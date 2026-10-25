import { setTimeout as delay } from 'node:timers/promises';

export class MuseClient {
  constructor(config) {
    this.url = config.esp32_url.replace(/\/$/, '');
    this.key = config.key;
    this.timeout = config.request_timeout_ms ?? 95000;
    if (!/^http:\/\/[\w.-]+:4397$/.test(this.url) || !/^[a-f0-9]{64}$/.test(this.key)) {
      throw new Error('Invalid ESP32 URL or bridge key');
    }
  }
  async http(path, method = 'GET', data, signal) {
    const timeout = AbortSignal.timeout(4000);
    const response = await fetch(this.url + path, {
      method, signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      headers: { Authorization: `Bearer ${this.key}`, 'Content-Type': 'application/json' },
      body: data ? JSON.stringify(data) : undefined,
    });
    if (!response.ok) throw new Error(`ESP32 HTTP ${response.status}`);
    return response.json();
  }
  health() { return this.http('/health'); }
  async cancel(id) {
    try { await this.http(`/requests/${id}/cancel`, 'POST'); } catch { /* best effort; device deadline also cancels */ }
  }
  async ask(id, text, signal) {
    const deadline = Date.now() + this.timeout;
    if (Buffer.byteLength(text, 'utf8') > 2048) throw new Error('Question exceeds 2048 UTF-8 bytes');
    try {
      let job;
      try { job = await this.http('/requests', 'POST', { request_id: id, text }, signal); }
      catch (error) {
        // A POST response can be lost after delivery. Poll the same ID once;
        // never create a second cloud turn for an uncertain submission.
        if (signal?.aborted) throw error;
        job = await this.http(`/requests/${id}`, 'GET', undefined, signal);
      }
      while (Date.now() < deadline) {
        if (job.status === 'completed' && job.reply) return job.reply;
        if (['cancelled', 'failed'].includes(job.status)) throw new Error(job.error || job.status);
        if (!['queued', 'running'].includes(job.status)) throw new Error('Invalid bridge response');
        await delay(750, undefined, { signal });
        job = await this.http(`/requests/${id}`, 'GET', undefined, signal);
      }
      throw new Error('Muse request timed out');
    } finally { await this.cancel(id); }
  }
}
