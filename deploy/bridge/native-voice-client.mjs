import {AudioMirror,nativeAudioOptIn} from './audio-mirror.mjs';
const URL='http://127.0.0.1:4417';
export function nativeWakeOptIn(flag,key){return flag && !Array.isArray(flag) && Object.keys(flag).length===1 && flag.enabled===true && typeof key==='string' && key.length ? {url:URL,key}:null;}
export class NativeVoiceClient {
 constructor(config,{request,mirrorFactory=c=>new AudioMirror(c),auto=true}={}){
  this.key=config.key;this.mirrorFactory=mirrorFactory;this.mirror=null;this.mirrorEnabled=false;this.known=false;this.closed=false;this.pending=false;this.starting=false;this.revision=0;this.state={state:'unknown',active:false,expires_at:null,last_error:null};
  this.request=request ?? (async(path,method='GET')=>{const r=await fetch(URL+path,{method,headers:{Authorization:'Bearer '+this.key,'Content-Type':'application/json'},body:method==='POST'?'{}':undefined,signal:AbortSignal.timeout(2000)});if(!r.ok)throw Error('Unavailable');return r.json();});
  if(auto)void this.poll();
  this.auto=auto;
 }
 blocked(){return (this.pending && Date.now()<(this.boundUntil??Infinity)) || (!this.known && !this.unavailable) || (this.state.active && Date.now()<(this.boundUntil??Infinity));}
 status(){return {...this.state,available:this.known,blocked:this.blocked(),mirror_enabled:this.mirrorEnabled,audio_mirror:this.mirror?.status()??{connected:false,frames_sent:0,backpressure:0}};}
 notify(){this.onState?.(this.status());}
 closeMirror(){this.mirror?.close();this.mirror=null;this.mirrorEnabled=false;this.mirrorExpiry=null;}
 accept(s){
  if(this.closed)return;
  if(!s || !['idle','starting','ready','stopping','failed'].includes(s.state) || typeof s.active!=='boolean' || (s.expires_at!==null && (!Number.isSafeInteger(s.expires_at) || s.expires_at>Date.now()+300000)) || (s.state==='ready' && (!s.active || !Number.isSafeInteger(s.expires_at) || s.expires_at<=Date.now() || s.expires_at-Date.now()>300000)) || ((s.state==='idle'||s.state==='failed')&&s.active))throw Error('Invalid status');
  this.known=true;this.unavailable=false;this.state={state:s.state,active:s.active,expires_at:s.expires_at,last_error:typeof s.last_error==='string'&&/^[a-z0-9_]{1,80}$/i.test(s.last_error)?s.last_error:null};
  if(s.active)this.boundUntil=s.expires_at??this.boundUntil??Date.now()+300000;else{this.pending=false;this.boundUntil=null;}
  if(s.state!=='ready')this.closeMirror();
  else if(this.mirrorExpiry!==s.expires_at){this.closeMirror();this.mirror=this.mirrorFactory(nativeAudioOptIn({expires_at:s.expires_at}));this.mirrorExpiry=s.expires_at;this.mirrorEnabled=!this.pending || this.cueExpiry===s.expires_at; if(this.pending)this.onReady?.({...this.state});}
  this.notify();
 }
 schedulePoll(){if(this.auto&&!this.closed){clearTimeout(this.timer);this.timer=setTimeout(()=>void this.poll(),1000);this.timer.unref?.();}}
 async poll(){
  if(this.closed||this.polling)return;
  if(this.starting){this.schedulePoll();return;}
  this.polling=true;const revision=this.revision;
  try{const status=await this.request('/status');if(!this.closed&&revision===this.revision)this.accept(status);}
  catch{if(!this.closed&&revision===this.revision){this.known=false;this.unavailable=true;this.closeMirror();this.notify();}}
  finally{this.polling=false;this.schedulePoll();}
 }
 async start(){
  if(this.closed||!this.known||this.blocked()||this.state.active)return false;
  this.revision++;this.starting=true;this.pending=true;this.boundUntil=Date.now()+300000;this.notify();
  try{const status=await this.request('/start','POST');if(this.closed)return false;this.accept(status);return true;}
  catch{if(!this.closed){this.known=false;this.unavailable=true;this.state={state:'unknown',active:true,expires_at:null,last_error:null};this.notify();}return false;}
  finally{this.starting=false;this.schedulePoll();}
 }
 enableMirror(s){if(this.closed||!this.known||this.state.state!=='ready'||this.mirrorExpiry!==s.expires_at||s.expires_at<=Date.now())return false;this.mirrorEnabled=true;this.cueExpiry=s.expires_at;this.notify();return true;}
 audio(data){if(this.mirrorEnabled&&this.known&&Date.now()<this.mirrorExpiry)this.mirror?.audio(data);}
 close(){this.closed=true;clearTimeout(this.timer);this.closeMirror();}
}
