import test from 'node:test';
import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import { EventEmitter, once } from 'node:events';
import { Rpc } from './rpc.mjs';
test('JSONL responses, notifications and server requests are separated, and process exit rejects requests', async () => {
  const child=new EventEmitter(); child.stdin=new PassThrough(); child.stdout=new PassThrough(); child.stderr=new PassThrough(); child.kill=()=>{};
  const rpc=new Rpc({child}); const packets=[]; child.stdin.on('data',x=>packets.push(JSON.parse(x)));
  const init=rpc.ready(); await new Promise(r=>setImmediate(r));
  child.stdout.write(JSON.stringify({id:packets[0].id,result:{}})+'\n'); await init;
  assert.equal(packets[1].method,'initialized');
  const note=once(rpc,'notification'); child.stdout.write('{"method":"turn/started","params":{}}\n'); assert.equal((await note)[0].method,'turn/started');
  const req=once(rpc,'serverRequest'); child.stdout.write('{"id":90,"method":"item/tool/requestUserInput","params":{}}\n'); assert.equal((await req)[0].id,90);
  const pending=rpc.request('thread/start',{}); const rejection=assert.rejects(pending,/disconnected/); child.emit('exit',1); await rejection; rpc.close();
});
