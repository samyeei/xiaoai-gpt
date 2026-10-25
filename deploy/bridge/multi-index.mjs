// Opt-in two-speaker entry. The original index.mjs remains the single rollback.
import {readFileSync} from 'node:fs';
import {createServer} from 'node:http';
import {loadSpeakers} from './speakers.mjs';
import {SpeakerHub} from './speaker-hub.mjs';
import {ConversationLease} from './conversation-lease.mjs';
import {LocalMuseClient} from './local-muse-client.mjs';
import {CodexClient} from './codex-client.mjs';
import {Controller,Speaker,recognizedText} from './controller.mjs';
import {DirectVoice} from './direct-voice.mjs';
import {nativeWake} from './speaker-transport.mjs';
import {dispatchNativeText} from './native-commands.mjs';
import {calibrationControl} from './calibration-control.mjs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadRuntime,unavailableMuseClient} from '../../mac/runtime-config.mjs';

const runtime=loadRuntime(resolve(dirname(fileURLToPath(import.meta.url)),'../..'));
const registry=loadSpeakers(),config=JSON.parse(readFileSync(process.env.BRIDGE_CONFIG,'utf8'));
if(registry.mode!=='multiple'||config.native_voice)throw Error('Invalid multi-speaker mode');
const lease=new ConversationLease(),pipelines=new Map();
// On bridge recovery reserve an already-active session before accepting wakes.
let recovery=null,recoveryToken=null;
if(config.realtime_voice){
 const r=await fetch('http://127.0.0.1:4418/status',{headers:{Authorization:'Bearer '+config.realtime_voice.key},signal:AbortSignal.timeout(5000)});
 if(!r.ok)throw Error('Realtime recovery unavailable');
 const s=await r.json();if(typeof s.active!=='boolean')throw Error('Invalid recovery state');
 if(s.active){if(!registry.devices.some(d=>d.id===s.device_id))throw Error('Unknown active device');recovery=s.device_id;recoveryToken=lease.acquire(recovery);}
}
const hub=new SpeakerHub({devices:registry.devices,host:runtime.bridge_host??process.env.BRIDGE_HOST??'0.0.0.0'});
for(const device of registry.devices){
 const native=hub.devices.get(device.id),muse=runtime.muse_enabled?new LocalMuseClient(config.muse):unavailableMuseClient(),codex=new CodexClient(config.codex);
 const controller=new Controller(muse,new Speaker(native),config,codex);
 const voice=new DirectVoice(native,controller,controller.speaker,{
  ...config,device_id:device.id,conversation_lease:lease,conversation_token:device.id===recovery?recoveryToken:null,
  voice_url:`ws://127.0.0.1:${device.id==='lx06-primary'?4400:4401}`,
  ...(config.realtime_voice?{realtime_voice:{...config.realtime_voice,device_id:device.id}}:{})
 });
 const pipeline={device,native,controller,voice,lastEvent:null};pipelines.set(device.id,pipeline);
 native.on('event',event=>{
  pipeline.lastEvent=Date.now();
  if(event.event==='playing'){controller.onPlaying(event.data==='Playing');voice.onPlaying(event.data==='Playing');}
  // A native wake affects only the matching speaker's own realtime session.
  if(voice.realtime?.state.active&&nativeWake(event))void voice.nativeInterrupt().catch(()=>{});
  if(lease.owner&&lease.owner!==device.id)return;
  if(!voice.nativeBlocked()&&(nativeWake(event)||recognizedText(event)))voice.nativePriority();
  const text=recognizedText(event);
  if(text)void dispatchNativeText(voice,controller,text).catch(()=>console.error('Device native command failed'));
 });
}
const primary=pipelines.get('lx06-primary');
const health=createServer((req,res)=>{
 if(req.url==='/calibrate'){void calibrationControl(req,res,primary.voice,config.calibration_key);return;}
 if(req.method!=='GET'||req.url!=='/health'){res.writeHead(404);res.end();return;}
 const speakers=[...pipelines.values()].map(p=>({device_id:p.device.id,ip:p.device.ip,...p.voice.status()}));
 res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});
 res.end(JSON.stringify({service:'xiaoai-muse',speaker_mode:'multiple',...primary.controller.status(),
  last_speaker_event:primary.lastEvent,conversation_owner:lease.owner,speakers,
  voice:{...primary.voice.status(),models_ready:speakers.every(s=>s.models_ready)},
  realtime_voice:primary.voice.realtime?.status()??null,native_voice:null,audio_mirror:{connected:false}
 }));
});
health.listen(4398,process.env.BRIDGE_HEALTH_HOST??'127.0.0.1');
let closing=false;
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{
 if(closing)return;closing=true;
 for(const p of pipelines.values()){p.controller.cancel();p.voice.close();}
 health.close();void hub.close();setTimeout(()=>process.exit(0),4500).unref();
});
console.log('Two-speaker bridge starting; one conversation at a time');
