import {spawn as nodeSpawn, execFile} from 'node:child_process';
import {createServer} from 'node:http';
import {timingSafeEqual} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';

export class NativeSupervisor {
  constructor({spawn, preflight, now=Date.now, setTimeout:timer=setTimeout, clearTimeout:clear=clearTimeout, killGroup=(pid,sig)=>process.kill(-pid,sig)}={}) {
    this.spawn=spawn;this.preflight=preflight;this.now=now;this.timer=timer;this.clear=clear;this.killGroup=killGroup;
    this.state='idle';this.child=null;this.pending=false;this.expires=null;this.error=null;this.generation=0;this.timers=[];this.waiters=[];
  }
  status(){return {state:this.state,active:this.pending||!!this.child,expires_at:this.expires,last_error:this.error};}
  later(fn,ms){const t=this.timer(fn,ms);t.unref?.();this.timers.push(t);}
  clearTimers(){for(const t of this.timers)this.clear(t);this.timers=[];}
  start(){
    if(this.closed||this.pending||this.child)return this.status();
    this.state='starting';this.pending=true;this.expires=null;this.error=null;this.final=null;this.exitInfo=null;this.errorEvent=false;this.signalled=false;this.stopped=false;this.buffer='';this.stdoutBytes=0;const generation=++this.generation;
    this.later(()=>this.fail('startup_timeout'),50000);
    Promise.resolve().then(()=>{if(generation!==this.generation||!this.pending)return;return this.preflight();}).then(()=>{
      if(generation!==this.generation||!this.pending)return;
      try{const child=this.spawn();this.child=child;this.pending=false;
        child.stdout.on('data',data=>{if(this.child===child)this.consume(data);});child.stderr?.on('data',()=>{});
        child.on('error',()=>{if(this.child!==child)return;this.error??='child_error';if(!Number.isSafeInteger(child.pid)||child.pid<=0){this.exited(null,null);return;}this.fail('child_error');});
        const settle=(code,signal)=>{if(this.child===child)this.exited(code,signal);};
        child.on('exit',(code,signal)=>{
          if(this.child!==child)return;
          this.exitInfo={code,signal};
          // Final stdout may still be queued after exit; close confirms stream drainage.
          this.later(()=>{if(this.child===child){this.error??='stdout_close_timeout';settle(code,signal);}},50000);
        });
        child.on('close',(code,signal)=>{const result=this.exitInfo??{code,signal};settle(result.code,result.signal);});
      }catch{this.pending=false;this.fail('spawn_failed');}
    },()=>{if(generation===this.generation&&this.pending){this.pending=false;this.fail('preflight_failed');}});
    return this.status();
  }
  consume(data){
    if(this.error)return;
    this.stdoutBytes+=Buffer.byteLength(data);
    if(this.stdoutBytes>65536){this.fail('stdout_too_large');return;}
    this.buffer+=data.toString();let pos;
    while((pos=this.buffer.indexOf('\n'))>=0){const line=this.buffer.slice(0,pos);this.buffer=this.buffer.slice(pos+1);let event;try{event=JSON.parse(line);}catch{this.fail('invalid_stdout');return;}
      if(event?.event==='ready'){
        if(this.state==='stopping'||this.exitInfo)continue;
        const expiry=event.expires_at,now=this.now();
        if(this.state!=='starting'||!Number.isSafeInteger(expiry)||expiry<=now||expiry>now+300000){this.fail('invalid_ready');return;}
        this.clearTimers();this.expires=expiry;this.state='ready';this.later(()=>{this.stopped=true;this.stop();},Math.max(0,expiry-this.now()));
      }else if(event?.event==='final'&&['failed','expired'].includes(event.status)&&Array.isArray(event.cleanup_errors)){
        this.final={status:event.status,clean:event.cleanup_errors.length===0,interrupted:event.error==='Session interrupted by SIGTERM'};
      }else if(event?.event==='error'&&typeof event.error_type==='string'){
        // Python prints a safe final error after graceful signal cleanup. Exit decides outcome.
        this.errorEvent=true;
      }else{this.fail('invalid_stdout');return;}
    }
  }
  fail(code){this.error??=code;this.stop();if(!this.child&&!this.pending){this.state='failed';this.finish();}}
  stop(){
    if(!this.pending&&!this.child)return this.status();
    this.stopped=true;this.state='stopping';
    if(this.pending){this.pending=false;++this.generation;this.state=this.error?'failed':'idle';this.finish();return this.status();}
    if(this.exitInfo)return this.status();
    if(!this.signalled){this.clearTimers();this.signalled=true;try{this.child.kill('SIGTERM');}catch{this.error??='signal_failed';}
      const owned=this.child;this.later(()=>{if(this.child===owned){this.error??='cleanup_timeout';if(this.exitInfo){this.exited(this.exitInfo.code,this.exitInfo.signal);return;}try{this.killGroup(owned.pid,'SIGKILL');}catch{this.error??='group_signal_failed';}}},50000);
    }return this.status();
  }
  exited(code,signal){
    this.clearTimers();this.child=null;this.signalled=false;
    if(this.buffer)this.error??='invalid_stdout';
    if(!this.error){if(this.final&&!this.final.clean)this.error='cleanup_failed';else if(!(this.final?.clean&&((this.final.status==='expired'&&code===0&&!signal)||(this.stopped&&this.final.interrupted&&code===1&&!signal))))this.error='child_exit';}
    this.expires=null;this.state=this.error?'failed':'idle';this.finish();
  }
  finish(){this.clearTimers();for(const r of this.waiters.splice(0))r();}
  async shutdown(){this.closed=true;this.stop();if(this.child||this.pending)await new Promise(r=>this.waiters.push(r));}
}

export function createSupervisorServer(supervisor, adminKey){
  if(typeof adminKey!=='string'||!adminKey)throw Error('admin_key_required');
  const expected=Buffer.from('Bearer '+adminKey);
  return createServer(async(req,res)=>{
    const reply=(code,value)=>{res.writeHead(code,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
    const got=Buffer.from(typeof req.headers.authorization==='string'?req.headers.authorization:'');
    if(got.length!==expected.length||!timingSafeEqual(got,expected)){req.resume();reply(401,{error:'unauthorized'});return;}
    if(req.headers.origin!==undefined&&req.headers.origin!=='null'){req.resume();reply(403,{error:'origin_rejected'});return;}
    if(req.method==='GET'&&req.url==='/status'){reply(200,supervisor.status());return;}
    if(req.method!=='POST'||!['/start','/stop'].includes(req.url)){req.resume();reply(404,{error:'not_found'});return;}
    let body='',size=0;try{for await(const chunk of req){size+=chunk.length;if(size>1024){req.resume();reply(413,{error:'body_too_large'});return;}body+=chunk.toString();}}catch{reply(400,{error:'invalid_body'});return;}
    try{const parsed=JSON.parse(body);if(!parsed||Array.isArray(parsed)||typeof parsed!=='object'||Object.keys(parsed).length)throw Error();}catch{reply(400,{error:'empty_json_required'});return;}
    reply(200,req.url==='/start'?supervisor.start():supervisor.stop());
  });
}

const ROOT=fileURLToPath(new URL('../../',import.meta.url));
export const FIXED_PATHS={root:ROOT,host:'root@192.168.100.186',control:resolve(ROOT,'.codex-runs/lx06-diagnostic/control'),knownHosts:resolve(ROOT,'.codex-runs/lx06-known-hosts'),python:resolve(ROOT,'.codex-runs/mac-voice-env/bin/python')};
export function productionSupervisor(paths=FIXED_PATHS){
  const sshArgs=['-S',paths.control,'-o','ControlMaster=no','-o','ControlPath='+paths.control,'-o','UserKnownHostsFile='+paths.knownHosts,'-o','StrictHostKeyChecking=yes','-o','BatchMode=yes','-o','GlobalKnownHostsFile=/dev/null','-o','ProxyCommand=/usr/bin/false','-o','ConnectionAttempts=1','-o','ConnectTimeout=3','-o','HostKeyAlgorithms=+ssh-rsa','-T',paths.host,'true'];
  return new NativeSupervisor({preflight:()=>new Promise((yes,no)=>execFile('/usr/bin/ssh',sshArgs,{timeout:4000,maxBuffer:1024},err=>err?no(Error('preflight_failed')):yes())),spawn:()=>nodeSpawn(paths.python,[resolve(ROOT,'mac/native-voice/session.py'),'--seconds','300','--dynamic-mirror','--host',paths.host,'--control-path',paths.control,'--known-hosts',paths.knownHosts],{cwd:ROOT,detached:true,stdio:['ignore','pipe','pipe']})});
}
export async function main(){const config=JSON.parse(readFileSync(resolve(ROOT,'mac/codex-service/private/config.json'),'utf8'));const supervisor=productionSupervisor();const server=createSupervisorServer(supervisor,config.admin_key);server.listen(4417,'127.0.0.1');let closing=false;const close=async()=>{if(closing)return;closing=true;server.close();await supervisor.shutdown();server.closeAllConnections();};process.on('SIGTERM',close);process.on('SIGINT',close);}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(()=>{process.stderr.write('native_supervisor_start_failed\n');process.exitCode=1;});
