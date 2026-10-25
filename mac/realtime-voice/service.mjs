import {readFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {Rpc} from '../codex-service/rpc.mjs';
import {loadConfig} from '../codex-service/config.mjs';
import {playFarewell} from './farewell.mjs';
import {MediaChild} from './media-child.mjs';
import {RealtimeSession} from './session.mjs';
import {createControlServer} from './server.mjs';
import {featureConfig} from './install.mjs';
import {loadSpeakers} from '../../deploy/bridge/speakers.mjs';
import {loadPreset} from '../codex-service/preset.mjs';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..'),config=loadConfig();
let mode='diagnostic';try{const p=JSON.parse(readFileSync(resolve(root,'mac/realtime-voice/private/player.json')));if(p.mode==='managed')mode='managed';}catch{}
let limits={idle_seconds:60,max_session_seconds:900};try{limits=featureConfig(JSON.parse(readFileSync(resolve(root,'mac/unified-service/private/realtime-voice.json'))));}catch{}
const preset=loadPreset(),devices=loadSpeakers().devices.map(d=>d.id);
const session=new RealtimeSession({devices,farewell:device=>playFarewell(root,mode,device),model:preset.model,reasoningEffort:preset.reasoning_effort,voice:preset.voice,outputGain:preset.output_gain,outputBufferMs:preset.output_buffer_ms,idleSeconds:limits.idle_seconds,maxSeconds:limits.max_session_seconds,rpcFactory:()=>new Rpc({executable:config.executable,cwd:root}),mediaFactory:init=>new MediaChild({...init,player_mode:mode},{root}),key:config.admin_key});
const server=createControlServer({session,devices,key:config.admin_key,nativeStatus:async()=>{const r=await fetch('http://127.0.0.1:4417/status',{headers:{Authorization:'Bearer '+config.admin_key},signal:AbortSignal.timeout(2000)});if(!r.ok)throw Error('native unavailable');return r.json();}});
server.listen(4418,'127.0.0.1');
let stopping=false;const close=async()=>{if(stopping)return;stopping=true;await session.stop();server.close(()=>process.exit(0));};process.on('SIGTERM',close);process.on('SIGINT',close);
