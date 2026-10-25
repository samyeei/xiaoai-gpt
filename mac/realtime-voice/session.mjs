import {randomUUID} from 'node:crypto';
import {EventEmitter} from 'node:events';
import {voiceCommandConfig} from '../../deploy/bridge/voice-mode.mjs';
import {createVoiceCommandClassifier,exitInstructions} from '../../deploy/bridge/voice-commands.mjs';
export class RealtimeSession extends EventEmitter {
 constructor({commandConfig=voiceCommandConfig,devices=['lx06-primary'],rpcFactory,mediaFactory,key,model,reasoningEffort,voice,outputGain=1,outputBufferMs=600,farewell,farewellWaitMs=10000,maxSeconds=900,idleSeconds=60,mediaConnectWaitMs=12000}){super();this.classifyCommand=createVoiceCommandClassifier(commandConfig);this.exitInstructions=exitInstructions(commandConfig);Object.assign(this,{devices,rpcFactory,mediaFactory,key,model,reasoningEffort,voice,outputGain,outputBufferMs,farewell,farewellWaitMs,maxSeconds,idleSeconds,mediaConnectWaitMs});this.current=null;this.lastError=null;this.lastStopReason=null;this.farewellPlayed=false;this.farewellSource=null;this.lastInputMetrics=null;this.lastOutputMetrics=null;this.lastRtpMetrics=null;this.lastReorderMetrics=null;this.lastOpusMetrics=null;this.setupDiagnostics=null;this.sessionHistory=[];this.startAttempts=0;}
 status(){const c=this.current;return {state:c?.state??'idle',active:!!c,session_id:c?.id??null,device_id:c?.device??null,media_connected:!!c?.connected,player_ready:!!c?.connected,input_metrics:c?.inputMetrics??this.lastInputMetrics,output_metrics:c?.outputMetrics??this.lastOutputMetrics,reorder_metrics:c?.reorderMetrics??this.lastReorderMetrics,rtp_metrics:c?.rtpMetrics??this.lastRtpMetrics,opus_metrics:c?.opusMetrics??this.lastOpusMetrics,media_metrics:c?.mediaMetrics??null,media_signals:c?.mediaSignals??[],last_stop_reason:this.lastStopReason,farewell_played:this.farewellPlayed,farewell_source:this.farewellSource,last_error:this.lastError,setup_diagnostics:this.setupDiagnostics,recent_sessions:this.sessionHistory,settings:{model:this.model??null,reasoning_effort:this.reasoningEffort??null,voice:this.voice??null,output_gain:this.outputGain,output_buffer_ms:this.outputBufferMs}};}
 publish(){this.emit('status',this.status());}
 async start(device){
  if(!this.devices.includes(device))throw Error('unknown_device');
  if(this.current){if(this.current.device!==device)throw Error('audio_busy');return this.status();}
  const c={id:randomUUID(),attempt:++this.startAttempts,device,state:'starting_realtime',started:false,connected:false,rpc:this.rpcFactory(),lastActivity:Date.now()};this.current=c;this.lastError=null;this.lastStopReason=null;this.farewellPlayed=false;this.farewellSource=null;this.lastInputMetrics=null;this.lastOutputMetrics=null;this.lastRtpMetrics=null;this.lastReorderMetrics=null;this.lastOpusMetrics=null;this.setupDiagnostics={started_at_ms:Date.now(),thread_ready:false,offer_sent:false,answer_received:false,server_started:false,media_connected:false,transport:{}};
  c.media=this.mediaFactory({device_id:device,key:this.key,session_id:c.id,output_gain:this.outputGain,output_buffer_ms:this.outputBufferMs});
  c.rpc.on('serverRequest',p=>c.rpc.reject(p.id));
  c.rpc.on('notification',p=>{if(this.current!==c||c.stopping)return;const v=p.params??{};
   if(p.method==='thread/realtime/started'){this.setupDiagnostics.server_started=true;c.started=true;this.check(c);}
   if(p.method==='thread/realtime/sdp'){this.setupDiagnostics.answer_received=true;c.media.send({op:'answer',sdp:v.sdp});this.check(c);}
   if(p.method==='thread/realtime/error')void this.fail(c,'realtime_error');
   if(p.method==='thread/realtime/closed'&&!c.ending)void this.stop(c.id,'server_closed');
   if(p.method==='thread/realtime/transcript/done'){
    c.lastActivity=Date.now();if(v.role==='user'&&this.classifyCommand(v.text)==='exit')this.requestExit(c);
   }
  });
  c.rpc.on('disconnected',()=>{if(!c.stopping)void this.fail(c,'rpc_disconnected');});
  c.media.on('event',e=>{if(this.current!==c||c.stopping)return;
   if(e.type==='offer'){this.setupDiagnostics.offer_sent=true;void c.rpc.request('thread/realtime/start',{threadId:c.thread,version:'v3',outputModality:'audio',...(this.voice?{voice:this.voice}:{}),transport:{type:'webrtc',sdp:e.sdp},includeStartupContext:false},30000).catch(()=>this.fail(c,'start_failed'));}
   if(e.type==='connected'){this.setupDiagnostics.media_connected=true;c.connected=true;this.check(c);}
   if(e.type==='transport_state'&&['peer','ice','dtls','signaling','answer_applied'].includes(e.stage)&&['new','checking','connecting','connected','completed','disconnected','failed','closed','stable','have-local-offer','have-remote-offer','ok'].includes(e.state))this.setupDiagnostics.transport[e.stage]=e.state;
   if(e.type==='candidate_summary'&&['local','remote'].includes(e.side)&&['host','srflx','relay','prflx','udp','tcp'].every(k=>Number.isInteger(e.counts?.[k])&&e.counts[k]>=0&&e.counts[k]<=512))this.setupDiagnostics.transport[e.side+'_candidates']=Object.fromEntries(['host','srflx','relay','prflx','udp','tcp'].map(k=>[k,e.counts[k]]));
   if(e.type==='transport_diagnostic'&&['commands','audio_reorder'].includes(e.phase)&&/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(e.exception_type??''))this.setupDiagnostics.transport[e.phase==='commands'?'command_exception':'audio_reorder_exception']=e.exception_type;
   if(c.ending&&(e.type==='playing'||e.type==='listening')){if(e.type==='playing')c.exitPlaybackStarted=true;else if(c.exitPlaybackStarted){this.farewellPlayed=true;this.farewellSource='realtime';void this.stop(c.id,'user_exit');}return;}
   if(e.type==='playing'||e.type==='listening'){c.state=e.type==='playing'?'playing_realtime':'listening_realtime';c.lastActivity=Date.now();this.publish();}
   if(e.type==='input_metrics'){const {type,...stats}=e;c.inputMetrics=stats;this.lastInputMetrics=stats;}
   if(e.type==='output_metrics'){const stats={};for(const k of ['frames','audio_ms','max_receive_gap_ms','receive_gaps_over_80ms','max_write_ms','receive_timeouts','player_starts','player_drains','player_underruns','timeline_gaps','timeline_gap_ms','timeline_resets'])if(Number.isFinite(e[k])&&e[k]>=0)stats[k]=e[k];c.outputMetrics=stats;this.lastOutputMetrics=stats;}
   if(e.type==='audio_nack'&&typeof e.negotiated==='boolean')this.setupDiagnostics.audio_nack=e.negotiated;
   if(e.type==='reorder_metrics'){c.reorderMetrics={};for(const k of ['reorder_received','reorder_delivered','reorder_skipped','reorder_late','reorder_resets','reorder_queued'])if(Number.isInteger(e[k])&&e[k]>=0)c.reorderMetrics[k]=e[k];this.lastReorderMetrics=c.reorderMetrics;}
   if(e.type==='rtp_metrics'){c.rtpMetrics={};for(const k of ['packets_received','packets_lost','jitter_samples'])if(Number.isInteger(e[k])&&e[k]>=0)c.rtpMetrics[k]=e[k];this.lastRtpMetrics=c.rtpMetrics;}
   if(e.type==='opus_metrics'){c.opusMetrics={};for(const k of ['fec_attempts','plc_samples','decoder_resets','decoded_frames'])if(Number.isInteger(e[k])&&e[k]>=0)c.opusMetrics[k]=e[k];this.lastOpusMetrics=c.opusMetrics;}
   if(e.type==='media_metrics')c.mediaMetrics={peak:e.peak,samples:e.samples,silent_samples:e.silent_samples};
   if(e.type==='media_signal'){c.mediaSignals??=[];c.mediaSignals.push(e);c.mediaSignals=c.mediaSignals.slice(-8);}
   if(e.type==='activity')c.lastActivity=Date.now();
   if(e.type==='error')void this.fail(c,['player_unavailable','audio_overflow','media_failed','bridge_disconnected'].includes(e.code)?e.code:'media_error');
  });
  c.media.on('exit',()=>{if(!c.stopping)void this.fail(c,'media_exit');});
  c.startTimeout=setTimeout(()=>this.fail(c,'startup_timeout'),40000);c.startTimeout.unref?.();
  c.limit=setTimeout(()=>void this.stop(c.id,'session_limit'),this.maxSeconds*1000);c.limit.unref?.();
  c.idle=setInterval(()=>{if(c.state==='listening_realtime'&&Date.now()-c.lastActivity>this.idleSeconds*1000)void this.stop(c.id,'idle_timeout');},1000);c.idle.unref?.();
  try{await c.rpc.ready();if(c.stopping)return this.status();const t=await c.rpc.request('thread/start',{...(this.model?{model:this.model}:{}),...(this.reasoningEffort?{config:{model_reasoning_effort:this.reasoningEffort}}:{}),ephemeral:true,sandbox:'read-only',approvalPolicy:'never',developerInstructions:'你在独立的中文音箱语音会话中。保持简洁，禁止调用工具或修改文件。'+this.exitInstructions},15000);if(this.model&&t.model!==this.model)throw Error('model_not_selected');if(this.reasoningEffort&&t.reasoningEffort!==this.reasoningEffort)throw Error('effort_not_selected');c.thread=t.thread.id;this.setupDiagnostics.thread_ready=true;if(!c.stopping)await c.media.start();}
  catch{await this.fail(c,'startup_failed');}
  return this.status();
 }
 check(c){
  if(this.current!==c||c.stopping)return;
  if(c.started&&this.setupDiagnostics.answer_received&&!c.connected&&!c.mediaTimeout){c.mediaTimeout=setTimeout(()=>void this.fail(c,'media_connect_timeout'),this.mediaConnectWaitMs);c.mediaTimeout.unref?.();}
  if(c.started&&c.connected&&c.state==='starting_realtime'){clearTimeout(c.startTimeout);clearTimeout(c.mediaTimeout);c.state='ready';this.publish();}
 }
 listen(id){const c=this.current;if(!c||c.id!==id||c.state!=='ready')throw Error('not_ready');c.media.send({op:'listen'});c.state='listening_realtime';c.lastActivity=Date.now();this.publish();return this.status();}
 requestExit(c){
  if(this.current!==c||c.stopping||c.ending)return;
  c.ending=true;c.exitPlaybackStarted=c.state==='playing_realtime';c.state='ending_realtime';c.media.send({op:'pause_input'});this.publish();
  c.exitTimeout=setTimeout(()=>{if(this.current!==c||c.stopping)return;if(c.exitPlaybackStarted)this.lastError='farewell_unconfirmed';void this.stop(c.id,'user_exit');},this.farewellWaitMs);c.exitTimeout.unref?.();
 }
 async fail(c,code){if(this.current!==c||c.stopping)return;this.lastError=code;await this.stop(c.id,'error:'+code);}
 async stop(id,reason='requested'){const c=this.current;if(!c)return this.status();if(id&&id!==c.id)throw Error('stale_session');if(c.cleanup)return c.cleanup;
  this.lastStopReason=reason;c.stopping=true;c.state='stopping';this.publish();clearTimeout(c.startTimeout);clearTimeout(c.limit);clearInterval(c.idle);clearTimeout(c.exitTimeout);clearTimeout(c.mediaTimeout);
  c.cleanup=(async()=>{try{await c.media.close();}catch{this.lastError??='cleanup_failed';}
   try{if(c.thread)await c.rpc.request('thread/realtime/stop',{threadId:c.thread},10000);}catch{this.lastError??='stop_unconfirmed';}
   try{if(reason==='user_exit'&&this.farewell&&!this.farewellPlayed&&!this.lastError){c.state='playing_farewell';this.publish();await this.farewell(c.device);this.farewellPlayed=true;this.farewellSource='fixed_fallback';}}catch{this.lastError??='farewell_failed';}
   finally{c.rpc.close();if(this.current===c){this.sessionHistory.push({attempt:c.attempt,reason,error:this.lastError,finished_at_ms:Date.now(),setup:{...this.setupDiagnostics},farewell_played:this.farewellPlayed});this.sessionHistory=this.sessionHistory.slice(-8);this.current=null;}this.publish();}return this.status();})();return c.cleanup;
 }
}
