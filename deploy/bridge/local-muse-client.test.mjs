import test from 'node:test';
import assert from 'node:assert/strict';
import { LocalMuseClient } from './local-muse-client.mjs';
const cfg={url:'http://127.0.0.1:4414',key:'a'.repeat(64)};
test('only numeric IPv4 loopback or localhost allowed; safe Muse configuration failures',()=>{
 for(const url of ['http://192.168.100.106:4414','http://127.0.0.2:4414','http://example.local:4414','http://localhost.evil:4414','https://127.0.0.1:4414'])assert.throws(()=>new LocalMuseClient({...cfg,url}),/Invalid Muse configuration/);
 assert.doesNotThrow(()=>new LocalMuseClient(cfg));assert.doesNotThrow(()=>new LocalMuseClient({...cfg,url:'http://localhost:4414'}));
});
test('facade inherits uncertain POST polling without duplicate sends; final-only Muse errors',async()=>{
 const client=new LocalMuseClient(cfg);let posts=0,cancels=0,polls=0;client.pollInterval=1;
 client.http=async(path,method)=>{if(path.endsWith('/cancel')){cancels++;return{};}if(method==='POST'){posts++;throw Error('lost');}return ++polls===1?{status:'running'}:{status:'completed',reply:'final'};};
 assert.equal(await client.ask('same','hello'),'final');assert.equal(posts,1);assert.equal(cancels,1);
 client.http=async()=>({status:'failed',error:'secret'});await assert.rejects(client.ask('bad','hello'),/Muse request unavailable/);
});
test('network facade labels health failure Muse and preserves authentication',async()=>{
 const client=new LocalMuseClient(cfg),original=globalThis.fetch;
 try{globalThis.fetch=async(url,options)=>{assert.equal(options.headers.Authorization,'Bearer '+cfg.key);throw Error('secret');};await assert.rejects(client.health(),/Muse request unavailable/);}finally{globalThis.fetch=original;}
});

import { createEndpoints } from '../../mac/codex-service/http.mjs';
import { once } from 'node:events';
import { createHmac } from 'node:crypto';
for (const priorStatus of ['completed','running']) test(`real HTTP definitive conflict leaves prior ${priorStatus} job untouched`,async t=>{
 const prior={request_id:'prior',digest:createHmac('sha256',Buffer.from(cfg.key,'hex')).update('original').digest('hex'),status:priorStatus,reply:'prior reply'},calls=[];
 const service={jobs:new Map([['prior',prior]]),submit:()=>{calls.push('POST');throw Error('Request ID conflict');},get:()=>{calls.push('GET');return prior;},cancel:()=>{calls.push('cancel');prior.status='cancelled';return prior;},status:()=>({ready:true})};
 const {lan,control}=createEndpoints({service,key:cfg.key,adminKey:'b'.repeat(64),port:0,controlPort:0});await Promise.all([once(lan,'listening'),once(control,'listening')]);t.after(()=>{lan.closeAllConnections();control.closeAllConnections();lan.close();control.close();});
 const client=new LocalMuseClient({...cfg,url:`http://127.0.0.1:${lan.address().port}`,request_timeout_ms:100});
 await assert.rejects(client.ask('prior','changed'),/Muse request unavailable/);assert.deepEqual(calls,['POST']);assert.equal(prior.status,priorStatus);
});
test('real HTTP lost conflict response checks digest before recovery and cancellation',async t=>{
 const prior={request_id:'prior',digest:createHmac('sha256',Buffer.from(cfg.key,'hex')).update('original').digest('hex'),status:'running',reply:'prior reply'},calls=[];
 const service={jobs:new Map([['prior',prior]]),submit:()=>{calls.push('POST');throw Error('Request ID conflict');},get:()=>{calls.push('GET');return prior;},cancel:()=>{calls.push('cancel');prior.status='cancelled';return prior;},status:()=>({ready:true})};
 const {lan,control}=createEndpoints({service,key:cfg.key,adminKey:'b'.repeat(64),port:0,controlPort:0});await Promise.all([once(lan,'listening'),once(control,'listening')]);t.after(()=>{lan.closeAllConnections();control.closeAllConnections();lan.close();control.close();});
 const client=new LocalMuseClient({...cfg,url:`http://127.0.0.1:${lan.address().port}`,request_timeout_ms:100});const original=globalThis.fetch;
 try{globalThis.fetch=async(url,options)=>{const res=await original(url,options);if(url.endsWith('/requests')&&options.method==='POST'){await res.arrayBuffer();throw Error('response lost');}return res;};
 await assert.rejects(client.ask('prior','changed'),/Muse request unavailable/);assert.deepEqual(calls,['POST']);assert.equal(prior.status,'running');}finally{globalThis.fetch=original;}
});
test('real HTTP lost successful POST recovers only matching question and conditional cancellation',async t=>{
 const digest=createHmac('sha256',Buffer.from(cfg.key,'hex')).update('original').digest('hex'),calls=[];
 const service={jobs:new Map(),submit:x=>{const job={request_id:x.request_id,digest,status:'completed',reply:'correct'};service.jobs.set(x.request_id,job);calls.push('POST');return job;},get:id=>{calls.push('GET');return service.jobs.get(id);},cancel:id=>{calls.push('cancel');return service.jobs.get(id);},status:()=>({ready:true})};
 const {lan,control}=createEndpoints({service,key:cfg.key,adminKey:'b'.repeat(64),port:0,controlPort:0});await Promise.all([once(lan,'listening'),once(control,'listening')]);t.after(()=>{lan.closeAllConnections();control.closeAllConnections();lan.close();control.close();});
 const client=new LocalMuseClient({...cfg,url:`http://127.0.0.1:${lan.address().port}`,request_timeout_ms:100}),original=globalThis.fetch;
 try{globalThis.fetch=async(url,options)=>{if(!url.endsWith('/requests'))assert.equal(options.headers['X-Request-Digest'],digest);const response=await original(url,options);if(url.endsWith('/requests')){await response.arrayBuffer();throw Error('lost');}return response;};assert.equal(await client.ask('same','original'),'correct');assert.deepEqual(calls,['POST','GET','cancel']);}finally{globalThis.fetch=original;}
});
test('lost conflict and lost recovery still condition final cancel on question digest',async t=>{
 const prior={request_id:'prior',digest:createHmac('sha256',Buffer.from(cfg.key,'hex')).update('original').digest('hex'),status:'running'},calls=[];
 const service={jobs:new Map([['prior',prior]]),submit:()=>{calls.push('POST');throw Error('Request ID conflict');},get:()=>{calls.push('GET');return prior;},cancel:()=>{calls.push('cancel');prior.status='cancelled';return prior;},status:()=>({ready:true})};
 const {lan,control}=createEndpoints({service,key:cfg.key,adminKey:'b'.repeat(64),port:0,controlPort:0});await Promise.all([once(lan,'listening'),once(control,'listening')]);t.after(()=>{lan.closeAllConnections();control.closeAllConnections();lan.close();control.close();});
 const client=new LocalMuseClient({...cfg,url:`http://127.0.0.1:${lan.address().port}`,request_timeout_ms:100}),original=globalThis.fetch;let cancelHTTP=0;
 try{globalThis.fetch=async(url,options)=>{const response=await original(url,options);if(url.endsWith('/cancel')){cancelHTTP++;assert.equal(response.status,409);return response;}await response.arrayBuffer();throw Error('response lost');};await assert.rejects(client.ask('prior','changed'),/Muse request unavailable/);assert.deepEqual(calls,['POST']);assert.equal(cancelHTTP,1);assert.equal(prior.status,'running');}finally{globalThis.fetch=original;}
});
