import test from 'node:test';import assert from 'node:assert/strict';import {RealtimeClient,realtimeOptIn} from './realtime-client.mjs';
import {EventEmitter} from 'node:events';
test('another device realtime session cannot attach audio, stop, or count as a successful start',async()=>{
 const requests=[];let sockets=0;
 const c=new RealtimeClient({key:'k',device_id:'lx06-secondary'},{auto:false,socketFactory:()=>{sockets++;throw Error('foreign audio');},request:async(path)=>{requests.push(path);return {active:true,state:'ready',session_id:'foreign',device_id:'lx06-primary'};}});
 c.apply({active:true,state:'ready',session_id:'foreign',device_id:'lx06-primary'});
 assert.equal(sockets,0);assert.equal(c.state.active,false);assert.equal(await c.start(),false);
 await c.stop();c.close();assert.equal(requests.includes('/stop'),false);
});
test('late close from a replaced audio socket cannot stop the next session',async()=>{
 const sockets=[],requests=[];
 const c=new RealtimeClient({key:'k'},{auto:false,socketFactory:()=>{const socket=new EventEmitter();socket.close=()=>{};sockets.push(socket);return socket;},request:async(path,body)=>{requests.push([path,body]);return {active:false,state:'idle',session_id:null};}});
 try{
  c.apply({active:true,state:'ready',session_id:'old'});assert.equal(sockets.length,1);const old=sockets[0];
  c.apply({active:false,state:'idle',session_id:null});c.apply({active:true,state:'ready',session_id:'new'});
  old.emit('close');await new Promise(r=>setImmediate(r));assert.equal(requests.length,0);assert.equal(c.state.session_id,'new');assert.equal(c.socket,sockets[1]);
  sockets[1].emit('close');await new Promise(r=>setImmediate(r));assert.deepEqual(requests,[['/stop',{session_id:'new'}]]);
 }finally{c.state={active:false,state:'idle'};c.close();}
});
test('late stop response and its cleanup cannot release or close a newer session',async()=>{
 let finishStop,newClosed=0;
 const c=new RealtimeClient({key:'k'},{auto:false,request:async(path)=>path==='/stop'?new Promise(r=>finishStop=r):{active:true,state:'starting_realtime',session_id:'new'}});
 c.state={active:true,state:'listening_realtime',session_id:'old'};c.socket={close(){}};
 const oldStop=c.stop();c.apply({active:false,state:'idle',session_id:null});await c.start();
 c.socket={close(){newClosed++;}};finishStop({active:false,state:'idle',session_id:null});await oldStop;
 assert.equal(c.state.session_id,'new');assert.equal(newClosed,0);c.state={active:false,state:'idle'};c.close();
});
test('strict opt-in fixes addresses and cannot override authentication',()=>{assert.equal(realtimeOptIn({enabled:false},'key'),null);assert.equal(realtimeOptIn({enabled:true,url:'https://external'},'key'),null);assert.equal(realtimeOptIn({enabled:true},'key').key,'key');});
test('stale status cannot release a newer session and stop includes owner',async()=>{const requests=[];const c=new RealtimeClient({key:'k'},{auto:false,request:async(path,p)=>{requests.push([path,p]);return {active:false,state:'idle',session_id:null};}});c.state={active:true,state:'listening_realtime',session_id:'new'};c.apply({active:true,state:'playing_realtime',session_id:'old'});assert.equal(c.state.session_id,'new');await c.stop();assert.equal(requests[0][1].session_id,'new');c.close();});
test('an idle poll issued before start cannot release the new reservation',async()=>{let finish;const c=new RealtimeClient({key:'k'},{auto:false,request:async(path)=>path==='/status'?new Promise(r=>finish=r):{active:true,state:'starting_realtime',session_id:'new'}});const poll=c.poll();await c.start();finish({active:false,state:'idle',session_id:null});await poll;assert.equal(c.state.active,true);c.state={active:false,state:'idle'};c.close();});
test('lost start response cleans a session confirmed by status rather than orphaning media',async()=>{const paths=[];const c=new RealtimeClient({key:'k'},{auto:false,request:async(path)=>{paths.push(path);if(path==='/start')throw Error('deadline');if(path==='/status')return {active:true,state:'starting_realtime',session_id:'owned'};return {active:false,state:'idle',session_id:null};}});assert.equal(await c.start(),false);assert.deepEqual(paths,['/start','/status','/stop']);assert.equal(c.blocked(),false);c.close();});
test('LX06 realtime input uses proven eightfold gain with saturation',async()=>{
 const c=new RealtimeClient({key:'k'},{auto:false});const sent=[];
 c.state={active:true,state:'listening_realtime',session_id:'s'};c.socket={readyState:1,bufferedAmount:0,send:data=>sent.push(data)};
 const input=Buffer.alloc(6);[100,10000,-10000].forEach((x,i)=>input.writeInt16LE(x,i*2));c.audio(input);
 assert.deepEqual([0,2,4].map(i=>sent[0].readInt16LE(i)),[800,32767,-32768]);assert.equal(input.readInt16LE(0),100);
});
