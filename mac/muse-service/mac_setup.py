"""Bounded, connection-isolated ingress around the unmodified pinned SDK."""
import collections
import threading
import sys
from musegadget.ble_setup import SetupController
from musegadget.pairing import PairingError


class _StaleConnection(ConnectionError):
    pass


class _PairingEpoch:
    def __init__(self, owner, pairing):
        self.owner = owner
        self.pairing = pairing

    def __getattr__(self, name):
        def call(*args, **kwargs):
            with self.owner._epoch_lock:
                self.owner._check_epoch()
                result = getattr(self.pairing, name)(*args, **kwargs)
                if name == 'mark_provisioning' and result:
                    self.owner._provision_epochs[result] = self.owner._epoch
                return result
        with self.owner._epoch_lock:
            self.owner._check_epoch()
            value = getattr(self.pairing, name)
            return call if callable(value) else value


class _TransportEpoch:
    def __init__(self, owner, transport):
        self.owner = owner
        self.transport = transport

    def mtu(self):
        with self.owner._epoch_lock:
            self.owner._check_epoch()
            return self.transport.mtu()

    def disconnect(self, delay):
        with self.owner._epoch_lock:
            self.owner._check_epoch()
            self.transport.disconnect(delay)

    def send_packets(self, packets):
        with self.owner._epoch_lock:
            self.owner._check_epoch()
            # Capture the sender before releasing the epoch lock. A replacement
            # central must never be selected by a delayed old worker.
            sender = getattr(self.transport, '_sender', None)
            send = sender.send_packets if sender else self.transport.send_packets
            if hasattr(self.transport, '_sender') and sender is None:
                raise _StaleConnection('BLE session ended')
        try:
            send(packets)
        except ConnectionError:
            # Cancellation of the captured sender after disconnect is normal.
            # An error belonging to the still-current connection fails closed.
            with self.owner._epoch_lock:
                self.owner._check_epoch()
            raise


class MacSetupController(SetupController):
    def __init__(self, *, max_commands=32, max_bytes=65536, **kwargs):
        self._epoch_lock = threading.RLock()
        self._condition = threading.Condition(self._epoch_lock)
        self._epoch = 0
        self._local = threading.local()
        self._pending = collections.deque()
        self._pending_bytes = 0
        self._max_commands = max_commands
        self._max_bytes = max_bytes
        self._closed = False
        self._stopping = False
        self._provision_epochs = {}
        self._raw_pairing = kwargs['pairing']
        self._raw_transport = kwargs['transport']
        kwargs['pairing'] = _PairingEpoch(self, kwargs['pairing'])
        kwargs['transport'] = _TransportEpoch(self, kwargs['transport'])
        provision = kwargs['provision']
        complete = kwargs.get('on_complete', lambda: None)
        def guarded_provision(credentials, commit):
            def guarded_commit(save):
                with self._epoch_lock:
                    self._check_epoch()
                    return commit(save)
            provision(credentials, guarded_commit)
        def guarded_complete():
            with self._epoch_lock:
                self._check_epoch()
                complete()
        kwargs['provision'] = guarded_provision
        kwargs['on_complete'] = guarded_complete
        super().__init__(**kwargs)
        # The SDK's unbounded inbox is unused; do not retain an admission path.
        del self._inbox
        self._state_lock = self._epoch_lock

    @property
    def pending_count(self):
        with self._epoch_lock: return len(self._pending)

    @property
    def pending_bytes(self):
        with self._epoch_lock: return self._pending_bytes

    @property
    def ingress_closed(self):
        with self._epoch_lock: return self._closed

    def _check_epoch(self):
        if self._closed or self._stopping or getattr(self._local, 'epoch', None) != self._epoch:
            raise _StaleConnection('BLE session ended')

    def _reset_locked(self):
        self._epoch += 1
        self._pending.clear()
        self._pending_bytes = 0
        self._assembler.reset()
        self._raw_pairing.reset()
        self._provision_epochs.clear()
        with self._state_lock: self._plaintext_blocked = False

    def on_write(self, packet):
        with self._condition:
            if self._closed or self._stopping: return
            message = self._assembler.feed(packet)
            if message is None: return
            if len(self._pending) >= self._max_commands or self._pending_bytes + len(message) > self._max_bytes:
                self._reset_locked()
                self._closed = True
                sender = getattr(self._raw_transport, '_sender', None)
                if sender: sender.cancel()
                self._raw_transport.disconnect(0)
                return
            self._pending.append((self._epoch, message))
            self._pending_bytes += len(message)
            self._condition.notify()

    def on_disconnect(self):
        with self._condition:
            self._reset_locked()
            self._closed = False

    def stop(self):
        with self._condition:
            self._stopping = True
            self._reset_locked()
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopping or self._pending)
                if self._stopping: return
                epoch, message = self._pending.popleft()
                self._pending_bytes -= len(message)
                self._local.epoch = epoch
            try:
                self.handle_message(message)
            except _StaleConnection:
                pass
            except Exception:
                self._fail_attempt()
                return

    def _fail_attempt(self):
        # Fixed diagnostic only: command contents and exception strings may
        # contain credentials. Stop ingress/protocol and advertising together.
        print('pairing_worker_failed', file=sys.stderr, flush=True)
        self.stop()
        sender = getattr(self._raw_transport, '_sender', None)
        if sender: sender.cancel()
        stop = getattr(self._raw_transport, 'stop', None)
        if stop:
            stop()
        else:
            self._raw_transport.disconnect(0)

    def _run_provision(self, credentials, generation):
        with self._epoch_lock:
            self._local.epoch = self._provision_epochs.pop(generation, None)
        try:
            super()._run_provision(credentials, generation)
        except _StaleConnection:
            pass
        except Exception:
            self._fail_attempt()

    def _handle_hello(self, command):
        # The SDK updates plaintext state after the pairing call. Serialize that
        # small update with reset; radio sends happen outside this lock.
        with self._epoch_lock:
            self._check_epoch()
            try:
                ready = self._pairing.handle_hello(command)
            except PairingError as error:
                ready = None
                status = error.status
            if ready is not None:
                with self._state_lock: self._plaintext_blocked = True
        if ready is None:
            self.send_status(status)
        else:
            self.send_json(ready)
