"""Opt-in finite BlackHole 16ch to authenticated SSH mux speaker probe.

Only scalar diagnostics reach stdout. No PCM is saved. Run from the native
voice virtualenv; requires an already authenticated task-owned ControlMaster.
"""

import argparse
import array
import json
import math
import os
import queue
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time

import sounddevice as sd

PLAYER_COMMAND = 'aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000'


def validate_seconds(seconds):
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ValueError('seconds must be finite, greater than zero and at most 300')


def select_blackhole(devices):
    matches = [index for index, device in enumerate(devices)
               if device['name'] == 'BlackHole 16ch'
               and device['max_input_channels'] >= 2]
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one input device named BlackHole 16ch')
    return matches[0]


def ssh_options(control_path, known_hosts):
    if not os.path.isabs(control_path) or not os.path.isabs(known_hosts):
        raise ValueError('Control socket and scoped known hosts must be absolute paths')
    return ['ssh', '-S', control_path, '-o', 'ControlMaster=no',
            '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile=' + known_hosts,
            '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'HostKeyAlgorithms=+ssh-rsa',
            # An existing mux ignores ProxyCommand; a vanished mux cannot
            # reconnect or silently open a fresh authentication connection.
            '-o', 'ProxyCommand=/usr/bin/false',
            '-o', 'ConnectTimeout=3', '-o', 'ConnectionAttempts=1']


def check_mux(host, control_path, known_hosts):
    if not host or host.startswith('-') or any(c.isspace() for c in host):
        raise ValueError('Expected an SSH host target')
    options = ssh_options(control_path, known_hosts)
    check = subprocess.run(options + ['-O', 'check', host], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3, check=False)
    if check.returncode:
        raise RuntimeError('Task SSH mux is not available')
    return options


def start_player(host, control_path, known_hosts):
    options = check_mux(host, control_path, known_hosts)
    return subprocess.Popen(options + ['-T', host, PLAYER_COMMAND],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, bufsize=0)


def close_player(process):
    try:
        process.stdin.close()
    except (OSError, BrokenPipeError):
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


class DownlinkProbe:
    def __init__(self, process, mute_port=None):
        if mute_port is not None:
            raise ValueError('Persistent mute requires GatedDownlinkProbe')
        self.mute_port = None
        self.mute_signals = 0
        self.process = process
        self.queue = queue.Queue(maxsize=8)
        self.stop = threading.Event()
        self.writer = None
        self.writer_failed = self.callback_failed = False
        self.callbacks = self.status_count = self.dropped_chunks = 0
        self.captured_frames = self.measured_samples = self.written_bytes = 0
        self.energy = 0
        self.peak = 0

    def player_exited(self):
        return self.process is not None and self.process.poll() is not None

    def callback(self, indata, frames, time_info, status):
        # PortAudio callback does no network IO, PCM analysis, or disk IO.
        if self.stop.is_set() or self.player_exited():
            self.stop.set()
            raise sd.CallbackAbort
        try:
            chunk = bytes(indata)
            self.callbacks += 1
            self.captured_frames += frames
            self.status_count += bool(status)
            try:
                self.queue.put_nowait(chunk)
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    self.dropped_chunks += 1
                except queue.Empty:
                    pass
                self.queue.put_nowait(chunk)
        except Exception:
            self.callback_failed = True
            self.stop.set()
            raise sd.CallbackAbort

    def start_writer(self):
        self.writer = threading.Thread(target=self.write_chunks,
                                       name='downlink-pcm-writer', daemon=True)
        self.writer.start()

    def measure_chunk(self, chunk):
        samples = array.array('h')
        samples.frombytes(chunk)
        block_energy = sum(int(sample) ** 2 for sample in samples)
        self.measured_samples += len(samples)
        self.energy += block_energy
        self.peak = max(self.peak, max((abs(int(s)) for s in samples), default=0))
        return bool(samples) and block_energy > 400 * len(samples)

    def write_pcm(self, chunk):
        fd = self.process.stdin.fileno()
        os.set_blocking(fd, False)
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_WRITE)
            pending = memoryview(chunk)
            while pending and not self.stop.is_set():
                if self.process.poll() is not None:
                    raise BrokenPipeError
                if not selector.select(timeout=.05):
                    continue
                try:
                    count = os.write(fd, pending)
                except BlockingIOError:
                    continue
                if not count:
                    raise BrokenPipeError
                self.written_bytes += count
                pending = pending[count:]
        return not pending

    def forward_chunk(self, chunk):
        self.measure_chunk(chunk)
        self.write_pcm(chunk)

    def write_chunks(self):
        try:
            while not self.stop.is_set():
                if self.process is not None and self.process.poll() is not None:
                    raise BrokenPipeError
                try:
                    chunk = self.queue.get(timeout=.05)
                except queue.Empty:
                    continue
                self.forward_chunk(chunk)
        except Exception:
            self.writer_failed = True
            self.stop.set()
        finally:
            if isinstance(self, GatedDownlinkProbe):
                try:
                    self.shutdown()
                except Exception:
                    self.writer_failed = True
                    self.stop.set()

    def shutdown(self):
        if self.process is not None:
            process, self.process = self.process, None
            close_player(process)

    def stats(self):
        return dict(callbacks=self.callbacks, callback_status_count=self.status_count,
                    captured_frames=self.captured_frames, measured_samples=self.measured_samples,
                    input_rms=math.sqrt(self.energy / self.measured_samples) / 32768
                    if self.measured_samples else 0.0, input_peak=self.peak / 32768,
                    written_bytes=self.written_bytes, dropped_chunks=self.dropped_chunks,
                    pending_chunks=self.queue.qsize(), callback_failed=self.callback_failed,
                    writer_failed=self.writer_failed, mute_signals=self.mute_signals)


class PauseGate:
    """Loopback-only persistent mute handshake; lost ACKs stop playback."""
    def __init__(self, timeout=.5, attempts=3):
        self.timeout, self.attempts = timeout, attempts
        self.socket = None

    def request(self, command, acknowledgement, stopped):
        if self.socket is None:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setblocking(False)
            self.socket.connect(('127.0.0.1', 4416))
        for _ in range(self.attempts):
            if stopped.is_set():
                raise RuntimeError('Mute handshake stopped')
            try:
                self.socket.send(command)
            except OSError:
                pass
            deadline = time.monotonic() + self.timeout
            while not stopped.is_set() and time.monotonic() < deadline:
                try:
                    if self.socket.recv(16) == acknowledgement:
                        return
                except OSError:
                    pass
                stopped.wait(min(.01, max(0, deadline - time.monotonic())))
        raise RuntimeError('Mute acknowledgement missing')

    def close(self):
        if self.socket is not None:
            sock, self.socket = self.socket, None
            sock.close()


class GatedDownlinkProbe(DownlinkProbe):
    """One aplay child per utterance, with acknowledged mute and EOF drain."""
    def __init__(self, player_factory, gate):
        super().__init__(None)
        self.mute_port = 4416
        self.player_factory = player_factory
        self.gate = gate
        self.silent_frames = 0
        self.utterances = 0
        self.gate_paused = False

    def player_exited(self):
        # Worker alone owns per-utterance EOF/drain. A successful exit while
        # draining must not make the capture callback or supervisor abort.
        return False

    def forward_chunk(self, chunk):
        active_audio = self.measure_chunk(chunk)
        if self.process is None:
            if not active_audio:
                return
            # ACK must precede both the remote player spawn and PCM write.
            self.gate.request(b'pause', b'paused', self.stop)
            self.gate_paused = True
            if self.stop.is_set():
                return
            self.process = self.player_factory()
            self.mute_signals += 1
            self.utterances += 1
            self.silent_frames = 0
        if not self.write_pcm(chunk):
            return
        self.silent_frames = 0 if active_audio else self.silent_frames + len(chunk) // 4
        if self.silent_frames >= 24000:
            self.process.stdin.close()
            # EOF must drain naturally and exit successfully. A timeout or
            # error is fatal and never releases the persistent uplink mute.
            code = self.process.wait(timeout=3)
            if code != 0:
                raise RuntimeError('Utterance player drain failed')
            self.process = None
            self.silent_frames = 0
            if not self.stop.is_set():
                self.gate.request(b'resume', b'resumed', self.stop)
                self.gate_paused = False

    def shutdown(self):
        # Ending/error paths deliberately never send resume. Session cleanup
        # owns disposal of the muted receiver. Child cleanup stays bounded.
        try:
            super().shutdown()
        finally:
            self.gate.close()

    def stats(self):
        return dict(super().stats(), utterances=self.utterances,
                    gate_paused=self.gate_paused)


def run_probe(seconds, host, control_path, known_hosts, mute_port=None):
    validate_seconds(seconds)
    if mute_port not in (None, 4416):
        raise ValueError('Optional mute port must be 4416')
    if sys.byteorder != 'little':
        raise RuntimeError('S16_LE capture requires a little endian host')
    process = probe = stream = None
    old_signals = {}
    try:
        device = select_blackhole(sd.query_devices())
        if mute_port is None:
            process = start_player(host, control_path, known_hosts)
            probe = DownlinkProbe(process)
        else:
            check_mux(host, control_path, known_hosts)
            probe = GatedDownlinkProbe(
                lambda: start_player(host, control_path, known_hosts), PauseGate())
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_signals[sig] = signal.signal(sig, lambda *_: probe.stop.set())
        probe.start_writer()
        stream = sd.RawInputStream(device=device, samplerate=48000, channels=2,
                                   dtype='int16', blocksize=4096, callback=probe.callback)
        stream.start()
        deadline = time.monotonic() + seconds
        print(json.dumps(dict(event='started', seconds=seconds,
                              device='BlackHole 16ch', channels=2, samplerate=48000)), flush=True)
        next_stats = time.monotonic() + 5
        while not probe.stop.is_set() and time.monotonic() < deadline:
            if probe.player_exited() or not stream.active:
                raise RuntimeError('Downlink player or capture stopped')
            probe.stop.wait(min(.05, max(0, deadline - time.monotonic())))
            if time.monotonic() >= next_stats:
                print(json.dumps(dict(event='stats', **probe.stats())), flush=True)
                next_stats = time.monotonic() + 5
        if probe.writer_failed or probe.callback_failed or probe.player_exited():
            raise RuntimeError('Downlink interrupted by player or callback failure')
    finally:
        if probe is not None:
            probe.stop.set()
        try:
            if stream is not None:
                try:
                    stream.stop()
                finally:
                    stream.close()
        finally:
            try:
                if probe is not None and probe.writer is not None:
                    # Handshake/start check <=3 sec plus player cleanup <=5.
                    probe.writer.join(timeout=9)
                    if probe.writer.is_alive():
                        raise RuntimeError('Downlink writer cleanup timed out')
                if probe is not None:
                    probe.shutdown()
            finally:
                for sig, previous in old_signals.items():
                    signal.signal(sig, previous)
                if probe is not None:
                    print(json.dumps(dict(event='final', **probe.stats())), flush=True)
    if probe.writer_failed or probe.callback_failed:
        raise RuntimeError('Downlink writer or callback failed')
    if process is not None and process.returncode != 0:
        raise RuntimeError('Downlink player returned failure')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--host', required=True)
    parser.add_argument('--control-path', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--mute-port4416', dest='mute_port', action='store_const',
                        const=4416, default=None,
                        help='Pause local uplink while forwarding active speaker audio')
    args = parser.parse_args(argv)
    try:
        validate_seconds(args.seconds)
        ssh_options(args.control_path, args.known_hosts)
    except ValueError as error:
        parser.error(str(error))
    return args


if __name__ == '__main__':
    try:
        args = parse_args()
        run_probe(args.seconds, args.host, args.control_path, args.known_hosts, args.mute_port)
    except Exception as error:
        print(json.dumps(dict(event='error', error_type=type(error).__name__)), flush=True)
        raise SystemExit(1)
