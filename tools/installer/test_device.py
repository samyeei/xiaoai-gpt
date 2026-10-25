import base64
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from .core import InstallError, Journal
from .device import Device


class Remote:
    def __init__(self):
        self.files = {
            'route': b'ws://old:4399\n', 'init': b'#!/bin/sh\n',
            'keys': b'ssh-rsa OTHER other\n',
        }
        self.commands = []

    def __call__(self, args, input=None, interactive=False, timeout=8):
        self.commands.append((args, input, interactive))
        if args[0] == 'ssh-keygen':
            key = Path(args[args.index('-f') + 1])
            key.write_bytes(b'PRIVATE TEST FIXTURE')
            key.with_suffix('.pub').write_text('ssh-rsa QUJDREVG test\n')
            return subprocess.CompletedProcess(args, 0, b'', b'')
        script = args[-1]
        if '-O' in args:
            if args[args.index('-O') + 1] == 'exit':
                self.socket.unlink(missing_ok=True)
            return subprocess.CompletedProcess(args, 0, b'', b'')
        if '-fN' in args:
            if getattr(self, 'auth_fails', False):
                return subprocess.CompletedProcess(args, 255, b'', b'')
            self.socket.parent.mkdir(parents=True, exist_ok=True)
            self.socket.touch()
            return subprocess.CompletedProcess(args, 0, b'', b'')
        if 'DEVICE_PREFLIGHT' in script:
            if getattr(self, 'bad_model', False):
                return subprocess.CompletedProcess(args, 1, b'', b'')
            return subprocess.CompletedProcess(args, 0, b'LX06\n', b'')
        if 'DEVICE_READ_' in script:
            kind = script.split('DEVICE_READ_')[1].split('\n')[0].lower()
            value = self.files.get(kind)
            out = b'ABSENT\n' if value is None else b'PRESENT\n' + base64.b64encode(value) + b'\n'
            return subprocess.CompletedProcess(args, 0, out, b'')
        if 'DEVICE_CAS_' in script:
            kind = script.split('DEVICE_CAS_')[1].split('\n')[0].lower()
            expected, desired = input.split(b'\n', 1)
            current = self.files.get(kind)
            digest = hashlib.sha256(current).hexdigest().encode() if current is not None else b'ABSENT'
            if expected != digest:
                return subprocess.CompletedProcess(args, 14, b'', b'')
            if desired == b'ABSENT\n':
                self.files.pop(kind, None)
            else:
                self.files[kind] = base64.b64decode(desired)
            return subprocess.CompletedProcess(args, 0, b'OK\n', b'')
        if 'DEVICE_PROBE' in script:
            return subprocess.CompletedProcess(args, 1 if getattr(self, 'bad_restriction', False) else 0, b'', b'')
        if 'DEVICE_RESTART' in script:
            return subprocess.CompletedProcess(args, 0, b'OK\n', b'')
        return subprocess.CompletedProcess(args, 0, b'', b'')


class DeviceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        home = root / 'home'
        home.mkdir()
        self.journal = Journal(root, home)
        self.remote = Remote()
        self.device = Device(self.journal, {'speaker': '192.168.1.20', 'mac_ip': '192.168.1.21'}, self.remote)
        self.remote.socket = self.device.socket

    def test_prepare_snapshots_once_and_preserves_originals_on_resume(self):
        self.device.prepare()
        original = self.journal.data['device']['route']['before']
        self.remote.files['route'] = b'ws://192.168.1.21:4399\n'
        self.device.prepare()
        self.assertEqual(self.journal.data['device']['route']['before'], original)

    def test_activation_key_is_restricted_and_no_duplicate_line(self):
        self.device.prepare()
        self.device.activate()
        self.assertEqual(self.remote.files['route'], b'ws://192.168.1.21:4399\n')
        keys = self.remote.files['keys'].decode()
        self.assertEqual(keys.count('xiaoai-realtime-voice'), 1)
        self.assertIn('command="aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty', keys)
        self.device.activate()
        self.assertEqual(self.remote.files['keys'].decode().count('xiaoai-realtime-voice'), 1)
        probe = [item for item in self.remote.commands if 'DEVICE_PROBE' in item[0][-1]]
        self.assertTrue(probe)
        self.assertEqual(probe[-1][1], bytes(3840))

    def test_restore_preserves_external_keys_and_refuses_route_conflict(self):
        self.device.prepare()
        self.device.activate()
        self.remote.files['keys'] += b'ssh-rsa NEW external\n'
        self.remote.files['route'] = b'ws://foreign:4399\n'
        with self.assertRaises(InstallError):
            self.device.check_restore()
        self.assertIn(b'NEW external', self.remote.files['keys'])
        self.remote.files['route'] = b'ws://192.168.1.21:4399\n'
        self.device.restore()
        self.assertEqual(self.remote.files['route'], b'ws://old:4399\n')
        self.assertIn(b'NEW external', self.remote.files['keys'])
        self.assertNotIn(b'xiaoai-realtime-voice', self.remote.files['keys'])

    def test_managed_probe_cannot_use_management_mux(self):
        self.device.prepare()
        self.remote.bad_restriction = True
        with self.assertRaises(InstallError):
            self.device.activate()
        self.assertEqual(self.remote.files['route'], b'ws://old:4399\n')
        probe = [args for args, _, _ in self.remote.commands if 'DEVICE_PROBE' in args[-1]][-1]
        self.assertIn('ControlMaster=no', probe)
        self.assertIn('ControlPath=none', probe)
        self.assertIn('PubkeyAcceptedAlgorithms=+ssh-rsa', probe)

    def test_unknown_model_blocks_before_snapshot(self):
        self.remote.bad_model = True
        with self.assertRaises(InstallError):
            self.device.prepare()
        self.assertNotIn('device', self.journal.data)
        preflight = [args[-1] for args, _, _ in self.remote.commands if 'DEVICE_PREFLIGHT' in args[-1]][-1]
        self.assertIn('grep -a -q start_recording', preflight)

    def test_foreign_key_rejected_and_absent_auth_restored(self):
        self.device.key.parent.mkdir(parents=True)
        self.device.key.write_bytes(b'foreign')
        self.device.key.with_suffix('.pub').write_text('ssh-rsa QUJDREVG test\n')
        with self.assertRaises(InstallError):
            self.device.prepare()
        self.device.key.unlink()
        self.device.key.with_suffix('.pub').unlink()
        self.remote.files.pop('keys')
        self.journal.data.pop('device')
        self.device.prepare()
        self.device.activate()
        self.device.restore()
        self.assertNotIn('keys', self.remote.files)

    def test_noninteractive_trusted_auth_and_owned_mux_close(self):
        self.device.connect(interactive=False)
        self.assertTrue(self.device.socket.exists())
        self.device.close()
        self.assertFalse(self.device.socket.exists())
        start = [args for args, _, _ in self.remote.commands if '-fN' in args][0]
        self.assertIn('BatchMode=yes', start)
        self.assertIn('StrictHostKeyChecking=yes', start)
        self.assertIn('-F', start)
        self.remote.auth_fails = True
        with self.assertRaises(InstallError):
            self.device.connect(interactive=False)

    def test_retained_key_identity_survives_device_transaction_rollback(self):
        self.device.prepare()
        public = self.device.key.with_suffix('.pub').read_bytes()
        self.journal.data.pop('device')
        self.journal.save()
        self.device.prepare()
        self.assertEqual(self.device.key.with_suffix('.pub').read_bytes(),public)


if __name__ == '__main__':
    unittest.main()
