import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { WebSocket } from 'ws';
import { SpeakerTransport, nativeWake } from './speaker-transport.mjs';
import { Controller } from './controller.mjs';
import { DirectVoice } from './direct-voice.mjs';
test('single rollback refuses a secondary reconnect instead of taking the primary slot',async()=>{
 const server=new SpeakerTransport({port:0,host:'127.0.0.1',allowedIP:'127.0.0.2'});await once(server.server,'listening');
 const client=new WebSocket(`ws://127.0.0.1:${server.server.address().port}`);
 try{await once(client,'open');await new Promise(r=>setTimeout(r,20));assert.equal(server.socket,null);}finally{client.terminate();await server.close();}
});

test('client protocol carries shell RPC, recording configuration, and binary PCM; disconnect rejects pending RPC', async () => {
  const server = new SpeakerTransport({port:0,host:'127.0.0.1'});
  await once(server.server, 'listening');
  const client = new WebSocket(`ws://127.0.0.1:${server.server.address().port}`);
  await once(client,'open');
  const messages = [];
  client.on('message', bytes => {
    const p = JSON.parse(bytes).Request; messages.push(p);
    if (p.command === 'run_shell') client.send(JSON.stringify({Response:{id:p.id,data:{exit_code:0,stdout:'ok',stderr:''}}}));
    if (p.command === 'start_recording') client.send(JSON.stringify({Response:{id:p.id,data:null}}));
  });
  try {
    assert.equal((await server.run_shell('true',1000)).stdout,'ok');
    await server.startRecording();
    assert.equal(messages[1].payload.bits_per_sample,32);
    const audio = once(server,'audio');
    client.send(Buffer.from(JSON.stringify({id:'x',tag:'record',bytes:[0,0,1,0]})));
    assert.deepEqual((await audio)[0],Buffer.from([0,0,1,0]));
    const pending = server.request('unused',null,1000);
    const rejected = assert.rejects(pending,/disconnected/);
    client.close(); await rejected;
  } finally { client.terminate(); await server.close(); }
});

test('direct question does not restart native XiaoAI; native command cancels a stale direct answer', async () => {
  let finish, began;
  const started = new Promise(r => { began=r; });
  const calls = [];
  const c = new Controller({ask:()=>new Promise(r=>{finish=r;began();})},
    {interrupt:async()=>assert.fail('Native restart'),say:async t=>calls.push(t)});
  const task = c.onDirectText('你好'); await started;
  await c.onText('播放音乐'); finish('obsolete'); await task;
  assert.deepEqual(calls,[]);
});

test('native wake cancellation preserves native Muse mode outside a direct session', () => {
  const voice = Object.create(DirectVoice.prototype);
  voice.controller = {mode:true,cancel:()=>assert.fail('No direct session to cancel')};
  voice.cancel=()=>{}; voice.session=null;
  voice.nativePriority(); assert.equal(voice.controller.mode,true);
  voice.session='direct'; voice.controller.cancel=()=>{};
  voice.nativePriority(); assert.equal(voice.controller.mode,false);
});

test('S32 conversion handles split samples without introducing clipping', () => {
  const frames=[];
  const voice=Object.create(DirectVoice.prototype);
  voice.worker={readyState:WebSocket.OPEN, bufferedAmount:0,send:b=>frames.push(b)};
  voice.remainder=Buffer.alloc(0);
  const samples=Buffer.alloc(12);
  samples.writeInt32LE(-2147483648,0); samples.writeInt32LE(2147418112,4); samples.writeInt32LE(65536,8);
  voice.audio(samples.subarray(0,5)); voice.audio(samples.subarray(5));
  const output=Buffer.concat(frames);
  assert.deepEqual([0,2,4].map(i=>output.readInt16LE(i)),[-32768,32767,1]);
});

test('only the native recognition-begin event counts as native wake',()=>{
  const event={event:'instruction',data:{NewLine:JSON.stringify({header:{namespace:'SpeechRecognizer',name:'RecognizeResult'},payload:{is_vad_begin:false,results:[]}})}};
  assert.equal(nativeWake(event),true);
  assert.equal(nativeWake({event:'playing',data:'Idle'}),false);
});
