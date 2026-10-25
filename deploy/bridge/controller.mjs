import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';

export const shellQuote = value => "'" + String(value).replaceAll("'", "'\\''") + "'";
export function recognizedText(event) {
  try {
    const e = typeof event === 'string' ? JSON.parse(event) : event;
    if (e.event !== 'instruction' || !e.data?.NewLine) return null;
    const line = JSON.parse(e.data.NewLine);
    if (line.header?.namespace !== 'SpeechRecognizer' || line.header?.name !== 'RecognizeResult' || line.payload?.is_final !== true) return null;
    return line.payload.results?.[0]?.text || null;
  } catch { return null; }
}
export class Speaker {
  constructor(native) { this.native = native; }
  async run(script) {
    const raw = await this.native.run_shell(script, 10000);
    const result = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!result || result.exit_code !== 0) throw new Error('Speaker command failed');
    return result;
  }
  async interrupt() {
    await this.run('/etc/init.d/mico_aivs_lab restart >/dev/null 2>&1');
    await delay(2000);
    await this.run('mphelper pause');
  }
  async say(text) {
    const result = await this.run('ubus call mibrain text_to_speech ' + shellQuote(JSON.stringify({ text, save: 0 })));
    try { if (JSON.parse(result.stdout).code !== 0) throw new Error('TTS rejected'); }
    catch (error) { throw new Error('Speaker TTS failed', { cause: error }); }
  }
}
const normalize = text => text.trim().replace(/[，。！？、,.!?\s]+/g, '');
export class Controller {
  constructor(muse, speaker, config = {}, codex = null) {
    this.muse = muse; this.speaker = speaker; this.codex = codex;
    this.codexAcceptedDelay = config.codex_accepted_delay_ms ?? 8000;
    this.modeTimeout = config.mode_timeout_ms ?? 60000;
    this.mode = false; this.until = 0; this.current = null;
    this.playing = false;
    this.sequence = 0; this.operations = Promise.resolve();
    this.lastText = ''; this.lastTime = 0; this.lastError = null;
  }
  status() { return { mode: this.mode ? 'muse' : 'xiaoai', pending: !!this.current, last_error: this.lastError }; }
  onPlaying(playing) {
    this.playing = playing;
    if (!playing && this.mode) this.until = Date.now() + this.modeTimeout;
  }
  cancel() { this.sequence++; this.current?.abort.abort(); this.current = null; }
  async onDirectText(text, backend = 'muse') {
    if (!['muse', 'codex'].includes(backend)) return;
    this.cancel(); this.mode = false; const sequence = this.sequence;
    const abort = new AbortController(), id = randomUUID();
    this.current = { abort, id, backend }; this.lastError = null;
    let timer, waiting = false, finished = false;
    const status = async value => {
      if (sequence !== this.sequence || finished) return;
      if (value === 'waiting_user' && !waiting) {
        waiting = true; clearTimeout(timer);
        await this.operation(sequence, () => this.progressSay('Codex正在等待你在Mac上确认。'));
      }
    };
    if (backend === 'codex') timer = setTimeout(() => {
      if (!finished && !waiting && sequence === this.sequence)
        void this.operation(sequence, () => {
          if (!finished && !waiting) return this.progressSay('Codex已接受任务，正在处理。');
        }).catch(() => {});
    }, this.codexAcceptedDelay);
    try {
      const client = backend === 'codex' ? this.codex : this.muse;
      if (!client) throw new Error('Codex unavailable');
      const reply = await client.ask(id, text, abort.signal, status);
      finished = true; clearTimeout(timer);
      if (sequence === this.sequence) await this.operation(sequence, () => this.progressSay(reply));
    } catch (error) {
      finished = true; clearTimeout(timer);
      if (sequence === this.sequence) {
        this.lastError = backend === 'codex' ? 'Codex unavailable' : error.message;
        await this.operation(sequence, () => this.progressSay(backend === 'codex' ? 'Codex暂时不可用，请稍后再试。' : 'Muse暂时不可用，请稍后再试。'));
      }
    } finally { clearTimeout(timer); if (sequence === this.sequence) this.current = null; }
  }
  async progressSay(text) {
    const action = () => this.speaker.say(text);
    if (this.progressPlayback) await this.progressPlayback(action);
    else await action();
  }
  async operation(sequence, fn) {
    // Serialize remote shell operations, and recheck after queued waits.
    const task = this.operations.catch(() => {}).then(async () => { if (sequence === this.sequence) await fn(); });
    this.operations = task; await task;
  }
  async onText(text) {
    if (typeof text !== 'string' || !text.trim()) return;
    const now = Date.now(), cleaned = normalize(text);
    if (text === this.lastText && now - this.lastTime < 1800) return;
    this.lastText = text; this.lastTime = now;
    if (this.mode && !this.current && !this.playing && now > this.until) this.mode = false;
    const enter = /^(和|跟)?(缪斯|谬斯|Muse|muse)聊(天|聊)$/.test(cleaned);
    const exit = /^(退出(缪斯|谬斯|Muse|muse)(模式)?|返回小爱|结束聊天)$/.test(cleaned);
    const single = text.match(/^\s*问(?:缪斯|谬斯|Muse|muse)[，,:：\s]*(.+)$/u);
    if (exit && (this.mode || this.current)) {
      this.cancel(); this.mode = false;
      const sequence = this.sequence;
      await this.operation(sequence, async () => { await this.speaker.interrupt(); if (sequence === this.sequence) await this.speaker.say('已返回小爱模式'); });
      return;
    }
    if (!enter && !single && !this.mode) {
      // A native command after a one-shot question supersedes its pending reply.
      // Leave the native command alone while cancelling the older Muse request.
      if (this.current) this.cancel();
      return;
    }
    this.cancel(); const sequence = this.sequence;
    if (enter) { this.mode = true; this.until = now + this.modeTimeout; }
    const abort = new AbortController(), id = randomUUID();
    this.current = { abort, id }; this.lastError = null;
    try {
      await this.operation(sequence, () => this.speaker.interrupt());
      if (sequence !== this.sequence) return;
      if (enter) {
        const health = await this.muse.health();
        if (!health.ready) throw new Error('Muse is not ready');
        await this.operation(sequence, () => this.speaker.say('可以了，请唤醒小爱后直接说你的问题。说返回小爱退出。'));
      } else {
        const reply = await this.muse.ask(id, single ? single[1] : text, abort.signal);
        if (sequence !== this.sequence) return;
        await this.operation(sequence, () => this.speaker.say(reply));
      }
      if (sequence === this.sequence) this.until = Date.now() + this.modeTimeout;
    } catch (error) {
      if (sequence === this.sequence) {
        this.mode = false; this.lastError = error.message;
        // Log no question, answer, credential or token.
        console.error('Muse bridge request failed:', error.message);
        try { await this.operation(sequence, () => this.speaker.say('Muse暂时不可用，已返回小爱模式')); } catch { /* speaker offline */ }
      }
    } finally { if (sequence === this.sequence) this.current = null; }
  }
}
