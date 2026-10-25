import {readFileSync} from 'node:fs';
import {isAbsolute,resolve} from 'node:path';

const legacyLabels={
  native:'com.LOCAL_USER.xiaoai-native-voice',
  realtime:'com.LOCAL_USER.xiaoai-realtime-voice',
  unified:'com.LOCAL_USER.xiaoai-unified',
};

function privateIPv4(host){
  if(typeof host!=='string'||!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(host))return false;
  const [a,b,c,d]=host.split('.').map(Number);
  if([a,b,c,d].some(n=>n>255))return false;
  return a===10||(a===172&&b>=16&&b<=31)||(a===192&&b===168);
}

export function loadRuntime(root){
  const path=resolve(root,'mac/installer/private/runtime.json');
  let runtime;
  try{runtime=JSON.parse(readFileSync(path,'utf8'));}
  catch(error){
    if(error?.code==='ENOENT')return {node:process.execPath,bridge_host:undefined,labels:legacyLabels,muse_enabled:true};
    throw new Error('Invalid private runtime configuration',{cause:error});
  }
  const labels=runtime?.labels;
  const prefix=typeof labels?.native==='string'&&labels.native.match(/^org\.xiaoaigpt\.([a-z0-9-]+)\.native$/)?.[1];
  const expected=prefix&&{native:`org.xiaoaigpt.${prefix}.native`,realtime:`org.xiaoaigpt.${prefix}.realtime`,unified:`org.xiaoaigpt.${prefix}.unified`};
  if(runtime?.version!==1||typeof runtime.node!=='string'||!isAbsolute(runtime.node)||!privateIPv4(runtime.bridge_host)||runtime.muse_enabled!==false||
    !expected||Object.keys(labels).length!==3||Object.entries(expected).some(([key,value])=>labels[key]!==value)||
    Object.keys(runtime).sort().join(',')!=='bridge_host,labels,muse_enabled,node,version'){
    throw new Error('Invalid private runtime configuration');
  }
  return runtime;
}

export function unavailableMuseClient(){
  return {
    async health(){return {ready:false,state:'unavailable'};},
    async ask(){throw new Error('Muse unavailable');},
  };
}

export function deriveWakeConfig(config,museEnabled){
  if(museEnabled)return config;
  if(config?.version!==1||!Array.isArray(config.routes)||
    !config.routes.some(route=>route.backend==='codex'&&route.enabled===true)){
    throw new Error('Codex-only runtime requires an enabled Codex wake route');
  }
  return {...config,routes:config.routes.map(route=>route.backend==='muse'?{...route,enabled:false}:route)};
}
