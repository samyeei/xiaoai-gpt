import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from uplink import MuteProtocol, UplinkProbe, parse_args, run_probe, select_blackhole


class UplinkTests(unittest.TestCase):
    def test_only_exact_pause_resume_from_loopback_are_acked(self):
        buffer = Mock()
        protocol = MuteProtocol(buffer)
        transport = Mock()
        protocol.connection_made(transport)
        for message in [b'', b'pause\n', b'resume\n', b'PAUSE', b'pauseextra']:
            protocol.datagram_received(message, ('127.0.0.1', 12345))
        protocol.datagram_received(b'pause', ('192.168.100.1', 12345))
        buffer.pause.assert_not_called()
        buffer.resume.assert_not_called()
        transport.sendto.assert_not_called()
        protocol.datagram_received(b'pause', ('127.0.0.1', 12345))
        buffer.pause.assert_called_once_with()
        transport.sendto.assert_called_with(b'paused', ('127.0.0.1', 12345))
        protocol.datagram_received(b'resume', ('127.0.0.1', 12345))
        buffer.resume.assert_called_once_with()
        transport.sendto.assert_called_with(b'resumed', ('127.0.0.1', 12345))

    def test_only_fixed_optional_mute_port(self):
        self.assertIsNone(parse_args([]).mute_port)
        self.assertEqual(parse_args(['--mute-port4416']).mute_port, 4416)
        with self.assertRaises(SystemExit), patch('sys.stderr'):
            parse_args(['--mute-port', '4444'])
        with self.assertRaises(ValueError): asyncio.run(run_probe(1, mute_port=4444))

    def test_finite_udp_cleanup_on_completion_and_start_failure(self):
        async def exercise(fail):
            loop = asyncio.get_running_loop()
            stream = Mock(active=True)
            if fail: stream.start.side_effect = RuntimeError('start failure')
            server = Mock(wait_closed=AsyncMock())
            transport = Mock()
            with patch('uplink.sd.query_devices', return_value=[dict(
                    name='BlackHole 2ch', max_input_channels=2, max_output_channels=2)]), \
                 patch('uplink.sd.Stream', return_value=stream), \
                 patch('uplink.serve', new=AsyncMock(return_value=server)), \
                 patch.object(loop, 'create_datagram_endpoint', new=AsyncMock(
                     return_value=(transport, Mock()))) as udp, patch('builtins.print'):
                if fail:
                    with self.assertRaises(RuntimeError): await run_probe(1, mute_port=4416)
                else:
                    await run_probe(.001, mute_port=4416)
            self.assertEqual(udp.call_args.kwargs['local_addr'], ('127.0.0.1', 4416))
            transport.close.assert_called_once()
            stream.close.assert_called_once()
        asyncio.run(exercise(False))
        asyncio.run(exercise(True))

    def test_exact_duplex_device_only(self):
        devices = [dict(name='BlackHole 2ch extra', max_input_channels=2, max_output_channels=2),
                   dict(name='BlackHole 2ch', max_input_channels=2, max_output_channels=2)]
        self.assertEqual(select_blackhole(devices), 1)
        with self.assertRaises(RuntimeError):
            select_blackhole(devices[:1])
        with self.assertRaises(RuntimeError):
            select_blackhole(devices + devices[1:])

    def test_duration_is_finite_and_bounded(self):
        self.assertEqual(parse_args([]).seconds, 60)
        self.assertEqual(parse_args(['--seconds', '300']).seconds, 300)
        for value in ['0', '301', 'nan', 'inf']:
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                parse_args(['--seconds', value])

    def test_run_api_cannot_bypass_finite_duration(self):
        for value in [0, 301, float('inf'), float('nan')]:
            with self.assertRaises(ValueError): asyncio.run(run_probe(value))

    def test_callback_outputs_and_counts_returned_input(self):
        probe = UplinkProbe()
        probe.buffer.feed(np.array([16384 << 16], dtype='<i4').tobytes())
        output = np.empty((5, 2), dtype=np.float32)
        probe.callback(np.full((5, 2), .25, dtype=np.float32), output, 5, None, False)
        self.assertTrue((output[:3] == 1).all())
        self.assertFalse(output[3:].any())
        stats = probe.stats()
        self.assertEqual(stats['input_samples'], 10)
        self.assertEqual(stats['input_peak'], .25)
        self.assertEqual(stats['input_rms'], .25)

    def test_one_client_and_malformed_rejection(self):
        class Socket:
            def __init__(self, frames): self.frames, self.close = frames, Mock()
            def __aiter__(self): return self
            async def __anext__(self):
                if not self.frames: raise StopAsyncIteration
                return self.frames.pop(0)
        async def exercise():
            probe = UplinkProbe()
            good = Socket([b'\x00' * 4, b'123', 'text'])
            good.close = Mock(side_effect=lambda **kwargs: asyncio.sleep(0))
            await probe.handle_client(good)
            self.assertEqual(probe.buffer.received_frames, 1)
            self.assertEqual(probe.rejected_messages, 1)
            good.close.assert_called_once_with(code=1003, reason='Expected nonempty S32 binary PCM')
            probe.client_connected = True
            other = Socket([])
            other.close = Mock(side_effect=lambda **kwargs: asyncio.sleep(0))
            await probe.handle_client(other)
            other.close.assert_called_once_with(code=1013, reason='One bridge connection allowed')
        asyncio.run(exercise())

    def test_finite_probe_closes_one_duplex_stream_and_loopback_server(self):
        stream = Mock(active=True)
        server = Mock(wait_closed=AsyncMock())
        with patch('uplink.sd.query_devices', return_value=[dict(
                name='BlackHole 2ch', max_input_channels=2, max_output_channels=2)]), \
             patch('uplink.sd.Stream', return_value=stream) as factory, \
             patch('uplink.serve', new=AsyncMock(return_value=server)) as listener, \
             patch('builtins.print'):
            asyncio.run(run_probe(.001))
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['device'], (0, 0))
        self.assertEqual(factory.call_args.kwargs['samplerate'], 48000)
        stream.start.assert_called_once()
        stream.stop.assert_called_once()
        stream.close.assert_called_once()
        server.close.assert_called_once()
        server.wait_closed.assert_awaited_once()
        self.assertEqual(listener.call_args.args[1:], ('127.0.0.1', 4415))
        self.assertEqual(listener.call_args.kwargs['origins'], [None])
        self.assertEqual(listener.call_args.kwargs['max_size'], 256000)
        self.assertEqual(listener.call_args.kwargs['max_queue'], 8)

    def test_stream_start_exception_also_closes_resources(self):
        stream = Mock()
        stream.start.side_effect = RuntimeError('start failure')
        server = Mock(wait_closed=AsyncMock())
        with patch('uplink.sd.query_devices', return_value=[dict(
                name='BlackHole 2ch', max_input_channels=2, max_output_channels=2)]), \
             patch('uplink.sd.Stream', return_value=stream), \
             patch('uplink.serve', new=AsyncMock(return_value=server)), \
             patch('builtins.print'):
            with self.assertRaises(RuntimeError): asyncio.run(run_probe(1))
        stream.close.assert_called_once()
        server.close.assert_called_once()
        server.wait_closed.assert_awaited_once()

    def test_sigterm_event_stops_and_cleans_up(self):
        stream = Mock(active=True)
        server = Mock(wait_closed=AsyncMock())
        mute_transport = Mock()
        async def exercise():
            loop = asyncio.get_running_loop()
            installed = {}
            def register(sig, handler): installed[sig] = handler
            async def start_server(*args, **kwargs):
                import signal
                installed[signal.SIGTERM]()
                return server
            with patch.object(loop, 'add_signal_handler', side_effect=register), \
                 patch('uplink.sd.query_devices', return_value=[dict(
                     name='BlackHole 2ch', max_input_channels=2, max_output_channels=2)]), \
                 patch('uplink.sd.Stream', return_value=stream), \
                 patch('uplink.serve', new=start_server), \
                 patch.object(loop, 'create_datagram_endpoint', new=AsyncMock(
                     return_value=(mute_transport, Mock()))), patch('builtins.print'):
                await run_probe(300, mute_port=4416)
        asyncio.run(exercise())
        stream.close.assert_called_once()
        server.wait_closed.assert_awaited_once()
        mute_transport.close.assert_called_once()
