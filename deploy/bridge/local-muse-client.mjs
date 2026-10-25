import { createHmac } from 'node:crypto';
import { CodexClient } from './codex-client.mjs';
const unavailable = status => Object.assign(new Error('Muse request unavailable'),Number.isInteger(status)?{status}:{});
// Reuse the existing polling, fixed-ID recovery and cancellation implementation.
export class LocalMuseClient extends CodexClient {
  constructor(config) {
    try {
      const endpoint = new URL(config.url);
      if (!['127.0.0.1', 'localhost'].includes(endpoint.hostname)) throw unavailable();
      super(config);
    } catch { throw new Error('Invalid Muse configuration'); }
  }
  digest(text){return createHmac('sha256',Buffer.from(this.key,'hex')).update(text,'utf8').digest('hex');}
  async http(...args) { try { return await super.http(...args); } catch(error) { throw unavailable(error?.status); } }
  async ask(...args) { try { return await super.ask(...args); } catch(error) { throw unavailable(error?.status); } }
}
