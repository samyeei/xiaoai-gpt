import { WebSocket } from 'ws';

const URL = 'ws://127.0.0.1:4415';
const MAX_DURATION = 300000;

export function nativeAudioOptIn(flag, now = Date.now()) {
  if (!flag || typeof flag !== 'object' || Array.isArray(flag)
      || Object.keys(flag).length !== 1 || !Number.isSafeInteger(flag.expires_at)
      || flag.expires_at <= now || flag.expires_at - now > MAX_DURATION) return {};
  return { native_audio_url: URL, native_audio_expires_at: flag.expires_at };
}

// A passive consumer of the existing speaker transport. No recording RPCs or PCM storage.
export class AudioMirror {
  constructor(config = {}, { connect = (url, options) => new WebSocket(url, options), retryDelays = [500, 1000, 2000] } = {}) {
    this.socket = null; this.closed = true; this.frames = 0; this.backpressure = 0;
    this.connectSocket = connect; this.retryDelays = retryDelays; this.attempt = 0;
    const flag = nativeAudioOptIn({ expires_at: config.native_audio_expires_at });
    if (config.native_audio_url !== URL || !flag.native_audio_url) return;
    this.expiresAt = flag.native_audio_expires_at; this.closed = false;
    this.expiry = setTimeout(() => this.close(), this.expiresAt - Date.now()); this.expiry.unref?.();
    this.connect();
  }
  status() { return { connected: !this.closed && this.socket?.readyState === WebSocket.OPEN, frames_sent: this.frames, backpressure: this.backpressure }; }
  connect() {
    if (this.closed) return;
    if (Date.now() >= this.expiresAt) { this.close(); return; }
    let socket;
    try { socket = this.connectSocket(URL, { maxPayload: 65536, handshakeTimeout: 3000 }); }
    catch { this.scheduleRetry(); return; }
    this.socket = socket;
    socket.on('error', () => {});
    // This endpoint is uplink only; unsolicited input closes it without parsing or logging.
    socket.on('message', () => socket.terminate());
    socket.once('close', () => {
      if (this.socket !== socket) return;
      this.socket = null; this.scheduleRetry();
    });
  }
  scheduleRetry() {
    if (this.closed || this.attempt >= this.retryDelays.length) return;
    const delay = this.retryDelays[this.attempt++];
    if (Date.now() + delay >= this.expiresAt) return;
    this.retry = setTimeout(() => { this.retry = null; this.connect(); }, delay); this.retry.unref?.();
  }
  audio(data) {
    if (this.closed) return;
    if (Date.now() >= this.expiresAt) { this.close(); return; }
    const socket = this.socket;
    if (socket?.readyState !== WebSocket.OPEN) return;
    if (socket.bufferedAmount > 128000 || socket.bufferedAmount + data.length > 128000) {
      this.backpressure++; socket.terminate(); return;
    }
    try {
      socket.send(data, {binary:true}, error => {
        if (error) socket.terminate();
        else this.frames++;
      });
    } catch { socket.terminate(); }
  }
  close() {
    this.closed = true; clearTimeout(this.retry); clearTimeout(this.expiry);
    const socket = this.socket; this.socket = null; socket?.terminate();
  }
}
