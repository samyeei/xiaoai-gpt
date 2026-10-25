import test from 'node:test';
import assert from 'node:assert/strict';
import { DirectVoice } from './direct-voice.mjs';
const make=()=>{
 const packets=[],calls=[];
 const voice=Object.assign(Object.create(DirectVoice.prototype),{wakeRoutes:new Map([['HEY_CODEX','codex'],['HEY_GPT','codex'],['HEY_LUKA','codex'],['HEY_MUSE','muse']]),state:'idle',session:null,generation:0,playing:false,controller:{onDirectText:async(...args)=>calls.push(args)},speaker:{say:async()=>{}},send:p=>packets.push(p),playback:async(_,action)=>action()});
 return {voice,packets,calls};
};
test('three activation aliases capture Codex backend and Muse retains its backend',async()=>{
 for(const [keyword,backend] of [['HEY_CODEX','codex'],['HEY_GPT','codex'],['HEY_LUKA','codex'],['HEY_MUSE','muse']]){
  const {voice,calls}=make();await voice.wake(keyword);assert.equal(voice.state,'listening');
  // Stop after dispatch to avoid waiting for real hardware playback.
  voice.controller.onDirectText=async(...args)=>{calls.push(args);voice.generation++;};
  await voice.answer('question');assert.deepEqual(calls,[['question',backend]]);
 }
});
test('unknown and missing wake labels are ignored, including object property names',async()=>{
 for(const label of [undefined,'unknown','__proto__','constructor']){const {voice,packets}=make();await voice.wake(label);assert.equal(voice.state,'idle');assert.equal(packets.length,0);}
});
test('cancel and close abort a direct task and suppress its late reply, preserving native mode without session',async()=>{
 const {Controller}=await import('./controller.mjs');
 for(const action of ['cancel','close']){
  let finish;const spoken=[];const controller=new Controller({ask:async()=>''},{say:async t=>spoken.push(t)},{}, {ask:()=>new Promise(r=>finish=r)});
  const {voice}=make();voice.controller=controller;voice.session='direct';voice.worker=null;
  const task=controller.onDirectText('task','codex');voice[action]();finish('late');await task;assert.deepEqual(spoken,[]);
 }
 const {voice}=make();let cancelled=false;voice.controller={mode:true,cancel:()=>cancelled=true};voice.cancel();assert.equal(cancelled,false);assert.equal(voice.controller.mode,true);
});
test('transport disconnection aborts active direct request; constructor playback hook captures generation',async()=>{
 const {EventEmitter}=await import('node:events');const {Controller}=await import('./controller.mjs');
 let finish;const spoken=[];const speaker={say:async t=>spoken.push(t)};
 const controller=new Controller({},speaker,{}, {ask:()=>new Promise(r=>finish=r)});
 class OfflineVoice extends DirectVoice {connect(){}}
 const voice=new OfflineVoice(new EventEmitter(),controller,speaker,{});voice.session='direct';
 const task=controller.onDirectText('task','codex');voice.transport.emit('disconnected');finish('late');await task;
 assert.deepEqual(spoken,[]);assert.equal(controller.current,null);
 voice.generation=17;let captured;voice.playback=async(generation,action)=>{captured=generation;await action();};
 await controller.progressPlayback(async()=>{});assert.equal(captured,17);voice.close();
});
test('native Codex wake prompts before start and never legacy listens; duplicate wake blocked',async()=>{
 const {voice,packets}=make();const order=[];let release;voice.speaker.say=async t=>{order.push(t);await new Promise(r=>release=r);};voice.nativeVoice={blocked:()=>false,start:async()=>{order.push('start');return true;}};
 const first=voice.wake('HEY_CODEX');await voice.wake('HEY_GPT');assert.equal(order.length,1);release();await first;assert.deepEqual(order,['我在，正在接通音频。','start']);assert.equal(packets.some(p=>p.type==='listen'),false);
});
test('native active suppresses legacy answer, nativePriority and other wakes',async()=>{const {voice,packets,calls}=make();voice.nativeVoice={blocked:()=>true};voice.nativePriority();await voice.wake('HEY_MUSE');await voice.answer('text');assert.equal(packets.length,0);assert.equal(calls.length,0);});
test('readiness cue completes before mirror enable and has a playback tail',async()=>{const {voice}=make();const order=[];voice.nativeRequested=true;voice.nativeVoice={enableMirror:s=>order.push(['mirror',s.expires_at])};voice.speaker.say=async t=>order.push(t);const begin=Date.now();await voice.nativeReady({expires_at:123});assert.deepEqual(order,['音频已接通，请按原生语音快捷键。',['mirror',123]]);assert.ok(Date.now()-begin>=390);});
test('worker reconnect starts paused during native lease',async()=>{const {EventEmitter}=await import('node:events');const {WebSocketServer}=await import('ws');const server=new WebSocketServer({host:'127.0.0.1',port:0});await new Promise(r=>server.once('listening',r));let packet;const got=new Promise(r=>server.once('connection',socket=>socket.once('message',raw=>{packet=JSON.parse(raw);r();})));class OfflineVoice extends DirectVoice {connect(){}}const voice=new OfflineVoice(new EventEmitter(),{}, {say:async()=>{}},{});voice.url=`ws://127.0.0.1:${server.address().port}`;voice.nativeVoice={blocked:()=>true,close(){}};DirectVoice.prototype.connect.call(voice);await got;assert.equal(packet.type,'pause');voice.close();await new Promise(r=>server.close(r));});
test('native reservation protects only pre-start prompt and clears on inactive or bounded uncertainty',()=>{for(const state of ['idle','failed','unknown']){const {voice,packets}=make();voice.nativeRequested=true;voice.nativePhase='waiting';voice.state='native';voice.nativeVoice={blocked:()=>false};voice.nativeState({state,active:state==='unknown',blocked:false,available:state!=='unknown'});assert.equal(voice.nativeRequested,false);assert.equal(voice.nativeBlocked(),false);assert.equal(packets.at(-1).type,'arm');}const {voice}=make();voice.nativeRequested=true;voice.nativePhase='prompting';voice.nativeVoice={blocked:()=>false};voice.nativeState({state:'idle',active:false,blocked:false,available:true});assert.equal(voice.nativeRequested,true);});
test('failed POST deadline releases direct reservation without failure cue during possible lease',async()=>{const {NativeVoiceClient}=await import('./native-voice-client.mjs');const {voice,packets}=make();const spoken=[];voice.speaker.say=async t=>spoken.push(t);voice.nativeVoice=new NativeVoiceClient({key:'k'},{auto:false,request:async()=>({state:'idle',active:false,expires_at:null,last_error:null})});await voice.nativeVoice.poll();voice.nativeVoice.onState=s=>voice.nativeState(s);voice.nativeVoice.request=async()=>{throw Error('unavailable');};await voice.wake('HEY_CODEX');assert.equal(voice.nativeRequested,true);assert.equal(voice.nativeBlocked(),true);voice.nativeVoice.boundUntil=Date.now()-1;await voice.nativeVoice.poll();assert.equal(voice.nativeRequested,false);assert.equal(voice.nativeBlocked(),false);assert.equal(packets.at(-1).type,'arm');assert.deepEqual(spoken,['我在，正在接通音频。']);voice.nativeVoice.close();});
test('captured entry phrases remain single questions; native entry owns continuous mode',async()=>{const {voice,calls}=make();let starts=0;voice.backend='codex';voice.realtime={blocked:()=>false,start:async()=>{starts++;return true;}};voice.controller.onDirectText=async(...args)=>{calls.push(args);voice.generation++;};await voice.answer('进入对话模式');assert.equal(starts,0);assert.deepEqual(calls,[['进入对话模式','codex']]);
 const other=make();other.voice.backend='muse';other.voice.realtime={blocked:()=>false,start:async()=>{throw Error('must not start');}};other.voice.controller.onDirectText=async(...a)=>{other.calls.push(a);other.voice.generation++;};await other.voice.answer('进入对话模式');assert.deepEqual(other.calls,[['进入对话模式','muse']]);});
test('calibration acquires only idle capture and rejects a busy voice lease',()=>{const {voice,packets}=make();assert.equal(voice.calibrate(),true);assert.equal(voice.state,'calibrating');assert.equal(packets.at(-1).type,'calibrate');assert.equal(typeof packets.at(-1).session,'string');assert.equal(voice.calibrate(),false);});

test('a completed calibration metric from another run cannot release the new calibration',()=>{const {voice}=make();voice.state='calibrating';voice.calibrationSession='new';voice.calibrationState({worker_state:'idle',calibration:{calibration_id:'old',calibration_complete:true}});assert.equal(voice.state,'calibrating');voice.calibrationState({worker_state:'idle',calibration:{calibration_id:'new',calibration_complete:true}});assert.equal(voice.state,'idle');});
