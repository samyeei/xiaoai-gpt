import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {WebSocket} from 'ws';
import {SpeakerHub} from './speaker-hub.mjs';
import {ConversationLease} from './conversation-lease.mjs';
import {validateSpeakers} from './speakers.mjs';

const devices=[{id:'lx06-primary',ip:'127.0.0.1'},{id:'lx06-secondary',ip:'127.0.0.2'}];
test('registry validates fixed identities and single rollback',()=>{
 assert.equal(validateSpeakers({version:1,mode:'single',devices}).devices.length,1);
 assert.equal(validateSpeakers({version:1,mode:'multiple',devices}).devices.length,2);
 for(const c of [{version:1,mode:'multiple',devices:[devices[0],devices[0]]},{version:1,mode:'multiple',devices:[{id:'bad',ip:'host;bad'}]}])assert.throws(()=>validateSpeakers(c));
});
test('lease permits one conversation and ignores stale releases',()=>{
 const l=new ConversationLease(),a=l.acquire('a');assert.ok(a);assert.equal(l.acquire('b'),null);
 assert.equal(l.release('b',a),false);assert.equal(l.release('a',a),true);
 const b=l.acquire('a');assert.notEqual(a,b);assert.equal(l.release('a',a),false);assert.equal(l.owner,'a');assert.equal(l.release('a',b),true);
});
test('hub isolates two PCM/RPC channels and rejects duplicate and unknown sources',async()=>{
 // macOS exposes only 127.0.0.1 without privileged loopback aliases.
 const hub=new SpeakerHub({devices,port:0,host:'127.0.0.1',peerAddress:req=>req.url.slice(1)});await once(hub.server,'listening');
 const url=`ws://127.0.0.1:${hub.server.address().port}`;
 const a=new WebSocket(url+'/127.0.0.1'),b=new WebSocket(url+'/127.0.0.2');
 try{
  await Promise.all([once(a,'open'),once(b,'open')]);
  const primary=hub.devices.get('lx06-primary'),secondary=hub.devices.get('lx06-secondary');
  const gotA=[],gotB=[];primary.on('audio',p=>gotA.push([...p]));secondary.on('audio',p=>gotB.push([...p]));
  for(const [s,value] of [[a,1],[b,2]])s.send(Buffer.from(JSON.stringify({tag:'record',bytes:[value]})));
  await new Promise(r=>setTimeout(r,30));assert.deepEqual(gotA,[[1]]);assert.deepEqual(gotB,[[2]]);
  b.on('message',raw=>{const p=JSON.parse(raw);if(p.Request)b.send(JSON.stringify({Response:{id:p.Request.id,data:'second'}}));});
  assert.equal(await secondary.run_shell('true',1000),'second');
  for(const ip of ['127.0.0.1','127.0.0.3']){const extra=new WebSocket(url+'/'+ip);await once(extra,'close');assert.equal(primary.socket.readyState,WebSocket.OPEN);}
  a.close();await once(a,'close');assert.equal(secondary.socket.readyState,WebSocket.OPEN);
 }finally{a.terminate();b.terminate();await hub.close();}
});
