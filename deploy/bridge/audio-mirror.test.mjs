import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';

const module = await import('./audio-mirror.mjs').catch(() => ({}));

function socketFactory() {
  const sockets = [];
  const connect = (url, options) => {
    const socket = new EventEmitter();
    Object.assign(socket, { readyState: 0, bufferedAmount: 0, sent: [], terminate() { this.readyState = 3; this.emit('close'); }, send(data, options, callback) { this.sent.push(data); callback?.(); } });
    sockets.push({socket, url, options}); return socket;
  };
  return { sockets, connect };
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

test('private opt-in requires a strict future epoch expiry within five minutes', () => {
  assert.equal(typeof module.nativeAudioOptIn, 'function');
  const now = 1000000;
  for (const value of [null, {}, {expires_at:'1001000'}, {expires_at:now}, {expires_at:now+300001}, {expires_at:now+1.5}, {expires_at:now+1000, enabled:true}]) assert.deepEqual(module.nativeAudioOptIn(value, now), {});
  assert.deepEqual(module.nativeAudioOptIn({expires_at:now+300000}, now), {native_audio_url:'ws://127.0.0.1:4415', native_audio_expires_at:now+300000});
});

test('default mirror is disabled and cannot connect to non-loopback URLs', () => {
  assert.equal(typeof module.AudioMirror, 'function');
  const factory = socketFactory();
  for (const config of [{}, {native_audio_url:'ws://example.com',native_audio_expires_at:Date.now()+1000}]) {
    const mirror = new module.AudioMirror(config, {connect:factory.connect});
    assert.deepEqual(mirror.status(), {connected:false,frames_sent:0,backpressure:0}); mirror.close();
  }
  assert.equal(factory.sockets.length, 0);
});

test('mirror sends unchanged S32 frames with a 64k inbound limit and no capture ownership', () => {
  assert.equal(typeof module.AudioMirror, 'function');
  const factory = socketFactory(), mirror = new module.AudioMirror({native_audio_url:'ws://127.0.0.1:4415',native_audio_expires_at:Date.now()+1000}, {connect:factory.connect});
  const {socket, options} = factory.sockets[0];
  assert.equal(options.maxPayload, 65536);
  socket.readyState = 1; socket.emit('open');
  const data = Buffer.from([0,0,255,127]); mirror.audio(data);
  assert.strictEqual(socket.sent[0], data);
  assert.deepEqual(mirror.status(), {connected:true,frames_sent:1,backpressure:0});
  mirror.close(); assert.equal(socket.readyState, 3);
});

test('backpressure drops the frame and closes before queuing more audio', () => {
  assert.equal(typeof module.AudioMirror, 'function');
  const factory = socketFactory(), mirror = new module.AudioMirror({native_audio_url:'ws://127.0.0.1:4415',native_audio_expires_at:Date.now()+1000}, {connect:factory.connect});
  const {socket} = factory.sockets[0]; socket.readyState=1;socket.emit('open');socket.bufferedAmount=128001;
  mirror.audio(Buffer.alloc(4));
  assert.equal(socket.sent.length,0); assert.deepEqual(mirror.status(),{connected:false,frames_sent:0,backpressure:1});mirror.close();
});

test('expiry terminates the mirror without a manager restart', async () => {
  assert.equal(typeof module.AudioMirror, 'function');
  const factory=socketFactory(),mirror=new module.AudioMirror({native_audio_url:'ws://127.0.0.1:4415',native_audio_expires_at:Date.now()+25},{connect:factory.connect});
  const {socket}=factory.sockets[0];socket.readyState=1;socket.emit('open');
  await delay(40);mirror.audio(Buffer.alloc(4));
  assert.equal(socket.readyState,3);assert.equal(socket.sent.length,0);assert.equal(mirror.status().connected,false);mirror.close();
});

test('connection retries are bounded and shutdown cancels the pending retry', async () => {
  assert.equal(typeof module.AudioMirror, 'function');
  const factory=socketFactory(),mirror=new module.AudioMirror({native_audio_url:'ws://127.0.0.1:4415',native_audio_expires_at:Date.now()+1000},{connect:factory.connect,retryDelays:[1,1,1]});
  for(let i=0;i<4;i++){factory.sockets[i].socket.terminate();await delay(5);}
  assert.equal(factory.sockets.length,4);mirror.close();await delay(5);assert.equal(factory.sockets.length,4);
  const other=new module.AudioMirror({native_audio_url:'ws://127.0.0.1:4415',native_audio_expires_at:Date.now()+1000},{connect:factory.connect,retryDelays:[20]});
  factory.sockets.at(-1).socket.terminate();const count=factory.sockets.length;other.close();await delay(30);assert.equal(factory.sockets.length,count);
});

test('manager discards inherited mirror settings before loading the private opt-in', () => {
  const source=readFileSync(new URL('../../mac/unified-service/index.mjs',import.meta.url),'utf8');
  assert.match(source,/delete bridge\.native_audio_url/);
  assert.match(source,/delete bridge\.native_audio_expires_at/);
  assert.match(source,/native-audio\.json/);
  assert.match(source,/nativeAudioOptIn/);
});

test('an actual websocket receives the original binary frame and ends on close', async () => {
  const {WebSocket, WebSocketServer}=await import('ws');
  const server=new WebSocketServer({host:'127.0.0.1',port:0});
  await new Promise(resolve=>server.once('listening',resolve));
  let receiver;
  const accepted=new Promise(resolve=>server.once('connection',socket=>{receiver=socket;resolve(socket);}));
  const mirror=new module.AudioMirror({native_audio_url:'ws://127.0.0.1:4415',native_audio_expires_at:Date.now()+1000}, {connect:(_url,options)=>new WebSocket(`ws://127.0.0.1:${server.address().port}`,options)});
  try {
    await accepted;
    await new Promise(resolve=>mirror.socket.once('open',resolve));
    const received=new Promise(resolve=>receiver.once('message',(data,binary)=>resolve({data,binary})));
    const frame=Buffer.from([0,0,1,0,0,0,255,127]);mirror.audio(frame);
    const result=await received;assert.equal(result.binary,true);assert.deepEqual(result.data,frame);
    const ended=new Promise(resolve=>receiver.once('close',resolve));mirror.close();await ended;
    assert.equal(mirror.status().connected,false);assert.equal(mirror.status().frames_sent,1);
  } finally { mirror.close();receiver?.terminate();await new Promise(resolve=>server.close(resolve)); }
});
