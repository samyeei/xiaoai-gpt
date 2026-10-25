import { spawn } from 'node:child_process';
import { EventEmitter } from 'node:events';

export class Rpc extends EventEmitter {
  constructor({ executable = 'codex', cwd, child } = {}) {
    super();
    this.child = child ?? spawn(executable, ['app-server','--listen','stdio://'], {cwd,stdio:['pipe','pipe','pipe']});
    this.pending = new Map(); this.sequence = 0; this.buffer = ''; this.closed = false;
    this.child.stdout.setEncoding('utf8');
    this.child.stdout.on('data', data => {
      this.buffer += data;
      if (this.buffer.length > 8 * 1024 * 1024) { this.fail(); this.child.kill(); return; }
      let end;
      while ((end=this.buffer.indexOf('\n')) >= 0) {
        const line=this.buffer.slice(0,end); this.buffer=this.buffer.slice(end+1);
        if (!line.trim()) continue;
        try {
          const packet=JSON.parse(line);
          if (packet.method) this.emit(packet.id !== undefined ? 'serverRequest' : 'notification',packet);
          else {
            const request=this.pending.get(packet.id);
            if (!request) continue;
            this.pending.delete(packet.id); clearTimeout(request.timer);
            if (packet.error) request.reject(new Error('Codex RPC rejected request'));
            else request.resolve(packet.result);
          }
        } catch { this.fail(); this.child.kill(); return; }
      }
    });
    // Drain stderr without copying sensitive tool output into bridge logs.
    this.child.stderr.on('data',()=>{});
    this.child.on('error',()=>this.fail()); this.child.on('exit',()=>this.fail());
    this.child.stdin.on('error',()=>this.fail());
  }
  send(packet) {
    if (this.closed) throw new Error('Codex disconnected');
    this.child.stdin.write(JSON.stringify(packet)+'\n');
  }
  request(method,params={},timeout=90000) {
    if (this.closed) return Promise.reject(new Error('Codex disconnected'));
    const id=++this.sequence;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('Codex RPC timed out'));},timeout);
      this.pending.set(id,{resolve,reject,timer});
      try { this.send({id,method,params}); }
      catch(error) {clearTimeout(timer);this.pending.delete(id);reject(error);}
    });
  }
  ready() {
    return this.initialized ??= this.request('initialize',{clientInfo:{name:'xiaoai_codex_voice',title:'XiaoAI Codex Voice',version:'0.1.0'},capabilities:{experimentalApi:true}})
      .then(()=>this.send({method:'initialized',params:{}}));
  }
  respond(id,result) { this.send({id,result}); }
  reject(id) { this.send({id,error:{code:-32601,message:'Unsupported bridge request'}}); }
  fail() {
    if (this.closed) return;
    this.closed=true;
    for (const p of this.pending.values()) {clearTimeout(p.timer);p.reject(new Error('Codex disconnected'));}
    this.pending.clear(); this.emit('disconnected');
  }
  close() { this.fail(); this.child.kill(); }
}
