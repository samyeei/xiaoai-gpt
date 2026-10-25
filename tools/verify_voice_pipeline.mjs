// Actual Python models + Node orchestration + real ESP32/Muse. Speaker playback is simulated.
import { EventEmitter } from 'node:events';
import { readFileSync, writeFileSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import { Controller } from '../deploy/bridge/controller.mjs';
import { MuseClient } from '../deploy/bridge/muse-client.mjs';
import { DirectVoice } from '../deploy/bridge/direct-voice.mjs';

function wav(path) {
  const data=readFileSync(path);
  let cursor=12;
  while(cursor+8<=data.length) {
    const length=data.readUInt32LE(cursor+4);
    if(data.toString('ascii',cursor,cursor+4)==='data') return data.subarray(cursor+8,cursor+8+length);
    cursor+=8+length+(length%2);
  }
  throw new Error('No PCM data');
}
const config=JSON.parse(readFileSync('deploy/config/bridge.json','utf8'));
config.voice_url='ws://127.0.0.1:4400';
const transport=new EventEmitter(); transport.socket={}; transport.startRecording=async()=>{};
let voice; const spoken=[];
const speaker={
  interrupt:async()=>{throw new Error('Direct mode restarted native XiaoAI');},
  say:async text=>{
    spoken.push(text); voice.onPlaying(true);
    setTimeout(()=>voice.onPlaying(false),200);
  },
};
const controller=new Controller(new MuseClient(config),speaker,config);
voice=new DirectVoice(transport,controller,speaker,config);
const until=async(fn,limit=15000)=>{
  const end=Date.now()+limit;
  while(!fn()){if(Date.now()>end)throw new Error('Pipeline state timeout: '+voice.state);await delay(50);}
};
async function feed(pcm) {
  for(let offset=0;offset<pcm.length;offset+=640) {
    const frame=pcm.subarray(offset,offset+640), s32=Buffer.alloc(frame.length*2);
    for(let i=0;i+2<=frame.length;i+=2)s32.writeInt32LE(frame.readInt16LE(i)<<16,i*2);
    transport.emit('audio',s32); await delay(20);
  }
}
try {
  await until(()=>voice.state==='idle');
  await feed(wav('artifacts/2026-10-06/hey-muse/hey-muse-reference.wav'));
  await feed(Buffer.alloc(32000));
  await until(()=>voice.state==='listening');
  await feed(wav('deploy/models/asr/test_wavs/zh.wav'));
  await feed(Buffer.alloc(48000));
  await until(()=>spoken.length===2,95000);
  await until(()=>voice.state==='idle');
  if(!spoken[1]?.trim()) throw new Error('No real Muse reply');
  const report={synthetic_wake:true,local_asr:true,real_esp32_muse_reply:true,
    speaker_playback:'simulated',human_far_field:'pending',status:voice.status(),reply_characters:spoken[1].length};
  writeFileSync('artifacts/2026-10-06/hey-muse/pipeline-acceptance.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} finally {voice.close();controller.cancel();}
