"""Bounded in-memory LX06 S32 to BlackHole stereo ring buffer."""

import math
import threading

import numpy as np


class AudioBuffer:
    def __init__(self, capacity=24000, gain=8):
        if not isinstance(capacity, int) or not 0 < capacity <= 24000:
            raise ValueError('capacity must be 1..24000 output frames')
        if not math.isfinite(gain) or gain <= 0:
            raise ValueError('gain must be finite and positive')
        self.capacity, self.gain = capacity, gain
        self._ring = np.zeros(capacity, dtype=np.float32)
        self._lock = threading.Lock()
        self._head = self._size = 0
        self.dropped = self.received_frames = self.received_messages = 0
        self.underrun_frames = self.contention_frames = 0
        self._muted = False
        self._mute_generation = 0
        self.muted_s32_frames = self.muted_output_frames = self.pause_notices = 0

    def pause(self):
        """Mute persistently until explicit resume; never replay queued input."""
        with self._lock:
            self._muted = True
            self._mute_generation += 1
            self.pause_notices += 1
            self.muted_output_frames += self._size
            self._head = self._size = 0
            self._ring.fill(0)

    def resume(self):
        with self._lock:
            self._muted = False

    @property
    def muted(self):
        with self._lock:
            return self._muted

    @property
    def pending(self):
        with self._lock:
            return self._size

    def feed(self, pcm):
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 4 or len(pcm) > 256000:
            raise ValueError('Expected nonempty S32 binary PCM')
        with self._lock:
            self.received_frames += len(pcm) // 4
            self.received_messages += 1
            if self._muted:
                self.muted_s32_frames += len(pcm) // 4
                return
            generation = self._mute_generation
        # LX06 stores signed 16-bit samples in the high bits of little-endian S32.
        mono = (np.frombuffer(pcm, dtype='<i4') >> 16).astype(np.float32)
        mono *= self.gain / 32768.0
        np.clip(mono, -1, 1, out=mono)
        samples = np.repeat(mono, 3)
        with self._lock:
            if self._muted or generation != self._mute_generation:
                self.muted_s32_frames += len(mono)
                return
            overflow = max(0, self._size + len(samples) - self.capacity)
            self.dropped += overflow
            if len(samples) >= self.capacity:
                self._ring[:] = samples[-self.capacity:]
                self._head, self._size = 0, self.capacity
                return
            discard = min(overflow, self._size)
            self._head = (self._head + discard) % self.capacity
            self._size -= discard
            tail = (self._head + self._size) % self.capacity
            first = min(len(samples), self.capacity - tail)
            self._ring[tail:tail + first] = samples[:first]
            self._ring[:len(samples) - first] = samples[first:]
            self._size += len(samples)

    def drain_into(self, output):
        """Never wait for the producer: callback contention yields silence."""
        if output.ndim != 2 or output.shape[1] != 2:
            raise ValueError('output must have two channels')
        output.fill(0)
        frames = len(output)
        if not self._lock.acquire(blocking=False):
            self.contention_frames += frames
            return
        try:
            if self._muted:
                self.muted_output_frames += self._size
                self._head = self._size = 0
                return
            count = min(frames, self._size)
            first = min(count, self.capacity - self._head)
            for channel in (0, 1):
                output[:first, channel] = self._ring[self._head:self._head + first]
                output[first:count, channel] = self._ring[:count - first]
            self._head = (self._head + count) % self.capacity
            self._size -= count
            self.underrun_frames += frames - count
        finally:
            self._lock.release()

    def drain(self, frames):
        if not isinstance(frames, int) or frames < 0:
            raise ValueError('frames must be a nonnegative integer')
        output = np.empty((frames, 2), dtype=np.float32)
        self.drain_into(output)
        return output
