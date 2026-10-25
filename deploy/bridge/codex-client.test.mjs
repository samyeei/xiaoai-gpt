import test from 'node:test';
import assert from 'node:assert/strict';
import { CodexClient } from './codex-client.mjs';
const config={url:'http://192.168.100.106:4411',key:'a'.repeat(64)};
test('validates endpoint and never leaks key in errors',()=>{
 for(const url of ['https://192.168.100.106:4411','http://example.com:4411','http://192.168.100.106','http://u:p@192.168.100.106:4411','http://192.168.100.106:4411/path','http://192.168.100.106:4411?x=1']) assert.throws(()=>new CodexClient({...config,url}));
 assert.doesNotThrow(()=>new CodexClient(config));
});
test('uncertain submission polls same ID, reports status once and returns final only',async()=>{
 const c=new CodexClient(config), calls=[], statuses=[];let polls=0;
 c.http=async(path,method='GET',body)=>{calls.push({path,method,body});if(path.endsWith('/cancel'))return {};if(method==='POST')throw Error('lost');return ++polls===1?{status:'waiting_user'}:{status:'completed',reply:'done'};};
 c.pollInterval=1;
 assert.equal(await c.ask('id','hello',undefined,s=>statuses.push(s)),'done');
 assert.deepEqual(statuses,['waiting_user','completed']);assert.equal(calls.filter(x=>x.path==='/requests'&&x.method==='POST').length,1);
});
test('failed payload is sanitized and cancellation is attempted',async()=>{
 const c=new CodexClient(config);let cancelled=false;c.http=async path=>path.endsWith('/cancel')?(cancelled=true,{}):{status:'failed',error:'SECRET RAW'};
 await assert.rejects(c.ask('id','hello'),e=>!e.message.includes('SECRET'));assert.equal(cancelled,true);
});
test('HTTP carries authentication and safe errors without exposing server body',async()=>{
 const c=new CodexClient(config),original=globalThis.fetch;let captured;
 try{
  globalThis.fetch=async(url,options)=>{captured={url,options};return {ok:true,json:async()=>({ready:true})};};
  assert.deepEqual(await c.health(),{ready:true});assert.equal(captured.url,config.url+'/health');assert.equal(captured.options.headers.Authorization,'Bearer '+config.key);assert.equal(captured.options.signal.aborted,false);
  globalThis.fetch=async()=>({ok:false,status:500,json:()=>assert.fail('error body must not be read')});
  await assert.rejects(c.health(),/Codex request unavailable/);
 }finally{globalThis.fetch=original;}
});
test('task deadline terminates polling and best effort cancels, without repost',async()=>{
 const c=new CodexClient({...config,request_timeout_ms:15});c.pollInterval=2;let posts=0,cancels=0;
 c.http=async(path,method)=>{if(path.endsWith('/cancel')){cancels++;return {}; }if(method==='POST')posts++;return {status:'running'};};
 await assert.rejects(c.ask('deadline','hello'),/Codex request unavailable/);assert.equal(posts,1);assert.equal(cancels,1);
});
test('external cancellation cancels the fixed request ID and no final reply',async()=>{
 const c=new CodexClient(config),abort=new AbortController();let cancelled=false;
 c.http=async path=>path.endsWith('/cancel')?(cancelled=true,{}):{status:'running'};
 const task=c.ask('cancel','hello',abort.signal);abort.abort();await assert.rejects(task);assert.equal(cancelled,true);
});
test('same-client concurrent same ID cannot override digest or cancel first job',async()=>{
 const c=new CodexClient(config),release={};let cancel=0;
 c.http=async(path,method)=>{if(path.endsWith('/cancel')){cancel++;return{};}return await new Promise(resolve=>{release.resolve=resolve;});};
 const first=c.ask('same','first');await assert.rejects(c.ask('same','different'));assert.equal(cancel,0);
 release.resolve({status:'completed',reply:'first answer'});assert.equal(await first,'first answer');assert.equal(cancel,1);
});
test('408 delivery uncertainty recovers with SHA256-conditioned GET and cancel',async()=>{
 const {createHash}=await import('node:crypto'),digest=createHash('sha256').update('hello').digest('hex'),c=new CodexClient(config),original=globalThis.fetch,calls=[];
 try{globalThis.fetch=async(url,options)=>{calls.push(options.method);if(url.endsWith('/requests'))return{ok:false,status:408};assert.equal(options.headers['X-Request-Digest'],digest);return{ok:true,json:async()=>({status:'completed',reply:'correct'})};};assert.equal(await c.ask('same','hello'),'correct');assert.deepEqual(calls,['POST','GET','POST']);}finally{globalThis.fetch=original;}
});
