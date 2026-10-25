import test from 'node:test';
import assert from 'node:assert/strict';
import { MuseClient } from './muse-client.mjs';

const config = { esp32_url: 'http://192.168.100.2:4397', key: 'a'.repeat(64), request_timeout_ms: 10000 };
test('lost POST response polls the same request ID without resubmitting', async () => {
  const old = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options.method]);
    assert.equal(options.headers.Authorization, 'Bearer ' + config.key);
    if (url.endsWith('/requests')) throw new Error('response lost');
    return Response.json({ status: 'completed', reply: 'ok' });
  };
  try { assert.equal(await new MuseClient(config).ask('unique-id', 'hello'), 'ok'); }
  finally { globalThis.fetch = old; }
  assert.deepEqual(calls.map(x => x[1]), ['POST', 'GET', 'POST']);
  assert.ok(calls[1][0].endsWith('/unique-id')); assert.ok(calls[2][0].endsWith('/unique-id/cancel'));
});
test('oversize text is rejected before any HTTP call', async () => {
  await assert.rejects(new MuseClient(config).ask('id', '中'.repeat(700)), /2048/);
});
test('failed jobs cancel their ID and report failure', async () => {
  const old = globalThis.fetch; const calls = [];
  globalThis.fetch = async (url, options) => { calls.push(options.method); return Response.json({ status: 'failed', error: 'local_interruption' }); };
  try { await assert.rejects(new MuseClient(config).ask('id', 'hello'), /local_interruption/); }
  finally { globalThis.fetch = old; }
  assert.deepEqual(calls, ['POST', 'POST']);
});
