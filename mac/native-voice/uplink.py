"""Finite, opt-in loopback PCM uplink; saves no raw audio."""

import argparse
import asyncio
import json
import math
import signal

import numpy as np
import sounddevice as sd
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from audio_buffer import AudioBuffer


def select_blackhole(devices):
    matches = [index for index, device in enumerate(devices)
               if device['name'] == 'BlackHole 2ch'
               and device['max_input_channels'] >= 2
               and device['max_output_channels'] >= 2]
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one duplex device named BlackHole 2ch')
    return matches[0]


class MuteProtocol(asyncio.DatagramProtocol):
    def __init__(self, buffer):
        self.buffer = buffer
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if addr[0] != '127.0.0.1':
            return
        if data == b'pause':
            self.buffer.pause()
            acknowledgement = b'paused'
        elif data == b'resume':
            self.buffer.resume()
            acknowledgement = b'resumed'
        else:
            return
        if self.transport is not None:
            self.transport.sendto(acknowledgement, addr)


class UplinkProbe:
    def __init__(self):
        self.buffer = AudioBuffer()
        self.client_connected = False
        self.rejected_messages = self.connections = 0
        self.input_samples = self.input_frames = self.callback_count = 0
        self.input_energy = self.input_peak = 0.0
        self.callback_status_count = 0
        self.callback_failed = False

    def callback(self, indata, outdata, frames, time_info, status):
        try:
            self.buffer.drain_into(outdata)
            self.callback_count += 1
            self.callback_status_count += bool(status)
            self.input_frames += frames
            self.input_samples += indata.size
            # Scalar diagnostics only; returned driver input never retained.
            self.input_energy += float(np.einsum('ij,ij->', indata, indata))
            self.input_peak = max(self.input_peak, float(np.max(indata)),
                                  -float(np.min(indata)))
        except Exception:
            outdata.fill(0)
            self.callback_failed = True
            raise sd.CallbackAbort

    async def handle_client(self, websocket):
        if self.client_connected:
            await websocket.close(code=1013, reason='One bridge connection allowed')
            return
        self.client_connected = True
        self.connections += 1
        try:
            async for message in websocket:
                try:
                    self.buffer.feed(message)
                except ValueError:
                    self.rejected_messages += 1
                    await websocket.close(code=1003, reason='Expected nonempty S32 binary PCM')
                    break
        except ConnectionClosed:
            pass
        finally:
            self.client_connected = False

    def stats(self):
        return dict(received_messages=self.buffer.received_messages,
                    received_s32_frames=self.buffer.received_frames,
                    pending_output_frames=self.buffer.pending,
                    dropped_output_frames=self.buffer.dropped,
                    underrun_frames=self.buffer.underrun_frames,
                    contention_frames=self.buffer.contention_frames,
                    muted_s32_frames=self.buffer.muted_s32_frames,
                    muted_output_frames=self.buffer.muted_output_frames,
                    pause_notices=self.buffer.pause_notices,
                    muted=self.buffer.muted,
                    input_frames=self.input_frames, input_samples=self.input_samples,
                    input_rms=math.sqrt(self.input_energy / self.input_samples)
                    if self.input_samples else 0.0,
                    input_peak=self.input_peak, callbacks=self.callback_count,
                    callback_status_count=self.callback_status_count,
                    callback_failed=self.callback_failed,
                    rejected_messages=self.rejected_messages, connections=self.connections)


async def run_probe(seconds, mute_port=None):
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ValueError('seconds must be finite, greater than zero and at most 300')
    if mute_port not in (None, 4416):
        raise ValueError('mute_port must be None or 4416')
    probe = UplinkProbe()
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    stream = server = mute_transport = None
    installed_signals = []
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stopped.set)
            installed_signals.append(sig)
        device = select_blackhole(sd.query_devices())
        stream = sd.Stream(device=(device, device), samplerate=48000,
                           channels=(2, 2), dtype='float32', callback=probe.callback)
        server = await serve(probe.handle_client, '127.0.0.1', 4415,
                             origins=[None], max_size=256000, max_queue=8,
                             compression=None, close_timeout=1)
        if mute_port is not None:
            mute_transport, _ = await loop.create_datagram_endpoint(
                lambda: MuteProtocol(probe.buffer), local_addr=('127.0.0.1', mute_port))
        stream.start()
        deadline = loop.time() + seconds
        print(json.dumps(dict(event='started', seconds=seconds,
                              device='BlackHole 2ch', host='127.0.0.1', port=4415,
                              mute_port=mute_port)), flush=True)
        while not stopped.is_set():
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(stopped.wait(), timeout=min(5, remaining))
            except asyncio.TimeoutError:
                pass
            if probe.callback_failed or not stream.active:
                raise RuntimeError('BlackHole duplex callback stopped')
            print(json.dumps(dict(event='stats', **probe.stats())), flush=True)
    finally:
        try:
            if stream is not None:
                try:
                    stream.stop()
                finally:
                    stream.close()
        finally:
            try:
                if server is not None:
                    server.close()
                    await server.wait_closed()
            finally:
                try:
                    if mute_transport is not None:
                        mute_transport.close()
                finally:
                    for sig in installed_signals:
                        loop.remove_signal_handler(sig)
                    print(json.dumps(dict(event='final', **probe.stats())), flush=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--mute-port4416', dest='mute_port', action='store_const',
                        const=4416, default=None, help='Enable loopback acoustic echo mute gate')
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 300:
        parser.error('--seconds must be finite, greater than zero and at most 300')
    return args


if __name__ == '__main__':
    try:
        args = parse_args()
        asyncio.run(run_probe(args.seconds, mute_port=args.mute_port))
    except Exception as error:
        # Do not print payloads or exception details from external input.
        print(json.dumps(dict(event='error', error_type=type(error).__name__)), flush=True)
        raise SystemExit(1)
