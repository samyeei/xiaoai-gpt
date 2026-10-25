import importlib.util
import os
import io
import contextlib
import time
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

sd = types.SimpleNamespace(CallbackAbort=type('CallbackAbort', (Exception,), {}))
spec = importlib.util.spec_from_file_location('downlink', Path(__file__).with_name('downlink.py'))
# A missing implementation is reported as an assertion, so RED is explicit.
if Path(spec.origin).exists():
    downlink = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'sounddevice': sd}):
        spec.loader.exec_module(downlink)
else:
    downlink = None


class DownlinkTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(downlink, 'bounded downlink implementation is missing')

    def test_device_is_exact_and_never_default(self):
        devices = [{'name': 'BlackHole 2ch', 'max_input_channels': 2},
                   {'name': 'BlackHole 16ch', 'max_input_channels': 16}]
        self.assertEqual(downlink.select_blackhole(devices), 1)
        for invalid in ([], devices + [devices[1]], [devices[0]]):
            with self.assertRaises(RuntimeError):
                downlink.select_blackhole(invalid)

    def test_queue_discards_oldest_and_callback_aborts_on_exit(self):
        probe = downlink.DownlinkProbe(Mock(poll=Mock(return_value=None)))
        for i in range(10):
            probe.callback(bytes([i]) * 16, 4, None, False)
        self.assertEqual(probe.queue.qsize(), 8)
        self.assertEqual(probe.dropped_chunks, 2)
        self.assertEqual(probe.queue.get_nowait(), bytes([2]) * 16)
        probe.process.poll.return_value = 1
        with self.assertRaises(sd.CallbackAbort):
            probe.callback(b'\x00' * 16, 4, None, False)

    def test_ssh_mux_only_and_fixed_command(self):
        options = downlink.ssh_options('/tmp/task/control', '/tmp/task/known_hosts')
        self.assertIn('BatchMode=yes', options)
        self.assertIn('StrictHostKeyChecking=yes', options)
        self.assertIn('ProxyCommand=/usr/bin/false', options)
        self.assertIn('ControlMaster=no', options)
        self.assertIn('HostKeyAlgorithms=+ssh-rsa', options)
        self.assertEqual(downlink.PLAYER_COMMAND,
                         'aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000')
        with self.assertRaises(ValueError):
            downlink.ssh_options('relative', '/tmp/known_hosts')

    def test_mux_check_failure_never_starts_player(self):
        with patch.object(downlink.subprocess, 'run', return_value=Mock(returncode=1)), \
             patch.object(downlink.subprocess, 'Popen') as popen:
            with self.assertRaises(RuntimeError):
                downlink.start_player('root@192.168.100.3', '/tmp/control', '/tmp/known_hosts')
            popen.assert_not_called()

    def test_cleanup_wait_is_bounded_then_terminate_kill(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired('ssh', 3),
                                    subprocess.TimeoutExpired('ssh', 1), 0]
        downlink.close_player(process)
        process.stdin.close.assert_called_once()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual([c.kwargs['timeout'] for c in process.wait.call_args_list], [3, 1, 1])

    def test_duration_validation(self):
        for value in (0, -1, 301, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                downlink.validate_seconds(value)
        self.assertEqual(downlink.parse_args(['--host', 'root@192.168.100.3',
            '--control-path', '/tmp/control', '--known-hosts', '/tmp/known_hosts']).seconds, 60)

    def test_writer_pipe_stall_can_be_stopped(self):
        readfd, writefd = os.pipe()
        process = Mock(poll=Mock(return_value=None))
        process.stdin = os.fdopen(writefd, 'wb', buffering=0)
        probe = downlink.DownlinkProbe(process)
        probe.queue.put(b'\0' * 16384)
        probe.start_writer()
        probe.stop.set()
        probe.writer.join(timeout=1)
        self.assertFalse(probe.writer.is_alive())
        process.stdin.close()
        os.close(readfd)

    def test_run_uses_exact_raw_stream_and_cleans_up(self):
        process = Mock(poll=Mock(return_value=None), returncode=0)
        stream = Mock(active=True)
        fake_sd = types.SimpleNamespace(CallbackAbort=sd.CallbackAbort,
            query_devices=Mock(return_value=[{'name':'BlackHole 16ch','max_input_channels':16}]),
            RawInputStream=Mock(return_value=stream))
        with patch.object(downlink, 'sd', fake_sd), \
             patch.object(downlink, 'start_player', return_value=process), \
             patch.object(downlink.DownlinkProbe, 'start_writer'), \
             patch.object(downlink, 'close_player') as close:
            with contextlib.redirect_stdout(io.StringIO()):
                downlink.run_probe(.001, 'root@192.168.100.3', '/tmp/control', '/tmp/known_hosts')
        options = fake_sd.RawInputStream.call_args.kwargs
        self.assertEqual((options['device'], options['channels'], options['samplerate'], options['dtype']),
                         (0, 2, 48000, 'int16'))
        stream.stop.assert_called_once()
        stream.close.assert_called_once()
        close.assert_called_once_with(process)

    def test_writer_metrics_handle_int16_minimum_without_overflow(self):
        readfd, writefd = os.pipe()
        process = Mock(poll=Mock(return_value=None))
        process.stdin = os.fdopen(writefd, 'wb', buffering=0)
        probe = downlink.DownlinkProbe(process)
        probe.queue.put(b'\x00\x80\xff\x7f')
        probe.start_writer()
        deadline = time.monotonic() + 1
        while probe.written_bytes < 4 and time.monotonic() < deadline:
            time.sleep(.005)
        probe.stop.set()
        probe.writer.join(timeout=1)
        process.stdin.close()
        os.close(readfd)
        self.assertEqual(probe.written_bytes, 4)
        self.assertEqual(probe.stats()['input_peak'], 1.0)
        self.assertGreater(probe.stats()['input_rms'], .99)
        self.assertFalse(probe.writer_failed)

    def test_writer_broken_pipe_stops_and_marks_failure(self):
        readfd, writefd = os.pipe()
        os.close(readfd)
        process = Mock(poll=Mock(return_value=None))
        process.stdin = os.fdopen(writefd, 'wb', buffering=0)
        probe = downlink.DownlinkProbe(process)
        probe.queue.put(b'\0' * 16)
        probe.start_writer()
        probe.writer.join(timeout=1)
        process.stdin.close()
        self.assertFalse(probe.writer.is_alive())
        self.assertTrue(probe.writer_failed)
        self.assertTrue(probe.stop.is_set())

    def test_stream_start_error_still_closes_player(self):
        process = Mock(poll=Mock(return_value=None))
        stream = Mock()
        stream.start.side_effect = RuntimeError('capture unavailable')
        fake_sd = types.SimpleNamespace(CallbackAbort=sd.CallbackAbort,
            query_devices=Mock(return_value=[{'name':'BlackHole 16ch','max_input_channels':16}]),
            RawInputStream=Mock(return_value=stream))
        with patch.object(downlink, 'sd', fake_sd), \
             patch.object(downlink, 'start_player', return_value=process), \
             patch.object(downlink.DownlinkProbe, 'start_writer'), \
             patch.object(downlink, 'close_player') as close, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                downlink.run_probe(.001, 'root@192.168.100.3', '/tmp/control', '/tmp/known_hosts')
        stream.close.assert_called_once()
        close.assert_called_once_with(process)

    def test_optional_mute_is_fixed_port_only(self):
        base = ['--host', 'root@192.168.100.3', '--control-path', '/tmp/control',
                '--known-hosts', '/tmp/known_hosts']
        self.assertEqual(getattr(downlink.parse_args(base), 'mute_port', 'missing'), None)
        self.assertEqual(downlink.parse_args(base + ['--mute-port4416']).mute_port, 4416)
        with self.assertRaises(ValueError):
            downlink.DownlinkProbe(Mock(), mute_port=4417)


    def test_missing_pause_ack_prevents_spawn_and_audio(self):
        factory = Mock()
        gate = Mock(request=Mock(side_effect=RuntimeError('no acknowledgement')))
        probe = downlink.GatedDownlinkProbe(factory, gate)
        with self.assertRaises(RuntimeError):
            probe.forward_chunk(b'\x15\x00' * 8)
        factory.assert_not_called()
        self.assertEqual(probe.written_bytes, 0)
        gate.request.assert_called_once_with(b'pause', b'paused', probe.stop)

    def test_pause_ack_precedes_spawn_write_and_resume_follows_natural_drain(self):
        events = []
        process = Mock(poll=Mock(return_value=None))
        process.wait.side_effect = lambda **kw: events.append('drain') or 0
        gate = Mock(request=Mock(side_effect=lambda command, *args: events.append(command)))
        factory = Mock(side_effect=lambda: events.append('spawn') or process)
        probe = downlink.GatedDownlinkProbe(factory, gate)
        with patch.object(downlink.GatedDownlinkProbe, 'write_pcm',
                          side_effect=lambda *args: events.append('write') or True):
            probe.forward_chunk(b'\x15\x00' * 8)
            probe.forward_chunk(b'\x00' * (24000 * 4))
        self.assertEqual(events, [b'pause', 'spawn', 'write', 'write', 'drain', b'resume'])
        process.stdin.close.assert_called_once()
        process.wait.assert_called_once_with(timeout=3)
        self.assertIsNone(probe.process)

    def test_failed_drain_never_resumes_uplink(self):
        process = Mock(poll=Mock(return_value=None), wait=Mock(return_value=1))
        gate = Mock()
        probe = downlink.GatedDownlinkProbe(Mock(return_value=process), gate)
        with patch.object(probe, 'write_pcm', return_value=True):
            probe.forward_chunk(b'\x15\x00' * 8)
            with self.assertRaises(RuntimeError):
                probe.forward_chunk(b'\x00' * (24000 * 4))
        self.assertEqual([c.args[0] for c in gate.request.call_args_list], [b'pause'])
        self.assertIs(probe.process, process)

    def test_gated_silence_never_spawns_player(self):
        factory = Mock()
        gate = Mock()
        probe = downlink.GatedDownlinkProbe(factory, gate)
        probe.forward_chunk(b'\0' * 16384)
        factory.assert_not_called()
        gate.request.assert_not_called()

    def test_gated_shutdown_drain_timeout_is_finite_and_does_not_resume(self):
        process = Mock(poll=Mock(return_value=None))
        process.wait.side_effect = [subprocess.TimeoutExpired('ssh', 3),
                                    subprocess.TimeoutExpired('ssh', 1), 0]
        gate = Mock()
        probe = downlink.GatedDownlinkProbe(Mock(), gate)
        probe.process = process
        probe.shutdown()
        gate.request.assert_not_called()
        gate.close.assert_called_once()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()

    def test_pause_gate_bounded_retries_and_exact_ack(self):
        udp = Mock(recv=Mock(side_effect=BlockingIOError()))
        with patch.object(downlink.socket, 'socket', return_value=udp):
            gate = downlink.PauseGate(timeout=.001, attempts=3)
            with self.assertRaises(RuntimeError):
                gate.request(b'pause', b'paused', downlink.threading.Event())
            gate.close()
        self.assertEqual(udp.send.call_count, 3)
        self.assertTrue(all(call.args == (b'pause',) for call in udp.send.call_args_list))
        udp.connect.assert_called_once_with(('127.0.0.1', 4416))
        udp.setblocking.assert_called_once_with(False)
        udp.close.assert_called_once()

    def test_gated_stalled_pipe_keeps_pause_until_shutdown_without_resume(self):
        readfd, writefd = os.pipe()
        process = Mock(poll=Mock(return_value=None), wait=Mock(return_value=0))
        process.stdin = os.fdopen(writefd, 'wb', buffering=0)
        gate = Mock()
        probe = downlink.GatedDownlinkProbe(Mock(return_value=process), gate)
        probe.queue.put(b'\x15\x00' * 8192)
        probe.start_writer()
        time.sleep(.1)
        self.assertTrue(probe.gate_paused)
        self.assertEqual([c.args[0] for c in gate.request.call_args_list], [b'pause'])
        probe.stop.set()
        probe.writer.join(timeout=1)
        os.close(readfd)
        self.assertFalse(probe.writer.is_alive())
        self.assertEqual([c.args[0] for c in gate.request.call_args_list], [b'pause'])
        process.wait.assert_called_once_with(timeout=3)

    def test_gate_exact_ack_succeeds_and_stop_never_sends_resume(self):
        udp = Mock(recv=Mock(side_effect=[b'junk', b'paused']))
        with patch.object(downlink.socket, 'socket', return_value=udp):
            gate = downlink.PauseGate(timeout=.05)
            stopped = downlink.threading.Event()
            gate.request(b'pause', b'paused', stopped)
            stopped.set()
            with self.assertRaises(RuntimeError):
                gate.request(b'resume', b'resumed', stopped)
            gate.close()
        udp.send.assert_called_once_with(b'pause')



if __name__ == '__main__':
    unittest.main()
