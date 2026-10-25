import { dirname, resolve } from 'node:path';
import { Rpc } from './rpc.mjs';
import { CodexService } from './service.mjs';
import { createEndpoints } from './http.mjs';
import { defaultConfig, initializeConfig, loadConfig } from './config.mjs';
import { execFileSync } from 'node:child_process';
import {loadPreset} from './preset.mjs';

if(process.argv[2]==='init') {
  const path=initializeConfig(process.argv[3] ?? '127.0.0.1');console.log('Private configuration created:',path);
} else if(process.argv[2]==='copy-control-key') {
  execFileSync('/usr/bin/pbcopy',[],{input:loadConfig().admin_key});console.log('Local control key copied to clipboard');
} else {
  const configPath=process.env.CODEX_VOICE_CONFIG ?? defaultConfig;
  const config=loadConfig(configPath),preset=loadPreset(),rpc=new Rpc({executable:config.executable,cwd:config.cwd});
  const service=new CodexService({rpc,cwd:config.cwd,model:preset.model,reasoningEffort:preset.single_reasoning_effort,stateFile:resolve(dirname(configPath),'state.json')});
  let endpoints,stopping=false;
  const stop=async()=>{
    if(stopping)return;stopping=true;
    for(const id of service.jobs.keys())try{await service.cancel(id);}catch{}
    service.close();rpc.close();
    for(const server of Object.values(endpoints ?? {})){server.closeAllConnections();server.close();}
  };
  process.on('SIGINT',()=>{void stop();});process.on('SIGTERM',()=>{void stop();});
  service.on('unavailable',()=>{
    if(stopping)return;
    console.error('Codex disconnected; service restart required');process.exitCode=1;void stop();
  });
  try{
    await service.start();
    endpoints=createEndpoints({service,key:config.key,adminKey:config.admin_key,host:process.env.XIAOAI_UNIFIED==='1'?'127.0.0.1':config.host,port:config.port,controlPort:config.control_port,unified:process.env.XIAOAI_UNIFIED==='1'});
    for(const server of Object.values(endpoints))server.on('error',()=>{console.error('HTTP listener unavailable; check address and ports');process.exitCode=1;void stop();});
    console.log(`Codex voice service: ${config.host}:${config.port}; local control: http://127.0.0.1:${config.control_port}`);
  }catch(error){console.error('Codex voice startup failed:',error.message);process.exitCode=1;await stop();}
}
