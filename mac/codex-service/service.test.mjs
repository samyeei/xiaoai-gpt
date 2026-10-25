import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { CodexService } from './service.mjs';

class FakeRpc extends EventEmitter {
  calls = []; responses = []; turns = 0;
  async ready() {}
  async request(method, params) {
    this.calls.push({ method, params });
    if (method.startsWith('thread/')) { this.resuming=method==='thread/resume'; return { model:params.model,reasoningEffort:params.config?.model_reasoning_effort,thread: { id: params.threadId ?? 'thread-1' } }; }
    if (method === 'turn/start') return { turn: { id: `turn-${++this.turns}` } };
    if (method === 'turn/interrupt' && this.resuming) this.note('turn/completed',{threadId:'thread-1',turn:{id:params.turnId,status:'interrupted'}});
    return {};
  }
  respond(id, result) { this.responses.push({ id, result }); }
  note(method, params) { this.emit('notification', { method, params }); }
  finish(text = '最终回复', status = 'completed', turn = `turn-${this.turns}`) {
    this.note('item/completed', { threadId:'thread-1', turnId:turn, item:{type:'agentMessage',phase:'final_answer',text} });
    this.note('turn/completed', { threadId:'thread-1',turn:{id:turn,status} });
  }
}
const tick = () => new Promise(r => setImmediate(r));
test('reasoning preset reaches thread configuration and every text turn',async t=>{
 const {service:s,rpc}=fixture(t,{model:'gpt-5.6-luna',reasoningEffort:'high'});await s.start();
 assert.deepEqual(rpc.calls[0].params.config,{model_reasoning_effort:'high'});assert.equal(s.status().reasoning_effort,'high');
 s.submit({request_id:'preset-test',text:'固定测试'});await tick();assert.equal(rpc.calls.find(x=>x.method==='turn/start').params.effort,'high');rpc.finish();
});
function fixture(t, options = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'xiaoai-codex-test-'));
  const rpc = new FakeRpc();
  const service = new CodexService({ rpc, cwd:process.cwd(), stateFile:join(dir,'state.json'), ...options });
  t.after(() => { service.close(); rmSync(dir,{recursive:true,force:true}); });
  return { service, rpc, dir };
}
test('a unique request completes only after a matching successful terminal event; commentary is not final', async t => {
  const {service:s,rpc} = fixture(t);
  await s.start(); s.submit({request_id:'job-1',text:'读取项目'}); await tick();
  rpc.note('item/completed',{threadId:'thread-1',turnId:'turn-1',item:{type:'agentMessage',phase:'commentary',text:'已提交'}});
  assert.equal(s.get('job-1').status,'running'); assert.equal(s.get('job-1').reply,undefined);
  rpc.finish('这是真实终态的最终答复');
  assert.equal(s.get('job-1').reply,'这是真实终态的最终答复');
  s.submit({request_id:'job-2',text:'追问'}); await tick(); rpc.finish();
  assert.equal(rpc.calls.filter(x=>x.method==='thread/start').length,1);
  assert.ok(rpc.calls.filter(x=>x.method==='turn/start').every(x=>x.params.threadId==='thread-1'));
});
test('same ID is idempotent and conflicting payload is rejected without another turn', async t => {
  const {service:s,rpc} = fixture(t); await s.start();
  s.submit({request_id:'job-1',text:'你好'}); s.submit({request_id:'job-1',text:'你好'});
  assert.throws(()=>s.submit({request_id:'job-1',text:'不同'}),/conflict/);
  assert.throws(()=>s.submit({request_id:'../bad',text:'你好'}),/Invalid/);
  assert.throws(()=>s.submit({request_id:'job-2',text:' ',cwd:'/tmp'}),/Invalid/);
  await tick(); assert.equal(rpc.turns,1); rpc.finish();
});
test('cancelled active turn retains the queue lock until terminal acknowledgement and drops late replies', async t => {
  const {service:s,rpc} = fixture(t); await s.start();
  s.submit({request_id:'job-1',text:'旧问题'}); await tick();
  s.submit({request_id:'job-2',text:'新问题'}); await s.cancel('job-1'); await tick();
  assert.equal(rpc.turns,1); assert.equal(s.get('job-1').status,'cancelled');
  rpc.finish('过期回复'); await tick(); assert.equal(rpc.turns,2);
  assert.equal(s.get('job-1').reply,undefined); rpc.finish('新回复');
  assert.equal(s.get('job-2').reply,'新回复');
});
test('approval is pending until explicit local response; concurrent requests remain waiting', async t => {
  const {service:s,rpc} = fixture(t); await s.start(); s.submit({request_id:'job-1',text:'任务'}); await tick();
  const params={threadId:'thread-1',turnId:'turn-1',command:'touch example'};
  rpc.emit('serverRequest',{id:81,method:'item/commandExecution/requestApproval',params});
  rpc.emit('serverRequest',{id:82,method:'item/fileChange/requestApproval',params});
  assert.equal(s.get('job-1').status,'waiting_user'); assert.equal(rpc.responses.length,0);
  assert.throws(()=>s.resolve('81',{decision:'acceptForSession'}),/Invalid/);
  s.resolve('81',{decision:'decline'}); assert.equal(s.get('job-1').status,'waiting_user');
  s.resolve('82',{decision:'accept'}); assert.equal(s.get('job-1').status,'running');
  assert.deepEqual(rpc.responses.map(x=>x.result),[{decision:'decline'},{decision:'accept'}]); rpc.finish();
});
test('restart resumes the saved thread but does not repeat an uncertain turn', async t => {
  const {service:s,rpc,dir} = fixture(t); await s.start(); s.submit({request_id:'job-1',text:'旧问题'}); await tick();
  s.close(); const rpc2=new FakeRpc(); const next=new CodexService({rpc:rpc2,cwd:process.cwd(),stateFile:join(dir,'state.json')});
  t.after(()=>next.close()); await next.start();
  assert.equal(next.get('job-1').status,'failed'); assert.equal(rpc2.turns,0);
  assert.equal(rpc2.calls[0].method,'thread/resume');
  assert.equal(rpc2.calls.filter(x=>x.method==='turn/interrupt').length,1);
  assert.ok(JSON.parse(readFileSync(join(dir,'state.json'))).threadId);
});
test('failed or interrupted terminal events never publish an agent reply as success', async t => {
  const {service:s,rpc} = fixture(t); await s.start(); s.submit({request_id:'job-1',text:'任务'}); await tick();
  rpc.finish('不能当成功','failed'); assert.equal(s.get('job-1').status,'failed'); assert.equal(s.get('job-1').reply,undefined);
});
test('permission grants require explicit exact requested scope and only last for this turn', async t=>{
  const {service:s,rpc}=fixture(t);await s.start();s.submit({request_id:'permission-job',text:'任务'});await tick();
  const permissions={network:{enabled:true},fileSystem:{read:['/tmp/example']}};
  rpc.emit('serverRequest',{id:91,method:'item/permissions/requestApproval',params:{threadId:'thread-1',turnId:'turn-1',permissions}});
  assert.equal(rpc.responses.length,0);
  assert.throws(()=>s.resolve('91',{permissions,scope:'session'}),/Invalid/);
  assert.throws(()=>s.resolve('91',{permissions:{...permissions,fileSystem:{read:['/']}}}),/Invalid/);
  s.resolve('91',{permissions,scope:'turn'});
  assert.deepEqual(rpc.responses[0].result,{permissions,scope:'turn'});rpc.finish();
});
test('restart before turn ID reconciles an in-progress resumed turn and never resubmits it',async t=>{
  const {service:s,rpc,dir}=fixture(t);await s.start();
  rpc.request=async function(method,params){this.calls.push({method,params});if(method==='turn/start')return new Promise(()=>{});return{};};
  s.submit({request_id:'uncertain-job',text:'已经到达但返回丢失'});await tick();s.close();
  const rpc2=new FakeRpc();
  rpc2.request=async function(method,params){this.calls.push({method,params});if(method==='thread/resume')return{thread:{id:'thread-1',turns:[{id:'uncertain-turn',status:'inProgress'}]}};if(method==='turn/interrupt')this.note('turn/completed',{threadId:'thread-1',turn:{id:params.turnId,status:'interrupted'}});return{};};
  const next=new CodexService({rpc:rpc2,cwd:process.cwd(),stateFile:join(dir,'state.json')});t.after(()=>next.close());await next.start();
  assert.equal(rpc2.calls.filter(x=>x.method==='turn/interrupt').length,1);assert.equal(rpc2.calls.find(x=>x.method==='turn/interrupt').params.turnId,'uncertain-turn');
  assert.equal(next.get('uncertain-job').status,'failed');assert.equal(rpc2.calls.filter(x=>x.method==='turn/start').length,0);
});
test('unknown submission with missing recovery evidence refuses readiness on every retry',async t=>{
  const {service:s,rpc,dir}=fixture(t);await s.start();rpc.request=async()=>new Promise(()=>{});s.submit({request_id:'uncertain-job',text:'任务'});await tick();s.close();
  for(let i=0;i<2;i++){
    const next=new CodexService({rpc:new FakeRpc(),cwd:process.cwd(),stateFile:join(dir,'state.json')});
    await assert.rejects(next.start(),/recovery unconfirmed/);assert.equal(next.status().ready,false);next.close();
  }
});
test('configured answering model is applied to new and resumed threads and subsequent turns',async t=>{
 const {service:s,rpc,dir}=fixture(t,{model:'gpt-5.6-luna'});await s.start();
 assert.equal(rpc.calls.find(c=>c.method==='thread/start').params.model,'gpt-5.6-luna');
 s.submit({request_id:'luna-model-check',text:'test'});await tick();assert.equal(rpc.calls.find(c=>c.method==='turn/start').params.model,'gpt-5.6-luna');rpc.finish();s.close();
 const resumedRpc=new FakeRpc(),resumed=new CodexService({rpc:resumedRpc,cwd:process.cwd(),stateFile:join(dir,'state.json'),model:'gpt-5.6-luna'});t.after(()=>resumed.close());await resumed.start();assert.equal(resumedRpc.calls.find(c=>c.method==='thread/resume').params.model,'gpt-5.6-luna');
});
