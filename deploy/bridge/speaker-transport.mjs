import { EventEmitter } from 'node:events';
import { randomUUID } from 'node:crypto';
import { WebSocketServer, WebSocket } from 'ws';

// Open-XiaoAI's existing client protocol; no firmware replacement required.
export class SpeakerTransport extends EventEmitter {
  constructor({ port = 4399, host = '0.0.0.0', listen = true, allowedIP } = {}) {
    super(); this.socket = null; this.pending = new Map();
    this.server = listen ? new WebSocketServer({ port, host, maxPayload: 2 * 1024 * 1024 }) : null;
    this.accept = socket => {
      if (this.socket) { socket.close(1013, 'One speaker only'); return; }
      this.socket = socket; socket.alive = true;
      socket.on('pong', () => { socket.alive = true; });
      socket.on('error', () => {});
      socket.on('message', (data, binary) => this.message(socket, data, binary));
      socket.on('close', () => {
        if (this.socket !== socket) return;
        this.socket = null;
        for (const entry of this.pending.values()) { clearTimeout(entry.timer); entry.reject(new Error('Speaker disconnected')); }
        this.pending.clear(); this.emit('disconnected');
      });
      this.emit('connected');
    };
    this.server?.on('connection', (socket,req)=>{
      if(allowedIP&&req.socket.remoteAddress?.replace(/^::ffff:/,'')!==allowedIP){socket.on('error',()=>{});socket.close(1008,'Unknown speaker');return;}
      this.accept(socket);
    });
    this.ping = setInterval(() => {
      const s = this.socket; if (!s) return;
      if (!s.alive) { s.terminate(); return; } s.alive = false; s.ping();
    }, 15000); this.ping.unref();
  }
  message(socket, data, binary) {
    try {
      const packet = JSON.parse(data.toString());
      if (binary) {
        if (packet.tag === 'record' && Array.isArray(packet.bytes) && packet.bytes.length <= 256000 && packet.bytes.every(x => Number.isInteger(x) && x >= 0 && x <= 255)) {
          this.emit('audio', Buffer.from(packet.bytes));
        }
      } else if (packet.Response) {
        const reply = packet.Response, entry = this.pending.get(reply.id);
        if (!entry) return;
        clearTimeout(entry.timer); this.pending.delete(reply.id);
        if (reply.code && reply.code !== 0) entry.reject(new Error('Speaker RPC rejected'));
        else entry.resolve(reply.data);
      } else if (packet.Event) this.emit('event', packet.Event);
      else if (packet.Request?.command === 'get_version') socket.send(JSON.stringify({ Response: { id:packet.Request.id, data:'1.0.0' } }));
    } catch { /* Invalid frames cannot escape the transport. */ }
  }
  request(command, payload, timeout = 10000) {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return Promise.reject(new Error('Speaker unavailable'));
    const id = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('Speaker RPC timeout')); }, timeout);
      this.pending.set(id, {resolve, reject, timer});
      socket.send(JSON.stringify({ Request: { id, command, payload } }), error => {
        if (error && this.pending.delete(id)) { clearTimeout(timer); reject(new Error('Speaker send failed')); }
      });
    });
  }
  run_shell(script, timeout) { return this.request('run_shell', script, timeout); }
  startRecording() { return this.request('start_recording', {pcm:'noop', channels:1, bits_per_sample:32, sample_rate:16000, period_size:320, buffer_size:1280}); }
  async close() {
    clearInterval(this.ping);
    if (this.socket?.readyState === WebSocket.OPEN) {
      try { await this.request('stop_recording', null, 1500); } catch { /* bounded shutdown */ }
    }
    this.socket?.terminate(); if(this.server)await new Promise(r => this.server.close(r));
  }
}

export function nativeWake(event) {
  try {
    if (event.event !== 'instruction' || !event.data?.NewLine) return false;
    const line = JSON.parse(event.data.NewLine);
    return line.header?.namespace === 'SpeechRecognizer' && line.header?.name === 'RecognizeResult'
      && line.payload?.is_vad_begin === false && !line.payload?.results?.[0]?.text;
  } catch { return false; }
}
