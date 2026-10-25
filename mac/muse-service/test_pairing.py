"""Behavior tests; no real credentials or Bluetooth radio needed."""
import contextlib
import io
import pathlib
import tempfile
import threading
import time
import unittest
import sys
sys.path.insert(0,str(pathlib.Path(__file__).parent/'vendor'))

class AdapterTests(unittest.TestCase):
    def sender(self, sink, **kwargs):
        from ble_macos import PacketSender
        return PacketSender(sink, **kwargs)

    def test_notification_order_pacing_and_backpressure(self):
        accepted=[];attempts=[];start=time.monotonic();ready=threading.Event()
        def sink(packet):
            attempts.append(packet)
            if not ready.is_set(): return False
            accepted.append((packet,time.monotonic()));return True
        sender=self.sender(sink,mtu=23,timeout=.5,stagger=.02)
        worker=threading.Thread(target=sender.send_packets,args=([b'one',b'two'],));worker.start()
        time.sleep(.015);self.assertEqual(accepted,[])
        ready.set();sender.ready();worker.join(.5)
        self.assertFalse(worker.is_alive());self.assertEqual([p for p,t in accepted],[b'one',b'two'])
        self.assertGreaterEqual(accepted[1][1]-accepted[0][1],.018)
        self.assertEqual(attempts[0],b'one')

    def test_notification_size_bounds_before_any_send(self):
        packets=[];sender=self.sender(lambda p:packets.append(p) or True,mtu=23)
        with self.assertRaises(ValueError):sender.send_packets([b'ok',b'x'*21])
        self.assertEqual(packets,[])

    def test_stalled_notify_times_out_and_cancel_wakes(self):
        sender=self.sender(lambda _:False,timeout=.02)
        with self.assertRaises(TimeoutError):sender.send_packets([b'x'])
        sender=self.sender(lambda _:False,timeout=10);errors=[]
        def send():
            try:sender.send_packets([b'x'])
            except Exception as e:errors.append(e)
        t=threading.Thread(target=send);t.start();time.sleep(.01);sender.cancel();t.join(.5)
        self.assertFalse(t.is_alive());self.assertIsInstance(errors[0],ConnectionError)

class PrivateStateTests(unittest.TestCase):
    def test_init_only_creates_private_identity_and_empty_token(self):
        from pair import initialize_state
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'private';out=io.StringIO()
            with contextlib.redirect_stdout(out):initialize_state(p)
            self.assertEqual(p.stat().st_mode&0o777,0o700)
            self.assertEqual((p/'identity.json').stat().st_mode&0o777,0o600)
            self.assertEqual((p/'sdk_token').read_text(),'')
            self.assertFalse((p/'pairing.json').exists())

    def test_credentials_rejected_without_network_or_persistence(self):
        from pair import verify_and_save
        from musegadget.ble_setup import Credentials,ProvisionFailed
        calls=[]
        with tempfile.TemporaryDirectory() as d:
            c=Credentials('secret-access','secret-refresh','','','http://bad','')
            with self.assertRaises(ProvisionFailed):verify_and_save(c,lambda save:save(),pathlib.Path(d),fetch=lambda *a:calls.append(a))
            self.assertEqual(calls,[]);self.assertFalse((pathlib.Path(d)/'pairing.json').exists())

    def test_credentials_verified_then_generation_committed_without_output(self):
        from pair import verify_and_save
        from musegadget.ble_setup import Credentials,ProvisionFailed
        c=Credentials('secret-access','secret-refresh','','','https://api.muse.ai','')
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);out=io.StringIO()
            with contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):
                verify_and_save(c,lambda save:save(),p,fetch=lambda *a:([{'vm_url':'wss://vm'}],200))
            self.assertEqual(out.getvalue(),'')
            self.assertEqual((p/'pairing.json').stat().st_mode&0o777,0o600)
            original=(p/'pairing.json').read_bytes()
            with self.assertRaises(ProvisionFailed):verify_and_save(c,lambda save:False,p,fetch=lambda *a:([{}],200))
            self.assertEqual((p/'pairing.json').read_bytes(),original)


class MoreStateTests(unittest.TestCase):
    def test_sdk_token_rejects_without_echoing_secret_and_preserves_identity(self):
        from pair import initialize_state,read_sdk_token
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);first=initialize_state(p);(p/'sdk_token').write_text('secret-token')
            with self.assertRaisesRegex(ValueError,'^SDK token file is invalid$'):read_sdk_token(p)
            self.assertEqual(initialize_state(p),first)

    def test_oversized_or_out_of_order_ble_chunk_is_discarded(self):
        from musegadget.ble_framing import ChunkAssembler,encode_chunks
        assembler=ChunkAssembler(max_bytes=10)
        self.assertIsNone(assembler.feed(b'\xfe\x00\x02'+b'a'*8))
        self.assertIsNone(assembler.feed(b'\xfe\x01\x02'+b'b'*8))
        self.assertIsNone(assembler.feed(b'\xfe\x01\x02x'))
        self.assertEqual(assembler.feed(b'\xfe\x00\x01ok'),b'ok')

    def test_pairing_expiry_drops_state_without_stale_commit(self):
        from musegadget.pairing import PairingSession,b64url_encode,PairingState
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        clock=[0];key=ec.generate_private_key(ec.SECP256R1())
        point=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        p=PairingSession(node_id='homelink-123456',device_id='hatch-link:02:00:00:12:34:56',mac='02:00:00:12:34:56',firmware_version='0.1.0',clock=lambda:clock[0])
        p.handle_hello({'version':5,'pairing_auth':'none','pairing_policy':'confirm_app','mobile_pub':b64url_encode(point),'mobile_nonce':b64url_encode(b'x'*16)})
        self.assertEqual(p.state,PairingState.WAIT_CLIENT_FINISHED)
        clock[0]=61;self.assertEqual(p.state,PairingState.IDLE)
        writes=[];self.assertFalse(p.commit_provisioning(1,lambda:writes.append(True)));self.assertEqual(writes,[])

class RunLoopTests(unittest.TestCase):
    def test_main_loop_accepts_packet_once_and_never_to_new_central(self):
        from ble_macos import BleServer
        class Manager:
            def __init__(self):self.packets=[]
            def updateValue_forCharacteristic_onSubscribedCentrals_(self,p,tx,central):self.packets.append((p,central));return True
        server=BleServer('test',lambda _:None,lambda:None);server._manager=Manager();server._tx=object();server._central=object()
        central=server._central;event=threading.Event();item=[b'x',event,None,central,server._connection_epoch];server._commands.append(item)
        server._pump();self.assertEqual(len(server._manager.packets),1);self.assertTrue(item[2]);self.assertTrue(event.is_set())
        item=[b'old',threading.Event(),None,central,server._connection_epoch];server._commands.append(item);server._central=object();server._pump()
        self.assertFalse(item[2]);self.assertEqual(len(server._manager.packets),1)

    def test_old_packet_rejected_when_same_central_resubscribes(self):
        from ble_macos import BleServer
        s=BleServer('test',lambda _:None,lambda:None);s._central=object()
        class Manager:
            def updateValue_forCharacteristic_onSubscribedCentrals_(self,*args):raise AssertionError('stale notification')
        s._manager=Manager();s._tx=object()
        item=[b'old',threading.Event(),None,s._central,s._connection_epoch]
        s._commands.append(item);s._connection_epoch+=1;s._pump()
        self.assertFalse(item[2]);self.assertTrue(item[1].is_set())

    def test_observed_advertising_retained_separately_from_current(self):
        from ble_macos import BleServer
        s=BleServer('test',lambda _:None,lambda:None)
        self.assertFalse(s.status()['advertising_observed'])
        s._record_advertising(True);s._record_advertising(False)
        self.assertTrue(s.status()['advertising_observed'])
        self.assertFalse(s.status()['advertising'])

class IngressTests(unittest.TestCase):
    def controller(self, **limits):
        from pair import MacSetupController
        from musegadget.identity import Identity
        from musegadget.pairing import PairingSession
        class Transport:
            def __init__(self): self.packets=[];self.stopped=False
            def send_packets(self, packets): self.packets.extend(packets)
            def mtu(self): return 512
            def disconnect(self, delay): pass
            def stop(self): self.stopped=True
        transport=Transport()
        pairing=PairingSession(node_id='test',device_id='test',mac='02:00:00:12:34:56',firmware_version='test')
        controller=MacSetupController(pairing=pairing,identity=Identity('02:00:00:12:34:56'),version='test',transport=transport,network=type('Network',(),{'is_online':lambda _:True})(),provision=lambda *a:None,**limits)
        return controller,pairing,transport

    def hello(self):
        import json
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        from musegadget.pairing import b64url_encode
        point=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        return json.dumps({'action':'pairing_client_hello','version':5,'pairing_auth':'none','pairing_policy':'confirm_app','mobile_pub':b64url_encode(point),'mobile_nonce':b64url_encode(b'x'*16)}).encode()

    def test_queued_old_hello_discarded_after_disconnect(self):
        c,p,t=self.controller();c.on_write(self.hello());c.on_disconnect();c.start()
        c.on_write(b'{"action":"get_device_info"}')
        deadline=time.monotonic()+1
        while not t.packets and time.monotonic()<deadline:time.sleep(.005)
        from musegadget.pairing import PairingState
        self.assertEqual(p.state,PairingState.IDLE)
        self.assertTrue(t.packets);self.assertNotIn(b'pairing_ready',b''.join(t.packets))
        c.stop();c._worker.join(1)

    def test_inflight_old_hello_cannot_mutate_or_send_after_disconnect(self):
        c,p,t=self.controller();entered=threading.Event();release=threading.Event();handled=threading.Event()
        original=c.handle_message
        def paused(raw,decrypted=False):
            entered.set();release.wait(1)
            try:original(raw,decrypted)
            finally:handled.set()
        c.handle_message=paused;c.start();c.on_write(self.hello());self.assertTrue(entered.wait(1))
        c.on_disconnect();release.set();self.assertTrue(handled.wait(1))
        from musegadget.pairing import PairingState
        self.assertEqual(p.state,PairingState.IDLE);self.assertEqual(t.packets,[])
        c.handle_message=original;c.on_write(self.hello())
        deadline=time.monotonic()+1
        while not t.packets and time.monotonic()<deadline:time.sleep(.005)
        self.assertTrue(t.packets);self.assertEqual(p.state,PairingState.WAIT_CLIENT_FINISHED)
        c.stop();c._worker.join(1)

    def test_disconnected_sender_cancellation_is_expected_and_quiet(self):
        c,p,t=self.controller();entered=threading.Event();release=threading.Event();finished=threading.Event();err=io.StringIO()
        def cancelled(packets):
            entered.set();release.wait(1)
            raise ConnectionError('secret transport details')
        t.send_packets=cancelled
        original=c.handle_message
        def handle(raw,decrypted=False):
            try: original(raw,decrypted)
            finally: finished.set()
        c.handle_message=handle
        with contextlib.redirect_stderr(err):
            c.start();c.on_write(self.hello());self.assertTrue(entered.wait(1))
            c.on_disconnect();release.set();self.assertTrue(finished.wait(1))
            # Wait for dispatch catch before observing whether it stopped.
            deadline=time.monotonic()+.1
            while not c._stopping and time.monotonic()<deadline:time.sleep(.001)
            self.assertFalse(c._stopping);self.assertFalse(t.stopped)
            c.stop();c._worker.join(1)
        self.assertEqual(err.getvalue(),'')

    def test_unexpected_worker_error_fails_closed_without_exception_text(self):
        c,p,t=self.controller();out=io.StringIO();err=io.StringIO()
        def broken(raw,decrypted=False):
            raise RuntimeError('secret-access secret-refresh peer-command')
        c.handle_message=broken
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            c.on_write(self.hello());c.on_write(b'{"action":"get_device_info"}');c.start()
            c._worker.join(1)
        self.assertFalse(c._worker.is_alive())
        self.assertTrue(t.stopped);self.assertTrue(c._stopping)
        self.assertEqual(c.pending_count,0);self.assertEqual(c.pending_bytes,0)
        self.assertEqual(t.packets,[])
        from musegadget.pairing import PairingState
        self.assertEqual(p.state,PairingState.IDLE)
        self.assertEqual(out.getvalue(),'')
        self.assertEqual(err.getvalue(),'pairing_worker_failed\n')
        c.on_write(self.hello());self.assertEqual(c.pending_count,0)

    def test_flood_bounded_count_and_bytes_and_resets_session(self):
        for limits,packet in [({'max_commands':2,'max_bytes':100},b'{}'),({'max_commands':20,'max_bytes':8},b'12345')]:
            c,p,t=self.controller(**limits)
            for _ in range(1000):c.on_write(packet)
            self.assertLessEqual(c.pending_count,limits['max_commands'])
            self.assertLessEqual(c.pending_bytes,limits['max_bytes'])
            self.assertTrue(c.ingress_closed)
            c.on_disconnect();self.assertFalse(c.ingress_closed)

class WriteBatchTests(unittest.TestCase):
    def scenario(self, values):
        from ble_macos import BleServer
        from types import SimpleNamespace
        received=[];responses=[]
        server=BleServer('test',received.append,lambda:None)
        server._rx=object();server._central=object()
        c=SimpleNamespace(CBATTErrorSuccess=0,CBATTErrorInvalidOffset=7,
            CBATTErrorInsufficientAuthorization=8,CBATTErrorInvalidAttributeValueLength=13,
            CBATTErrorUnlikelyError=14)
        requests=[SimpleNamespace(characteristic=lambda:server._rx,offset=lambda:0,
            central=lambda:server._central,value=lambda v=v:v) for v in values]
        manager=SimpleNamespace(respondToRequest_withResult_=lambda r,s:responses.append((r,s)))
        return server,c,requests,manager,received,responses

    def test_multiple_writes_get_one_response_on_first_request(self):
        server,c,requests,manager,received,responses=self.scenario([b'a',b'b'])
        server._receive_write_requests(manager,requests,c)
        self.assertEqual(received,[b'a',b'b'])
        self.assertEqual(responses,[(requests[0],0)])

    def test_invalid_batch_does_not_deliver_any_packet(self):
        server,c,requests,manager,received,responses=self.scenario([b'a',b''])
        server._receive_write_requests(manager,requests,c)
        self.assertEqual(received,[])
        self.assertEqual(responses,[(requests[0],13)])

    def test_unexpected_ingress_failure_stops_with_fixed_category(self):
        server,c,requests,manager,received,responses=self.scenario([b'a'])
        def fail(_):raise ValueError('secret-token-do-not-emit')
        server.on_write=fail
        server._receive_write_requests(manager,requests,c)
        self.assertTrue(server._stopped.is_set())
        self.assertEqual(server._fatal,'Bluetooth input failed')
        self.assertEqual(responses,[(requests[0],14)])

if __name__=='__main__':unittest.main()
