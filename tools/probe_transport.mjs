import { SpeakerTransport } from '../deploy/bridge/speaker-transport.mjs';
import { writeFileSync } from 'node:fs';
import { Speaker } from '../deploy/bridge/controller.mjs';
const transport = new SpeakerTransport({port:4419});
let frames=0, bytes=0, peak=0, low16=0;
const playing=[];
transport.on('event',e=>{if(e.event==='playing')playing.push(e.data);});
transport.on('audio', data=>{
  frames++; bytes+=data.length;
  for(let i=0;i+4<=data.length;i+=4) {
    const n=data.readInt32LE(i); peak=Math.max(peak,Math.abs(n));
    if(n & 65535) low16++;
  }
});
const deadline=setTimeout(()=>{console.error('Probe connection timed out');void transport.close().then(()=>process.exit(1));},20000);
transport.on('connected',async()=>{
  try {
    const shell=await transport.run_shell('printf capture-probe',5000);
    await transport.startRecording();
    await new Promise(r=>setTimeout(r,4000));
    await transport.request('stop_recording',null);
    await new Speaker(transport).say('连接测试完成。');
    await new Promise(r=>setTimeout(r,3000));
    const report={real_client_rpc:shell,frames,bytes,peak_s32:peak,low16_nonzero:low16,playing};
    writeFileSync('artifacts/2026-10-06/hey-muse/transport-acceptance.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
    if(!frames||!bytes) throw new Error('No audio received');
    if(!playing.includes('Playing') || !playing.some(x=>x!=='Playing')) throw new Error('Playback events missing');
    clearTimeout(deadline); await transport.close();
  } catch(e) {console.error(e.message);clearTimeout(deadline);await transport.close();process.exitCode=1;}
});
