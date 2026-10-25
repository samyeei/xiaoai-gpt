import { WebSocket } from 'ws';
import { NativeVoiceClient } from './native-voice-client.mjs';
import {RealtimeClient} from './realtime-client.mjs';
import {classifyVoiceCommand} from './voice-mode.mjs';
import {loadWakeRoutes} from './wake-routes.mjs';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';

export class DirectVoice {
  constructor(transport, controller, speaker, config) {
    this.transport = transport; this.controller = controller; this.speaker = speaker;
    this.wakeRoutes = loadWakeRoutes();
    this.lease=config.conversation_lease;this.leaseToken=config.conversation_token;this.deviceId=config.device_id??'lx06-primary';
    this.url = config.voice_url ?? 'ws://voice:4400';
    this.state = 'offline'; this.session = null; this.worker = null; this.closed = false;
    this.metrics = {}; this.lastError = null; this.remainder = Buffer.alloc(0);
    this.generation = 0; this.playing = false; this.playRevision = 0; this.playStarts = 0;
    transport.on('audio', data => this.audio(data));
    transport.on('connected', () => { this.remainder = Buffer.alloc(0); void this.record(); });
    transport.on('disconnected', () => { this.cancel(); this.lastError = 'Speaker disconnected'; });
    controller.progressPlayback = action => {
      const generation = this.generation;
      return this.playback(generation, action);
    };
    this.nativeVoice = config.native_voice ? new NativeVoiceClient(config.native_voice) : null;
    if (this.nativeVoice) {
      transport.on('audio', data => this.nativeVoice.audio(data));
      this.nativeVoice.onState = status => this.nativeState(status);
      this.nativeVoice.onReady = status => void this.nativeReady(status);
    }
    this.realtime = config.realtime_voice ? new RealtimeClient(config.realtime_voice) : null;
    if(this.realtime){this.realtime.onState=s=>this.realtimeState(s);this.realtime.onReady=s=>void this.realtimeReady(s);}
    this.connect();
  }
  nativeState(status) {
    if (this.closed) return;
    if (status.blocked || this.nativePhase === 'prompting') {
      this.state = 'native'; this.send({type:'pause'}); return;
    }
    const failedBeforeReady = this.nativeRequested && status.available && !status.active && ['failed','idle'].includes(status.state);
    this.nativeRequested = false; this.nativePhase = null;
    if (this.state === 'native') {
      this.state = 'idle';
      this.send({type:this.playing ? 'pause' : 'arm'});
      if (failedBeforeReady) void this.playback(this.generation, () => this.speaker.say('音频未接通，请检查诊断连接。')).catch(() => {});
    }
  }
  nativeBlocked() { return !!this.singleRequested || !!this.realtimeRequested || !!this.nativeRequested || !!this.nativeVoice?.blocked() || !!this.realtime?.blocked() || this.state==='calibrating'; }
  realtimeState(s){
    if(this.closed)return;
    if(this.realtimeRequested&&!s.active)return;
    const setup=s.setup_diagnostics;
    if(!s.active&&this.state==='realtime'&&this.realtimeRetryLeft>0&&['media_connect_timeout','startup_timeout'].includes(s.last_error)&&s.last_stop_reason==='error:'+s.last_error&&setup?.thread_ready&&setup.offer_sent&&setup.answer_received&&setup.server_started&&!setup.media_connected){
      this.realtimeRetryLeft=0;this.realtimeRequested=true;this.send({type:'pause'});
      void this.retryRealtime(this.generation);return;
    }
    if(s.active){this.state='realtime';this.send({type:'pause'});}
    else if(this.state==='realtime'){
      this.realtimeRetryLeft=0;
      if(s.last_error&&this.lease){
        // Keep ownership through the failure announcement, too.
        this.state='prompting';const generation=this.generation;
        void this.playback(generation,()=>this.speaker.say('语音连接失败，请稍后再试。')).catch(()=>{}).finally(()=>{
          if(generation===this.generation){this.state='idle';this.releaseIfIdle();this.send({type:this.playing?'pause':'arm'});}
        });
      }else{
        this.state='idle';this.releaseIfIdle();this.send({type:this.playing?'pause':'arm'});
        if(s.last_error)void this.playback(this.generation,()=>this.speaker.say('语音连接失败，请稍后再试。')).catch(()=>{});
      }
    }
    this.releaseIfIdle();
  }
  async retryRealtime(generation){
    try{
      await this.playback(generation,()=>this.speaker.say('音频连接较慢，正在重新连接。'),10000);
      if(this.closed||generation!==this.generation)return;
      if(!await this.realtime.start()){
        this.realtimeRequested=false;this.cancel();
        await this.playback(this.generation,()=>this.speaker.say('语音连接失败，请稍后再试。'));
      }
    }catch{if(!this.closed&&generation===this.generation){this.lastError='Realtime reconnect failed';this.realtimeRequested=false;this.cancel();}}
    finally{this.realtimeRequested=false;this.releaseIfIdle();}
  }
  async realtimeReady(s){
    const generation=this.generation;
    try{await this.playback(generation,()=>this.speaker.say('可以开始了。'),10000);await delay(400);
      if(generation===this.generation&&this.realtime?.state.session_id===s.session_id)await this.realtime.enable(s);
    }catch{
      if(this.realtime?.state.session_id===s.session_id){
        this.lastError='Realtime readiness playback failed';
        await this.realtime.stop('readiness_playback_failed').catch(()=>{});
      }
    }
  }
  status() { return {state:this.state, speaker_connected:!!this.transport.socket, ...this.metrics, native_commands:this.nativeCommands??null, last_error:this.lastError}; }
  send(packet) { if (this.worker?.readyState === WebSocket.OPEN) this.worker.send(JSON.stringify(packet)); }
  async record() {
    try { await this.transport.startRecording(); this.lastError = null; }
    catch { this.lastError = 'Shared capture failed'; }
  }
  connect() {
    if (this.closed) return;
    const socket = new WebSocket(this.url, { maxPayload: 65536 }); this.worker = socket;
    socket.on('error', () => {});
    socket.on('open', () => { this.state = this.nativeVoice?.blocked() ? 'native' : 'idle'; this.send({type:this.playing || this.nativeBlocked() ? 'pause' : 'arm'}); if (this.transport.socket) void this.record(); });
    socket.on('message', raw => {
      try {
        const packet = JSON.parse(raw.toString());
        if (packet.type === 'metrics') {this.metrics = packet.data;this.calibrationState(packet.data);}
        else if (packet.type === 'wake' && this.state === 'idle' && !this.controller.current && !this.playing) void this.wake(packet.keyword);
        else if (packet.type === 'text' && packet.session === this.session && this.state === 'listening') void this.answer(packet.text);
        else if (packet.type === 'timeout' && packet.session === this.session) this.cancel();
        else if (packet.type === 'error') { this.lastError = 'Voice worker error'; this.cancel(); }
      } catch { this.lastError = 'Invalid voice packet'; }
    });
    socket.on('close', () => {
      this.cancel();
      this.state = 'offline';
      this.lastError = 'Voice worker disconnected';
      if (!this.closed) this.retry = setTimeout(() => this.connect(), 3000);
    });
  }
  audio(data) {
    const w = this.worker;
    if (w?.readyState !== WebSocket.OPEN || (this.nativeBlocked() && !this.realtime?.state?.active && this.state!=='calibrating')) return;
    if (w.bufferedAmount > 128000) { this.lastError = 'Audio backpressure'; this.cancel(); w.close(); return; }
    const raw = Buffer.concat([this.remainder, data]);
    const count = Math.floor(raw.length / 4), pcm = Buffer.allocUnsafe(count * 2);
    // LX06 ALSA plug provides left-aligned S32. A real capture verified low 16 bits are zero.
    for (let i = 0; i < count; i++) pcm.writeInt16LE(raw.readInt32LE(i * 4) >> 16, i * 2);
    this.remainder = Buffer.from(raw.subarray(count * 4));
    if (pcm.length) {if(this.realtime?.state?.active)this.realtime.audio(pcm);else w.send(pcm);}
  }
  onPlaying(value) {
    if (value) this.playStarts++;
    this.playing = value; this.playRevision++;
    // Suppress acoustic self-triggering. Music must be paused before Hey Muse in phase one.
    if (this.state === 'idle') this.send({type:value || this.nativeBlocked() ? 'pause' : 'arm'});
  }
  cancelDirect() {
    if (this.session) { this.controller.cancel(); this.controller.mode = false; this.session = null; }
  }
  claimConversation(){
    if(!this.lease)return true;
    if(this.leaseToken)return this.lease.owner===this.deviceId;
    this.leaseToken=this.lease.acquire(this.deviceId);return !!this.leaseToken;
  }
  releaseIfIdle(){
    if(this.leaseToken&&['idle','offline'].includes(this.state)&&!this.singleRequested&&!this.realtimeRequested&&!this.nativeRequested&&!this.realtime?.blocked()){
      this.lease.release(this.deviceId,this.leaseToken);this.leaseToken=null;
    }
  }
  cancel() {
    this.realtimeRetryLeft=0;
    if(this.realtime?.state?.active)void this.realtime.stop().catch(()=>{});
    this.cancelDirect();
    this.generation++; this.session = null;
    this.state = this.realtime?.blocked() ? 'realtime' : this.nativeVoice?.blocked() ? 'native' : this.worker?.readyState === WebSocket.OPEN ? 'idle' : 'offline';
    this.releaseIfIdle();
    this.send({type:this.playing || this.nativeBlocked() ? 'pause' : 'arm'});
  }
  nativePriority() {
    if (this.nativeBlocked()) return;
    // Preserve the previously working native-wake Muse conversation mode.
    this.cancelDirect();
    this.cancel();
  }
  async playback(generation, action, limit = 60000) {
    const initial = this.playStarts;
    await action();
    const started = Date.now();
    while (generation === this.generation) {
      if (this.playStarts > initial && !this.playing) return;
      if (this.playStarts === initial && Date.now()-started > 6000) throw new Error('No playback confirmation');
      if (Date.now()-started > limit) throw new Error('Playback timeout');
      await delay(100);
    }
  }
  calibrationState(data){if(this.state==='calibrating'&&data.worker_state==='idle'&&data.calibration?.calibration_id===this.calibrationSession&&data.calibration.calibration_complete)this.state='idle';}
  calibrate(){if(this.state!=='idle'||this.playing||this.controller.current||this.nativeBlocked())return false;this.state='calibrating';this.calibrationSession=randomUUID();this.send({type:'calibrate',session:this.calibrationSession});return true;}
  async wake(keyword,{singleQuestion=false}={}) {
    const backend = (this.wakeRoutes ?? loadWakeRoutes()).get(keyword);
    if (!backend) return;
    if (this.nativeRequested || this.nativeVoice?.blocked() || this.realtime?.blocked()) return;
    if(!this.claimConversation()){this.send({type:'arm'});return;}
    if (backend === 'codex' && this.nativeVoice && !singleQuestion) {
      this.state = 'native'; const generation = ++this.generation;
      this.nativeRequested = true; this.nativePhase = 'prompting'; this.send({type:'pause'});
      try {
        await this.playback(generation, () => this.speaker.say('我在，正在接通音频。'), 10000);
        if (generation !== this.generation) { this.nativeRequested = false; this.nativePhase = null; this.nativeState(this.nativeVoice.status()); return; }
        this.nativePhase = 'waiting';
        const started = await this.nativeVoice.start();
        if (!started && !this.nativeVoice.blocked()) {
          this.nativeRequested = false; this.nativePhase = null;
          await this.playback(generation, () => this.speaker.say('音频未接通，请检查诊断连接。'), 10000);
          this.cancel();
        }
      } catch { this.nativeRequested = false; this.nativePhase = null; this.cancel(); }
      return;
    }
    this.backend = backend;
    this.state = 'prompting'; const generation = ++this.generation;
    this.session = randomUUID(); this.send({type:'pause'});
    try {
      await this.playback(generation, () => this.speaker.say(this.realtime&&backend==='codex'?'我在。':'我在，请说。'), 10000);
      if (generation !== this.generation) return;
      await delay(400);
      if (generation !== this.generation) return;
      this.state = 'listening'; this.send({type:'listen', session:this.session});
    } catch (e) { this.lastError = e.message; if (generation === this.generation) this.cancel(); }
  }
  async nativeReady(status) {
    if (!this.nativeRequested) return;
    this.nativeRequested = false; this.nativePhase = 'ready';
    const generation = this.generation;
    try {
      await this.playback(generation, () => this.speaker.say('音频已接通，请按原生语音快捷键。'), 10000);
      await delay(400);
      if (generation === this.generation) this.nativeVoice.enableMirror(status);
    } catch { this.lastError = 'Readiness playback failed'; }
  }
  async nativeInterrupt() {
    if(this.nativeStopPromise)return this.nativeStopPromise;
    if(!this.realtime?.state?.active)return false;
    this.realtimeRetryLeft=0;this.realtimeRequested=false;
    const generation=++this.generation;this.send({type:'pause'});
    this.nativeStopPromise=(async()=>{
      try{await this.realtime.stop();return true;}
      finally{if(this.generation===generation){this.state='idle';this.releaseIfIdle();this.send({type:this.playing?'pause':'arm'});}this.nativeStopPromise=null;}
    })();
    return this.nativeStopPromise;
  }
  async onNativeText(text) {
    this.nativeCommands??={final_count:0,entry_count:0,last_entry_at_ms:null,last_result:null};
    this.nativeCommands.final_count++;
    if(classifyVoiceCommand(text)==='single'){
      if(this.nativeBlocked()||this.singleRequested)return true;
      const keyword=[...(this.wakeRoutes??loadWakeRoutes())].find(([,backend])=>backend==='codex')?.[0];
      if(!keyword)return false;
      if(!this.claimConversation())return true;
      this.singleRequested=true;this.cancelDirect();this.state='prompting';
      const generation=++this.generation;this.send({type:'pause'});
      try{
        await this.speaker.interrupt();
        if(generation!==this.generation||this.closed)return true;
        await this.wake(keyword,{singleQuestion:true});
      }catch{this.lastError='Native single-question entry failed';if(generation===this.generation)this.cancel();}
      finally{this.singleRequested=false;this.releaseIfIdle();if(this.state==='idle')this.send({type:this.playing?'pause':'arm'});}
      return true;
    }
    if(classifyVoiceCommand(text)==='exit'&&this.realtime?.state?.active)return this.nativeInterrupt();
    if(classifyVoiceCommand(text)!=='enter'||!this.realtime||this.nativeBlocked())return false;
    if(!this.claimConversation())return true;
    this.nativeCommands.entry_count++;this.nativeCommands.last_entry_at_ms=Date.now();
    this.realtimeRetryLeft=1;this.realtimeRequested=true;this.cancelDirect();this.state='realtime';
    const generation=++this.generation;this.send({type:'pause'});
    try {
      await this.speaker.interrupt();
      if(generation!==this.generation||this.closed)return true;
      await this.playback(generation,()=>this.speaker.say('正在连接连续语音，请稍候。'),10000);
      if(generation!==this.generation||this.closed)return true;
      const started=await this.realtime.start();
      this.nativeCommands.last_result=started?'accepted':'failed';
      if(!started){
        try{await this.playback(generation,()=>this.speaker.say('语音暂时无法连接，请稍后再试。'));}
        finally{this.realtimeRequested=false;this.cancel();}
      }
    }catch{this.nativeCommands.last_result='failed';this.lastError='Native continuous entry failed';this.realtimeRequested=false;this.cancel();}
    finally{this.realtimeRequested=false;this.releaseIfIdle();}
    return true;
  }
  async answer(text) {
    if (this.nativeBlocked()) return;
    if (typeof text !== 'string' || !text.trim()) { this.cancel(); return; }
    if(this.backend==='codex'&&this.realtime){
      const command=classifyVoiceCommand(text);
      if(command==='exit'){this.cancel();return;}
    }
    this.state = 'answering'; const generation = this.generation;
    this.send({type:'pause'});
    try {
      await this.controller.onDirectText(text, this.backend);
      if (generation !== this.generation) return;
      // Controller completes only after confirmed final playback. Keep a tail for room echo.
      await delay(600);
      if (generation === this.generation) this.cancel();
    } catch { this.lastError = 'Direct voice request failed'; if (generation === this.generation) this.cancel(); }
  }
  close() { this.closed = true; clearTimeout(this.retry); this.cancel(); this.worker?.terminate(); this.nativeVoice?.close(); this.realtime?.close(); }
}
