"""CoreBluetooth peripheral adapter for the pinned Muse BLE setup protocol.

Apple supports local name/service UUID advertising, not manufacturer data.
The main thread owns every CoreBluetooth operation; setup runs on its worker.
"""
from __future__ import annotations

import collections
import pathlib
import sys
import threading
import time
sys.path.insert(0,str(pathlib.Path(__file__).parent/'vendor'))
from musegadget.ble_framing import MAX_PACKET_BYTES,CHUNK_STAGGER_S

SERVICE_UUID='7fdd3d1c-38ea-46cf-8b46-314ecf5f240c'
RX_UUID='4d593029-28a2-4a6e-a1f0-3c2d5e8f9b01'
TX_UUID='d75dc4ca-7b2b-4e9c-8f0a-1d2e3f4a5b6c'

class PacketSender:
    """Bounded, paced sends with no loss when CoreBluetooth's queue is full."""
    def __init__(self,sink,*,mtu=23,timeout=10,stagger=CHUNK_STAGGER_S):
        self.sink=sink;self.mtu=mtu;self.timeout=timeout;self.stagger=stagger
        self._cancelled=threading.Event();self._ready=threading.Event();self._lock=threading.Lock()
    def ready(self):self._ready.set()
    def cancel(self):self._cancelled.set();self._ready.set()
    def send_packets(self,packets):
        if len(packets)>255 or any(not isinstance(p,bytes) or not p or len(p)>min(self.mtu-3,MAX_PACKET_BYTES) for p in packets):
            raise ValueError('BLE packet limit exceeded')
        with self._lock:
            deadline=time.monotonic()+self.timeout
            for index,packet in enumerate(packets):
                if index and self._cancelled.wait(self.stagger):raise ConnectionError('BLE session ended')
                while True:
                    if self._cancelled.is_set():raise ConnectionError('BLE session ended')
                    if time.monotonic()>=deadline:raise TimeoutError('BLE notification queue timed out')
                    self._ready.clear()
                    if self.sink(packet):break
                    self._ready.wait(min(.05,max(0,deadline-time.monotonic())))

class BleServer:
    """Official Transport interface; run() must execute on Python main thread."""
    def __init__(self,local_name,on_write,on_disconnect,*,startup_timeout=15):
        self.local_name=local_name;self.on_write=on_write;self.on_disconnect=on_disconnect
        self.startup_timeout=startup_timeout;self._stopped=threading.Event()
        self._state_lock=threading.Lock();self._commands=collections.deque();self._command_lock=threading.Lock()
        self._connection_epoch=0
        self._manager=None;self._tx=None;self._central=None;self._mtu=23;self._sender=None
        self._state='unknown';self._authorization=None;self._advertising=False;self._advertising_observed=False;self._fatal=None
        self._disconnect_deadline=None
    def mtu(self):
        with self._state_lock:return self._mtu
    def status(self):
        with self._state_lock:return {'state':self._state,'authorization':self._authorization,'advertising':self._advertising,'advertising_observed':self._advertising_observed,'manufacturer_data':False}
    def _record_advertising(self, active):
        with self._state_lock:
            self._advertising=bool(active)
            self._advertising_observed |= self._advertising
    def send_packets(self,packets):
        sender=self._sender
        if not sender:raise ConnectionError('BLE notifications not subscribed')
        sender.send_packets(packets)
    def disconnect(self,delay):
        # Peripheral API cannot force-disconnect an arbitrary central. Remove
        # services/advertisement and invalidate our protocol state after delay.
        self._disconnect_deadline=time.monotonic()+max(0,delay)
    def stop(self):
        self._stopped.set()
        if self._sender:self._sender.cancel()
    def _enqueue_packet(self,packet,central,epoch):
        # Called by PacketSender's worker. Wait for the main-thread updateValue
        # result rather than treating enqueue as radio acceptance.
        result=threading.Event();item=[packet,result,None,central,epoch]
        with self._command_lock:
            if self._stopped.is_set():raise ConnectionError('BLE session ended')
            if len(self._commands)>=255:raise BufferError('BLE notification queue limit')
            self._commands.append(item)
        deadline=time.monotonic()+10
        while not result.wait(.05):
            if self._stopped.is_set():raise ConnectionError('BLE session ended')
            if time.monotonic()>deadline:raise TimeoutError('CoreBluetooth run loop unavailable')
        return item[2]
    def _pump(self):
        if self._disconnect_deadline is not None and time.monotonic()>=self._disconnect_deadline:
            self._disconnect_deadline=None;self.stop();return
        with self._command_lock:items=list(self._commands);self._commands.clear()
        for item in items:
            packet,event,_,central,epoch=item
            item[2]=bool(epoch==self._connection_epoch and central is not None and central==self._central and self._manager.updateValue_forCharacteristic_onSubscribedCentrals_(packet,self._tx,[self._central]))
            event.set()
    def _receive_write_requests(self,manager,requests,C):
        # Apple requires a single response for the whole batch, addressed to
        # its first request. Validate all entries before handing any to setup.
        if not requests:return
        status=C.CBATTErrorSuccess;packets=[]
        for request in requests:
            if request.characteristic()!=self._rx or request.offset()!=0:
                status=C.CBATTErrorInvalidOffset;break
            if self._central is None or request.central()!=self._central:
                status=C.CBATTErrorInsufficientAuthorization;break
            value=request.value()
            if not value or len(value)>MAX_PACKET_BYTES:
                status=C.CBATTErrorInvalidAttributeValueLength;break
            packets.append(bytes(value))
        if status==C.CBATTErrorSuccess:
            try:
                for packet in packets:self.on_write(packet)
            except Exception:
                self._fatal='Bluetooth input failed';self.stop();self.on_disconnect()
                status=C.CBATTErrorUnlikelyError
        manager.respondToRequest_withResult_(requests[0],status)
    def run(self):
        if threading.current_thread() is not threading.main_thread():raise RuntimeError('CoreBluetooth requires the main thread')
        import CoreBluetooth as C
        import objc
        from Foundation import NSObject,NSRunLoop,NSDate
        owner=self
        class MusePeripheralDelegate(NSObject,protocols=[objc.protocolNamed('CBPeripheralManagerDelegate')]):
            def peripheralManagerDidUpdateState_(self,manager):
                state=int(manager.state());names={0:'unknown',1:'resetting',2:'unsupported',3:'unauthorized',4:'powered_off',5:'powered_on'}
                with owner._state_lock:owner._state=names.get(state,'unknown');owner._authorization=int(C.CBManager.authorization())
                if state!=C.CBManagerStatePoweredOn:
                    if state in (2,3,4):owner._fatal='Bluetooth '+names[state];owner.stop()
                    return
                owner._rx=C.CBMutableCharacteristic.alloc().initWithType_properties_value_permissions_(C.CBUUID.UUIDWithString_(RX_UUID),C.CBCharacteristicPropertyWrite|C.CBCharacteristicPropertyWriteWithoutResponse,None,C.CBAttributePermissionsWriteable)
                owner._tx=C.CBMutableCharacteristic.alloc().initWithType_properties_value_permissions_(C.CBUUID.UUIDWithString_(TX_UUID),C.CBCharacteristicPropertyRead|C.CBCharacteristicPropertyNotify,None,C.CBAttributePermissionsReadable)
                service=C.CBMutableService.alloc().initWithType_primary_(C.CBUUID.UUIDWithString_(SERVICE_UUID),True)
                service.setCharacteristics_([owner._rx,owner._tx]);owner._service=service;manager.addService_(service)
            def peripheralManager_didAddService_error_(self,manager,service,error):
                if error:owner._fatal='GATT service registration failed';owner.stop();return
                manager.startAdvertising_({C.CBAdvertisementDataLocalNameKey:owner.local_name,C.CBAdvertisementDataServiceUUIDsKey:[C.CBUUID.UUIDWithString_(SERVICE_UUID)]})
            def peripheralManagerDidStartAdvertising_error_(self,manager,error):
                if error:owner._fatal='Bluetooth advertising failed';owner.stop();return
                owner._record_advertising(manager.isAdvertising())
            def peripheralManager_central_didSubscribeToCharacteristic_(self,manager,central,characteristic):
                if characteristic!=owner._tx:return
                if owner._central is not None and owner._central!=central:return
                if owner._central==central:return
                owner._connection_epoch+=1
                owner._central=central
                with owner._state_lock:owner._mtu=min(central.maximumUpdateValueLength(),MAX_PACKET_BYTES)+3
                epoch=owner._connection_epoch
                owner._sender=PacketSender(lambda packet:owner._enqueue_packet(packet,central,epoch),mtu=owner.mtu())
            def peripheralManager_central_didUnsubscribeFromCharacteristic_(self,manager,central,characteristic):
                if central==owner._central:
                    owner._connection_epoch+=1
                    if owner._sender:owner._sender.cancel()
                    owner._sender=None;owner._central=None
                    with owner._state_lock:owner._mtu=23
                    owner.on_disconnect()
            def peripheralManagerIsReadyToUpdateSubscribers_(self,manager):
                if owner._sender:owner._sender.ready()
            def peripheralManager_didReceiveWriteRequests_(self,manager,requests):
                owner._receive_write_requests(manager,requests,C)
            def peripheralManager_didReceiveReadRequest_(self,manager,request):
                if request.characteristic()==owner._tx and request.offset()==0:
                    request.setValue_(b'');status=C.CBATTErrorSuccess
                else:status=C.CBATTErrorInvalidOffset
                manager.respondToRequest_withResult_(request,status)
        self._delegate=MusePeripheralDelegate.alloc().init()
        self._manager=C.CBPeripheralManager.alloc().initWithDelegate_queue_options_(self._delegate,None,{C.CBPeripheralManagerOptionShowPowerAlertKey:False})
        with self._state_lock:self._authorization=int(C.CBManager.authorization())
        deadline=time.monotonic()+self.startup_timeout
        try:
            while not self._stopped.is_set():
                NSRunLoop.mainRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.01));self._pump()
                if not self._advertising and time.monotonic()>deadline:
                    self._fatal='Bluetooth startup timeout (permission/state/advertising callback unavailable)';self.stop()
            if self._fatal:raise RuntimeError(self._fatal)
        finally:
            self.stop();self._manager.stopAdvertising();self._manager.removeAllServices();self._manager.setDelegate_(None)
            self._record_advertising(False)
            self.on_disconnect()
