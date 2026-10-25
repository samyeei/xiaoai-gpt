// Restore existing local voice jobs without restarting an active conversation.
import {spawnSync} from 'node:child_process';
import {readFileSync,existsSync} from 'node:fs';
import {homedir} from 'node:os';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline/promises';
import {loadVoiceCommands} from '../deploy/bridge/voice-commands.mjs';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const domain='gui/'+process.getuid();
const jobs=[['com.LOCAL_USER.xiaoai-native-voice','音频转接'],['com.LOCAL_USER.xiaoai-realtime-voice','连续语音'],['com.LOCAL_USER.xiaoai-unified','唤醒和问答']];
function run(args){return spawnSync('/bin/launchctl',args,{stdio:'ignore',timeout:10000}).status===0;}
async function status(port,path,key=''){
 const response=await fetch(`http://127.0.0.1:${port}${path}`,{headers:key?{Authorization:'Bearer '+key}:{},signal:AbortSignal.timeout(2000)});
 if(!response.ok)throw Error('not_ready');return response.json();
}
async function main(){
 const commands=loadVoiceCommands();
 console.log('正在检查小爱语音服务……');
 for(const [label,name] of jobs){
  const target=domain+'/'+label;
  if(!run(['enable',target]))throw Error(name+'服务未能启动，请把这个窗口的结果告诉 Codex。');
  if(!run(['print',target])){
   const file=resolve(homedir(),'Library/LaunchAgents',label+'.plist');
   if(!existsSync(file)||!run(['bootstrap',domain,file]))throw Error(name+'服务未能启动，请把这个窗口的结果告诉 Codex。');
  }
  // No -k: kickstart starts a stopped job and leaves a running job untouched.
  if(!run(['kickstart',target]))throw Error(name+'服务未能启动，请把这个窗口的结果告诉 Codex。');
 }
 const {admin_key}=JSON.parse(readFileSync(resolve(root,'mac/codex-service/private/config.json'),'utf8'));
 let observed=null;
 for(let attempt=0;attempt<20;attempt++){
  try{
   const [bridge,realtime,manager,native]=await Promise.all([status(4398,'/health'),status(4418,'/status',admin_key),status(4413,'/status',admin_key),status(4417,'/status',admin_key)]);
   observed={bridge,realtime,manager,native};
   if(bridge.voice?.models_ready&&manager.codex?.ready){
    console.log('Mac 语音服务已就绪。');
    if(manager.codex.model)console.log(`默认问答：${manager.codex.model}，推理强度 ${manager.codex.reasoning_effort??'默认'}。`);
    if(realtime.settings?.voice)console.log(`连续人声：${realtime.settings.voice}，播放增益 ${realtime.settings.output_gain} 倍。`);
    if(realtime.active||native.active)console.log('当前语音通话保持运行。');
    if(bridge.speakers)for(const speaker of bridge.speakers)console.log(`音箱 ${speaker.ip}：${speaker.speaker_connected?'已连接':'未连接'}。`);
    if(bridge.speakers?bridge.speakers.some(s=>s.speaker_connected):bridge.voice.speaker_connected){
     const wakeConfig=JSON.parse(readFileSync(resolve(root,'config/wake-words.json'),'utf8'));
     const wake=wakeConfig.routes.find(r=>r.enabled&&r.backend==='codex')?.phrases[0];
     console.log('音箱已连接。');
     if(wake)console.log(`单次唤醒：“${wake}”。`);
     if(commands.single.length)console.log(`单次口令：说“小爱同学”，等回应后说“${commands.single[0]}”。`);
     if(commands.continuous.length)console.log(`连续语音：说“小爱同学”，等回应后说“${commands.continuous[0]}”。`);
     console.log(`结束时说“${commands.exit[0]}”。`);
    }else console.log('音箱暂未连接：请确认音箱已通电，且与 Mac 在同一网络。');
    return;
   }
  }catch{}
  if(attempt===0)console.log('正在等待语音模型加载……');
  await new Promise(r=>setTimeout(r,1000));
 }
 console.log(observed?'服务已启动，但语音模型或问答仍未就绪。':'服务未能正常响应。');
 console.log('请把这个窗口的结果告诉 Codex，先不要重复重启音箱。');process.exitCode=1;
}
try{await main();}catch(error){console.log(error.message.includes('服务未能启动')?error.message:'启动检查未完成，请把这个窗口的结果告诉 Codex。');process.exitCode=1;}
if(process.stdin.isTTY){const terminal=createInterface({input:process.stdin,output:process.stdout});await terminal.question('\n按回车关闭本次检查。');terminal.close();}
