import {dispatchNativeText} from './native-commands.mjs';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { MuseClient } from './muse-client.mjs';
import { LocalMuseClient } from './local-muse-client.mjs';
import { CodexClient } from './codex-client.mjs';
import { Controller, Speaker, recognizedText } from './controller.mjs';
import { SpeakerTransport, nativeWake } from './speaker-transport.mjs';
import { DirectVoice } from './direct-voice.mjs';
import {calibrationControl} from './calibration-control.mjs';
import { AudioMirror } from './audio-mirror.mjs';
import {loadSpeakers} from './speakers.mjs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadRuntime,unavailableMuseClient} from '../../mac/runtime-config.mjs';

const runtime=loadRuntime(resolve(dirname(fileURLToPath(import.meta.url)),'../..'));
const config = JSON.parse(readFileSync(process.env.BRIDGE_CONFIG ?? '/app/config/bridge.json', 'utf8'));
const directEnabled = process.env.HEY_MUSE === '1';
const native = directEnabled ? new SpeakerTransport({host:runtime.bridge_host ?? process.env.BRIDGE_HOST ?? '0.0.0.0',allowedIP:loadSpeakers().devices.find(d=>d.id==='lx06-primary').ip}) : createRequire(import.meta.url)('/app/migpt/open-xiaoai.node');
const muse = !runtime.muse_enabled ? unavailableMuseClient() : config.muse ? new LocalMuseClient(config.muse) : new MuseClient(config);
let codex = null;
try { if (config.codex) codex = new CodexClient(config.codex); }
catch { console.log('Codex configuration unavailable; Muse remains active'); }
const controller = new Controller(muse, new Speaker(native), config, codex);
const voice = directEnabled ? new DirectVoice(native, controller, controller.speaker, config) : null;
const audioMirror = new AudioMirror(directEnabled && !config.native_voice ? config : {});
const mirrorAudio = data => audioMirror.audio(data);
if (directEnabled && !config.native_voice && config.native_audio_url) native.on('audio', mirrorAudio);
let lastEvent = null;
globalThis.RUST_CALLBACKS = {
  on_event: event => {
    lastEvent = Date.now();
    try {
      const e = JSON.parse(event);
      if (e.event === 'playing') { controller.onPlaying(e.data === 'Playing'); voice?.onPlaying(e.data === 'Playing'); }
      if(voice?.realtime?.state?.active && nativeWake(e))void voice.nativeInterrupt().catch(()=>console.error('Native realtime stop failed'));
      if (voice && !voice.nativeBlocked() && (nativeWake(e) || recognizedText(e))) voice.nativePriority();
    } catch { /* malformed events are ignored */ }
    const text = recognizedText(event);
    if(text)void dispatchNativeText(voice,controller,text).catch(()=>console.error('Native command processing failed'));
  },
  on_input_data: () => {},
};
if (directEnabled) native.on('event', e => globalThis.RUST_CALLBACKS.on_event(JSON.stringify(e)));
const health = createServer((request, response) => {
  if(request.url==='/calibrate'){void calibrationControl(request,response,voice,config.calibration_key);return;}
  if (request.method !== 'GET' || request.url !== '/health') { response.writeHead(404); response.end(); return; }
  response.setHeader('Content-Type', 'application/json');
  response.setHeader('Cache-Control', 'no-store');
  response.end(JSON.stringify({ service: 'xiaoai-muse', ...controller.status(), last_speaker_event: lastEvent, audio_mirror: audioMirror.status(), native_voice: voice?.nativeVoice?.status() ?? null, realtime_voice: voice?.realtime?.status() ?? null, ...(voice ? {voice:voice.status()} : {}) }));
});
health.listen(4398, process.env.BRIDGE_HEALTH_HOST ?? '0.0.0.0');
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
  if (directEnabled) native.off('audio', mirrorAudio); audioMirror.close(); controller.cancel(); voice?.close(); if (directEnabled) void native.close(); health.close(); setTimeout(() => process.exit(0), 4500).unref();
});
console.log('XiaoAI Muse bridge starting: speaker port 4399, health port 4398');
if(runtime.muse_enabled){
 try { console.log(config.muse ? 'Local Muse ready:' : 'ESP32 ready:', !!(await muse.health()).ready); }
 catch { console.log(config.muse ? 'Local Muse unavailable at startup; original XiaoAI mode remains active' : 'ESP32 unavailable at startup; original XiaoAI mode remains active'); }
}
if (!directEnabled) await native.start();
