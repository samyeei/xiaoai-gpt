import {WebSocket} from 'ws';
export function realtimeOptIn(flag,key){if(!flag||flag.enabled!==true||!key||Object.keys(flag).some(k=>!['enabled','idle_seconds','max_session_seconds'].includes(k)))return null;return {url:'http://127.0.0.1:4418',key};}
export class RealtimeClient{
 constructor(config,{auto=true,request,socketFactory=(...args)=>new WebSocket(...args)}={}){this.socketFactory=socketFactory;this.config=config;this.state={active:false,state:'idle',session_id:null};this.closed=false;this.revision=0;this.request=request??(async(path,body)=>{const r=await fetch('http://127.0.0.1:4418'+path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+config.key,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(path==='/start'?20000:path==='/stop'?25000:5000)});if(!r.ok)throw Error('Realtime unavailable');return r.json();});if(auto)this.poll();}
 blocked(){return this.starting||this.uncertain||this.state.active;}
 apply(s){if(this.closed||!s||typeof s.active!=='boolean')return;if(this.state.active&&s.active&&s.session_id!==this.state.session_id)return;if(this.config.device_id&&s.active&&s.device_id!==this.config.device_id){this.remoteBusy=true;return;}this.remoteBusy=false;this.state=s;
  if(!s.active){this.socket?.close();this.socket=null;this.readyId=null;}else if(s.state==='ready'&&!this.socket){
   const socket=this.socketFactory('ws://127.0.0.1:4419/audio/'+s.session_id,{headers:{Authorization:'Bearer '+this.config.key},maxPayload:65536});this.socket=socket;
   socket.on('error',()=>{});socket.on('open',()=>{if(this.closed||this.state.session_id!==s.session_id){socket.close();return;}this.readyId=s.session_id;this.onReady?.(s);});
   socket.on('close',()=>{const owned=this.socket===socket;if(owned)this.socket=null;if(owned&&this.state.active&&this.state.session_id===s.session_id&&!this.closed)void this.stop('audio_socket_closed').catch(()=>{});});
  }this.onState?.(s);
 }
 async poll(){if(this.closed)return;try{const revision=this.revision;const state=await this.request('/status');if(revision===this.revision){this.uncertain=false;this.apply(state);}}catch{this.onUnavailable?.();}finally{if(!this.closed){this.timer=setTimeout(()=>this.poll(),500);this.timer.unref?.();}}}
 async start(){if(this.remoteBusy)return false;if(this.blocked())return true;this.starting=true;this.revision++;try{this.apply(await this.request('/start',{device_id:this.config.device_id??'lx06-primary',mode:'continuous'}));return this.state.active;}catch{try{this.apply(await this.request('/status'));if(this.state.active)await this.stop();}catch{this.uncertain=true;}return false;}finally{this.starting=false;}}
 async enable(s){if(this.state.session_id!==s.session_id||this.socket?.readyState!==WebSocket.OPEN)return false;this.apply(await this.request('/listen',{session_id:s.session_id}));return true;}
 audio(pcm){if(this.socket?.readyState!==WebSocket.OPEN||!['listening_realtime','playing_realtime'].includes(this.state.state))return;if(this.socket.bufferedAmount>64000){void this.stop().catch(()=>{});return;}const amplified=Buffer.alloc(pcm.length);for(let i=0;i+1<pcm.length;i+=2)amplified.writeInt16LE(Math.max(-32768,Math.min(32767,pcm.readInt16LE(i)*8)),i);this.socket.send(amplified);}
 async stop(trigger='requested'){
  if(this.config.device_id&&!this.state.active)return this.state;
  this.lastStopTrigger=['requested','audio_socket_closed','readiness_playback_failed'].includes(trigger)?trigger:'requested';
  const revision=++this.revision,sessionId=this.state.session_id,socket=this.socket;
  try{
   const result=await this.request('/stop',{session_id:sessionId??undefined});
   if(revision===this.revision&&(!this.state.active||this.state.session_id===sessionId))this.apply(result);
  }finally{socket?.close();}
 }
 status(){return {...this.state,client_diagnostics:{last_stop_trigger:this.lastStopTrigger??null}};}
 close(){if(this.closed)return;clearTimeout(this.timer);if(this.state.active)void this.stop().catch(()=>{});this.closed=true;this.socket?.close();this.socket=null;}
}
