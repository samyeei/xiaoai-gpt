import { EventEmitter } from 'node:events';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync, renameSync, existsSync } from 'node:fs';
import { dirname } from 'node:path';
import { isDeepStrictEqual } from 'node:util';

const terminal = new Set(['completed','failed','cancelled']);
const idPattern = /^[a-zA-Z0-9_-]{1,80}$/;
const hash = text => createHash('sha256').update(text).digest('hex');
const approvalMethods = new Set(['item/commandExecution/requestApproval','item/fileChange/requestApproval','item/tool/requestUserInput','item/permissions/requestApproval','mcpServer/elicitation/request']);
export class CodexService extends EventEmitter {
  constructor({rpc,cwd,stateFile,model,reasoningEffort,taskTimeout=15*60*1000}) {
    super(); this.rpc=rpc; this.cwd=cwd; this.stateFile=stateFile; this.taskTimeout=taskTimeout; this.model=model;this.reasoningEffort=reasoningEffort;
    this.jobs=new Map(); this.queue=[]; this.active=null; this.threadId=null; this.available=false; this.closed=false;
    if (existsSync(stateFile)) {
      const saved=JSON.parse(readFileSync(stateFile,'utf8'));
      if (saved.cwd !== cwd) throw new Error('Saved session directory mismatch');
      this.threadId=saved.threadId; this.recoveryTurn=saved.activeTurn;
      this.uncertainSubmission=!!saved.uncertainSubmission;
      for (const job of saved.jobs ?? []) {
        if (!terminal.has(job.status)) {job.status='failed';job.error='Service restarted; previous task was not repeated';}
        this.jobs.set(job.request_id,job);
      }
    }
    rpc.on('notification',packet=>this.note(packet));
    rpc.on('serverRequest',packet=>this.serverRequest(packet));
    rpc.on('disconnected',()=>this.disconnected());
  }
  persist() {
    mkdirSync(dirname(this.stateFile),{recursive:true,mode:0o700});
    const state={cwd:this.cwd,threadId:this.threadId,activeTurn:this.active?.turnId ?? this.recoveryTurn ?? null,
      uncertainSubmission:!!this.uncertainSubmission || !!(this.active && !this.active.turnId),
      jobs:[...this.jobs.values()].map(j=>({...this.view(j),digest:j.digest}))};
    const temporary=this.stateFile+'.tmp'; writeFileSync(temporary,JSON.stringify(state),{mode:0o600}); renameSync(temporary,this.stateFile);
  }
  view(j) {
    return {request_id:j.request_id,status:j.status,created_at:j.created_at,
      ...(j.reply ? {reply:j.reply} : {}),...(j.error ? {error:j.error} : {})};
  }
  change(j) {this.persist();this.emit('job',this.view(j));}
  get(id) { const j=this.jobs.get(id); if (!j) throw new Error('Not found'); return this.view(j); }
  status() {return {service:'xiaoai-codex',ready:this.available,pending:[...this.jobs.values()].filter(j=>!terminal.has(j.status)).length,waiting_user:this.approvals().length,model:this.effectiveModel??null,reasoning_effort:this.effectiveEffort??null};}
  async start() {
    await this.rpc.ready();
    const params={cwd:this.cwd,...(this.model?{model:this.model}:{}),...(this.reasoningEffort?{config:{model_reasoning_effort:this.reasoningEffort}}:{})};
    const response=this.threadId ? await this.rpc.request('thread/resume',{...params,threadId:this.threadId}) :
      await this.rpc.request('thread/start',{...params,developerInstructions:'这是独立的中文语音会话。最终答复尽量在180个汉字内，使用自然口语；重要操作风险和等待用户确认必须明确说明。保留用户请求的工作目标；不能把已提交或等待批准说成已经完成。'});
    if(this.model && response.model!==this.model)throw new Error('Configured model was not selected');
    if(this.reasoningEffort&&response.reasoningEffort!==this.reasoningEffort)throw new Error('Configured reasoning effort was not selected');
    this.effectiveEffort=response.reasoningEffort??null;
    this.effectiveModel=response.model??null;
    this.threadId=response.thread.id;
    const turns=response.thread.turns;
    if(this.uncertainSubmission && !Array.isArray(turns))throw new Error('Previous turn recovery unconfirmed');
    if(Array.isArray(turns)){
      const running=turns.filter(t=>t.status==='inProgress');
      if(running.length>1)throw new Error('Previous turn recovery unconfirmed');
      if(running.length===1)this.recoveryTurn=running[0].id;
      this.uncertainSubmission=false;
    }
    if (this.recoveryTurn) {
      const previous=response.thread.turns?.find(t=>t.id===this.recoveryTurn);
      if (previous && ['completed','failed','interrupted'].includes(previous.status)) this.recoveryTurn=null;
      else {
        const turnId=this.recoveryTurn;
        const acknowledged=new Promise((resolve,reject)=>{
          const timer=setTimeout(()=>{this.off('recovered',finish);reject(new Error('Previous turn recovery unconfirmed'));},30000);
          const finish=()=>{clearTimeout(timer);resolve();}; this.once('recovered',finish);
        });
        // Register the waiter before the interrupt: terminal notifications can precede the RPC response.
        try { await this.rpc.request('turn/interrupt',{threadId:this.threadId,turnId}); await acknowledged; }
        catch(error) {acknowledged.catch(()=>{});throw error;}
      }
    }
    this.available=true; this.persist(); this.drain();
  }
  submit(input) {
    if (!input || Object.keys(input).some(k=>!['request_id','text'].includes(k)) || typeof input.request_id!=='string' || !idPattern.test(input.request_id) ||
      typeof input.text !== 'string' || !input.text.trim() || Buffer.byteLength(input.text)>8192) throw new Error('Invalid request');
    const digest=hash(input.text), old=this.jobs.get(input.request_id);
    if (old) {if(old.digest !== digest) throw new Error('Request ID conflict'); return this.view(old);}
    if (!this.available || this.closed) throw new Error('Codex unavailable');
    if (this.queue.length >= 8 || this.jobs.size >= 1000) throw new Error('Task capacity reached');
    const job={request_id:input.request_id,text:input.text,digest,status:'queued',created_at:Date.now(),approvals:new Map(),items:new Map()};
    this.jobs.set(job.request_id,job); this.queue.push(job); this.change(job); this.drain(); return this.view(job);
  }
  async drain() {
    if (!this.available || this.closed || this.active || this.recoveryTurn) return;
    const job=this.queue.shift(); if (!job) return;
    if (terminal.has(job.status)) {this.drain();return;}
    this.active=job;job.status='running';this.change(job);
    job.timer=setTimeout(()=>{void this.cancel(job.request_id,'Codex task timed out');},this.taskTimeout);job.timer.unref?.();
    try {
      const result=await this.rpc.request('turn/start',{threadId:this.threadId,...(this.model?{model:this.model}:{}),...(this.reasoningEffort?{effort:this.reasoningEffort}:{}),input:[{type:'text',text:job.text}]});
      if (this.active !== job) return;
      job.turnId=result.turn.id; this.persist();
      if (terminal.has(job.status)) await this.interrupt(job);
    } catch {
      // Submission may already have arrived. Stop the process rather than steering another turn into it.
      this.disconnected(); this.rpc.close?.();
    }
  }
  async interrupt(job) {
    if (!job.turnId) return;
    try { await this.rpc.request('turn/interrupt',{threadId:this.threadId,turnId:job.turnId}); }
    catch {this.disconnected();this.rpc.close?.();}
    if (this.active === job) {
      clearTimeout(job.cancelTimer);
      job.cancelTimer=setTimeout(()=>{if(this.active===job){this.disconnected();this.rpc.close?.();}},10000);job.cancelTimer.unref?.();
    }
  }
  async cancel(id,reason) {
    const job=this.jobs.get(id);if(!job) throw new Error('Not found');
    if (terminal.has(job.status)) return this.view(job);
    job.status=reason ? 'failed':'cancelled'; if(reason)job.error=reason;delete job.reply;
    job.approvals?.clear();clearTimeout(job.timer);this.change(job);
    if(this.active===job) await this.interrupt(job); else this.queue=this.queue.filter(x=>x!==job);
    return this.view(job);
  }
  note({method,params:p}) {
    if (!p || p.threadId!==this.threadId) return;
    if (method==='turn/completed' && p.turn.id===this.recoveryTurn) {this.recoveryTurn=null;this.emit('recovered');return;}
    const job=this.active;if(!job)return;
    if (method==='turn/started' && !job.turnId) {job.turnId=p.turn.id;this.persist();}
    const turnId=p.turnId ?? p.turn?.id;
    if (turnId && job.turnId && turnId!==job.turnId)return;
    if (method==='serverRequest/resolved') {
      job.approvals.delete(String(p.requestId));
      if(job.status==='waiting_user' && !job.approvals.size){job.status='running';this.change(job);}
    }
    if (method==='item/started' || method==='item/completed') job.items.set(p.item.id,p.item);
    if (method==='item/completed' && p.item.type==='agentMessage' && (!p.item.phase || p.item.phase==='final_answer')) job.finalText=p.item.text;
    if (method==='turn/completed') {
      if (!terminal.has(job.status)) {
        if(p.turn.status==='completed' && job.finalText?.trim()) {job.status='completed';job.reply=job.finalText.trim();}
        else {job.status=p.turn.status==='interrupted'?'cancelled':'failed';job.error='Codex turn did not produce a successful final answer';}
      }
      clearTimeout(job.timer);clearTimeout(job.cancelTimer);job.approvals.clear();this.active=null;delete job.text;
      this.change(job);this.drain();
    }
  }
  serverRequest(packet) {
    const job=this.active,p=packet.params;
    if(!job || terminal.has(job.status) || p?.threadId!==this.threadId || (p.turnId && job.turnId && p.turnId!==job.turnId) || !approvalMethods.has(packet.method)) {
      this.rpc.reject?.(packet.id);return;
    }
    job.approvals.set(String(packet.id),packet);job.status='waiting_user';this.change(job);
  }
  approvals() {return this.active ? [...this.active.approvals.values()].map(p=>({id:String(p.id),method:p.method,params:p.params,item:this.active.items?.get(p.params.itemId)})) : [];}
  resolve(id,result) {
    const job=this.active,packet=job?.approvals.get(String(id));if(!packet)throw new Error('Not found');
    if(!result || typeof result!=='object')throw new Error('Invalid response');
    if(['item/commandExecution/requestApproval','item/fileChange/requestApproval'].includes(packet.method)) {
      if(Object.keys(result).length!==1 || !['accept','decline','cancel'].includes(result.decision))throw new Error('Invalid decision');
      const choices=packet.params.availableDecisions;
      if(choices && !choices.includes(result.decision))throw new Error('Invalid decision');
    } else if(packet.method==='item/tool/requestUserInput') {
      const questions=packet.params.questions ?? [],answers=result.answers;
      if(Object.keys(result).length!==1 || !answers || typeof answers!=='object' || Object.keys(answers).length!==questions.length ||
        questions.some(q=>!Array.isArray(answers[q.id]?.answers) || !answers[q.id].answers.length || answers[q.id].answers.some(a=>typeof a!=='string')))throw new Error('Invalid answers');
    } else if(packet.method==='item/permissions/requestApproval') {
      // Grant precisely what was displayed, once. Do not accept caller-invented scope or session-wide grants.
      if(Object.keys(result).some(k=>!['permissions','scope'].includes(k)) || (result.scope!==undefined && result.scope!=='turn') ||
        (!isDeepStrictEqual(result.permissions,{}) && !isDeepStrictEqual(result.permissions,packet.params.permissions)))throw new Error('Invalid permission response');
    } else if(packet.method==='mcpServer/elicitation/request') {
      if(Object.keys(result).some(k=>!['action','content'].includes(k)) || !['decline','cancel'].includes(result.action) || result.content!=null)throw new Error('Invalid elicitation response; only decline or cancel supported');
    }
    this.rpc.respond(packet.id,result);job.approvals.delete(String(id));
    if(!job.approvals.size)job.status='running';this.change(job);
  }
  disconnected() {
    this.available=false;
    for(const j of this.jobs.values())if(!terminal.has(j.status)){j.status='failed';j.error='Codex disconnected';clearTimeout(j.timer);clearTimeout(j.cancelTimer);j.approvals?.clear();}
    // Keep active turn identity on disk for recovery; never start a new task on uncertain submission.
    this.persist();this.emit('unavailable');
  }
  close() {this.closed=true;this.available=false;for(const j of this.jobs.values()){clearTimeout(j.timer);clearTimeout(j.cancelTimer);}this.persist();}
}
