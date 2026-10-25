import test from 'node:test';
import assert from 'node:assert/strict';
import {DirectVoice} from './direct-voice.mjs';
import {ConversationLease} from './conversation-lease.mjs';

const fixture=()=>{
 const order=[],calls=[];
 const voice=Object.assign(Object.create(DirectVoice.prototype),{
  state:'idle',worker:{readyState:1},generation:0,backend:'codex',session:null,playing:false,
  controller:{onDirectText:async(...args)=>{calls.push(args);voice.generation++;}},
  realtime:{blocked:()=>false,start:async()=>{order.push('start');return true;}},
  speaker:{interrupt:async()=>order.push('interrupt'),say:async()=>order.push('say')},
  send:p=>order.push(p.type),playback:async(_,fn)=>fn()
 });return {voice,order,calls};
};

test('hey Luka captured commands remain one-shot questions',async()=>{
 const {voice,order,calls}=fixture();await voice.answer('开启连续对话');
 assert.deepEqual(calls,[['开启连续对话','codex']]);assert.equal(order.includes('start'),false);
});

test('native XiaoAI entry interrupts builtin reply and reserves audio before start',async()=>{
 const {voice,order}=fixture();let release;
 voice.speaker.interrupt=async()=>{order.push('interrupt');await new Promise(r=>release=r);};
 const pending=voice.onNativeText('开启连续对话。');assert.equal(voice.nativeBlocked(),true);
 assert.equal(await voice.onNativeText('开启连续对话'),false);
 voice.realtimeState({active:false,state:'idle'});assert.equal(voice.state,'realtime');
 release();assert.equal(await pending,true);assert.ok(order.indexOf('interrupt')<order.indexOf('start'));
 assert.equal(voice.realtimeRequested,false);
});

test('ordinary native requests and a missing realtime backend do not start a call',async()=>{
 const {voice,order}=fixture();assert.equal(await voice.onNativeText('解释开启连续对话是什么意思'),false);assert.equal(order.length,0);
 voice.realtime=null;assert.equal(await voice.onNativeText('开启连续对话'),false);
});

test('late readiness playback failure from an old session cannot stop a newer session',async()=>{
 const {voice}=fixture();let reject,stops=0;
 voice.realtime.state={active:true,session_id:'old'};voice.realtime.stop=async()=>stops++;
 voice.playback=()=>new Promise((_,r)=>reject=r);
 const pending=voice.realtimeReady({session_id:'old'});
 voice.realtime.state={active:true,session_id:'new'};reject(Error('old playback failed'));await pending;
 assert.equal(stops,0);
});

test('one native command retries a stalled accepted media connection only once',async()=>{
 const {voice,order}=fixture();voice.state='realtime';voice.realtimeRetryLeft=1;voice.realtime.state={active:false};
 const failed={active:false,state:'idle',last_error:'media_connect_timeout',last_stop_reason:'error:media_connect_timeout',setup_diagnostics:{thread_ready:true,offer_sent:true,answer_received:true,server_started:true,media_connected:false}};
 voice.realtimeState(failed);voice.realtimeState(failed);await new Promise(r=>setImmediate(r));
 assert.equal(order.filter(x=>x==='start').length,1);assert.equal(voice.realtimeRetryLeft,0);
 voice.realtimeState(failed);await new Promise(r=>setImmediate(r));assert.equal(order.filter(x=>x==='start').length,1);
});

test('authentication failure and user stop never trigger automatic retry',async()=>{
 for(const failure of [{last_error:'player_unavailable',last_stop_reason:'error:player_unavailable'},{last_error:null,last_stop_reason:'user_exit'}]){
  const {voice,order}=fixture();voice.state='realtime';voice.realtimeRetryLeft=1;voice.realtime.state={active:false};voice.realtimeState({active:false,state:'idle',...failure});await new Promise(r=>setImmediate(r));assert.equal(order.includes('start'),false);
 }
});

test('cancelling during retry announcement prevents a late new call',async()=>{
 const {voice,order}=fixture();let release;voice.realtimeRequested=true;voice.realtime.state={active:false};
 voice.playback=()=>new Promise(r=>release=r);
 const pending=voice.retryRealtime(voice.generation);voice.cancel();release();await pending;assert.equal(order.includes('start'),false);
});
test('native XiaoAI wake stops an active realtime call without waiting for cloud audio',async()=>{const {voice,order}=fixture();voice.realtime.state={active:true,session_id:'current'};voice.realtime.stop=async()=>{order.push('stop');voice.realtime.state={active:false};};voice.realtime.blocked=()=>!!voice.realtime.state.active;assert.equal(await voice.nativeInterrupt(),true);assert.equal(order.includes('stop'),true);assert.equal(voice.state,'idle');assert.equal(await voice.nativeInterrupt(),false);});
test('native exit command is accepted while realtime normally blocks native routing',async()=>{const {voice}=fixture();let stops=0;voice.realtime.state={active:true};voice.realtime.blocked=()=>true;voice.realtime.stop=async()=>{stops++;voice.realtime.state={active:false};};assert.equal(await voice.onNativeText('退下吧'),true);assert.equal(stops,1);});
test('repeated native interrupts share cleanup and cannot reset a newer generation',async()=>{const {voice}=fixture();let release,stops=0;voice.realtime.state={active:true};voice.realtime.stop=()=>{stops++;return new Promise(r=>release=r);};const a=voice.nativeInterrupt(),b=voice.nativeInterrupt();voice.generation++;voice.state='realtime';release();await Promise.all([a,b]);assert.equal(stops,1);assert.equal(voice.state,'realtime');});
test('native GPT command interrupts builtin speech then captures exactly one Codex question',async()=>{const {voice,order}=fixture();voice.nativeVoice={blocked:()=>false,start:async()=>{throw Error('legacy voice must not start');}};const packets=[];voice.send=p=>packets.push(p);assert.equal(await voice.onNativeText('打开机劈替'),true);assert.equal(voice.state,'listening');assert.equal(voice.backend,'codex');assert.equal(packets.filter(p=>p.type==='listen').length,1);assert.equal(order.includes('start'),false);assert.equal(order[0],'interrupt');assert.equal(voice.singleRequested,false);});
test('native single-question reservation prevents duplicate entry and stale capture',async()=>{const {voice,order}=fixture();let release;voice.speaker.interrupt=()=>new Promise(r=>release=r);const pending=voice.onNativeText('打开GPT');assert.equal(voice.nativeBlocked(),true);assert.equal(await voice.onNativeText('打开机劈替'),true);voice.cancel();release();await pending;assert.equal(voice.state,'idle');assert.equal(voice.singleRequested,false);assert.equal(order.includes('say'),false);});

test('two speakers cannot enter together; cancelling releases only after own cleanup',async()=>{
 const a=fixture(),b=fixture(),lease=new ConversationLease();
 Object.assign(a.voice,{deviceId:'a',lease});Object.assign(b.voice,{deviceId:'b',lease});
 let release;a.voice.speaker.interrupt=()=>new Promise(r=>release=r);
 const first=a.voice.onNativeText('打开机劈替');assert.equal(lease.owner,'a');
 await b.voice.onNativeText('开启连续对话');assert.equal(b.order.includes('start'),false);assert.equal(b.order.includes('interrupt'),false);
 a.voice.cancel();release();await first;assert.equal(lease.owner,null);
 await b.voice.onNativeText('开启连续对话');assert.equal(b.order.includes('start'),true);
 b.voice.cancel();assert.equal(lease.owner,null);
});
test('lease remains held until realtime stop and failure announcement finish',async()=>{
 const {voice}=fixture(),lease=new ConversationLease();Object.assign(voice,{lease,deviceId:'a'});voice.claimConversation();voice.state='realtime';voice.realtime.state={active:true};voice.realtime.blocked=()=>voice.realtime.state.active;
 voice.realtime.stop=async()=>{};voice.cancel();assert.equal(lease.owner,'a');
 let release;voice.playback=()=>new Promise(r=>release=r);voice.realtime.state={active:false};
 voice.realtimeState({active:false,last_error:'media_failed'});assert.equal(lease.owner,'a');release();await new Promise(r=>setImmediate(r));assert.equal(lease.owner,null);
});
test('a recovered reservation is released if session disappeared before first poll',()=>{
 const {voice}=fixture(),lease=new ConversationLease();Object.assign(voice,{lease,deviceId:'a',leaseToken:lease.acquire('a')});
 voice.realtimeState({active:false,state:'idle'});assert.equal(lease.owner,null);
});
