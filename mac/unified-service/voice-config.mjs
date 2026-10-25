import {nativeWakeOptIn} from '../../deploy/bridge/native-voice-client.mjs';
import {realtimeOptIn} from '../../deploy/bridge/realtime-client.mjs';
import {featureConfig} from '../realtime-voice/install.mjs';
export function asrWakeTestEnv(flag,now=Date.now()/1000){
 if(!flag || Array.isArray(flag) || Object.keys(flag).some(k=>!['enabled','expires_at'].includes(k)) || flag.enabled!==true || !Number.isFinite(flag.expires_at) || flag.expires_at<=now || flag.expires_at>now+1200)return {};
 return {ASR_WAKE_TEST_EXPIRES_AT:String(flag.expires_at)};
}
export function configureVoiceFlags(bridge,{nativeFlag,realtimeFlag},key){const result={...bridge};delete result.native_voice;delete result.realtime_voice;let realtime=null;try{realtime=realtimeOptIn(featureConfig(realtimeFlag),key);}catch{}if(realtime){result.realtime_voice=realtime;delete result.native_audio_url;delete result.native_audio_expires_at;}else{const native=nativeWakeOptIn(nativeFlag,key);if(native)result.native_voice=native;}return result;}

export function asrWakeEnv(flag){
 if(!flag || Array.isArray(flag) || Object.keys(flag).some(k=>k!=='enabled') || flag.enabled!==true)return {};
 return {ASR_WAKE_ENABLED:'1'};
}
