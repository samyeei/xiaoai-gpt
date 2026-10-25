// Local, idle-only mode switch. Device/NAS endpoint rollback is separate.
import {readFileSync,writeFileSync,renameSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {validateSpeakers} from '../deploy/bridge/speakers.mjs';
const file=fileURLToPath(new URL('../config/speakers.json',import.meta.url));
const mode=process.argv[2];
if(!['single','multiple'].includes(mode))throw Error('Usage: node tools/set_speaker_mode.mjs single|multiple');
const previous=readFileSync(file,'utf8'),c=JSON.parse(previous);c.mode=mode;validateSpeakers(c);
const credentials=JSON.parse(readFileSync(new URL('../mac/codex-service/private/config.json',import.meta.url),'utf8'));
async function read(port,path){const r=await fetch(`http://127.0.0.1:${port}${path}`,{headers:{Authorization:'Bearer '+credentials.admin_key},signal:AbortSignal.timeout(3000)});if(!r.ok)throw Error('Service unavailable');return r.json();}
const [bridge,realtime,native]=await Promise.all([read(4398,'/health'),read(4418,'/status'),read(4417,'/status')]);
const voices=bridge.speakers??[bridge.voice];
if(bridge.pending||bridge.conversation_owner||realtime.active||native.active||voices.some(v=>!['idle','offline'].includes(v.state)))throw Error('Finish current conversation before switching');
function save(text){writeFileSync(file+'.tmp',text,{mode:0o644});renameSync(file+'.tmp',file);}
function restart(){for(const name of ['com.LOCAL_USER.xiaoai-realtime-voice','com.LOCAL_USER.xiaoai-unified'])execFileSync('launchctl',['kickstart','-k',`gui/${process.getuid()}/${name}`],{stdio:'ignore'});}
save(JSON.stringify(c,null,2)+'\n');
try{restart();}catch{save(previous);restart();throw Error('Mode switch failed; previous configuration restored');}
console.log(mode==='multiple'?'Two-speaker mode enabled; waiting for devices to reconnect.':'Original single-speaker entry enabled; only primary accepted.');
