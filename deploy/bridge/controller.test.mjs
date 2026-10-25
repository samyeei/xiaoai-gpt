import test from 'node:test';
import assert from 'node:assert/strict';
import { Controller, recognizedText, shellQuote, Speaker } from './controller.mjs';

const fixture = () => {
  const calls = [];
  const speaker = { interrupt: async () => calls.push('interrupt'), say: async text => calls.push(text) };
  const muse = { health: async () => ({ ready: true }), ask: async (_, text) => `answer:${text}` };
  return { calls, speaker, muse, c: new Controller(muse, speaker) };
};
test('ordinary XiaoAI commands do not intercept or call Muse', async () => {
  const { c, calls, muse } = fixture();
  muse.ask = async () => assert.fail('Muse should not run');
  await c.onText('明天早上七点叫我'); await c.onText('播放音乐');
  assert.deepEqual(calls, []); assert.equal(c.status().mode, 'xiaoai');
});
test('enter, converse, exit, and deduplicate recognition', async () => {
  const { c, calls } = fixture();
  await c.onText('和缪斯聊天'); assert.equal(c.status().mode, 'muse');
  await c.onText('你好'); await c.onText('你好');
  assert.equal(calls.filter(x => x === 'answer:你好').length, 1);
  await c.onText('返回小爱'); assert.equal(c.status().mode, 'xiaoai');
  assert.equal(calls.at(-1), '已返回小爱模式');
});
test('one-shot prefix returns a reply without entering persistent mode', async () => {
  const { c, calls } = fixture(); await c.onText('问缪斯：今天有什么建议');
  assert.equal(calls.at(-1), 'answer:今天有什么建议'); assert.equal(c.status().mode, 'xiaoai');
});
test('exit cancels a pending cloud request and suppresses its late reply', async () => {
  const { c, muse, calls } = fixture(); await c.onText('和缪斯聊天');
  let finish, started; const began = new Promise(resolve => { started = resolve; });
  let aborted = false;
  muse.ask = (_, __, signal) => new Promise(resolve => {
    finish = resolve; signal.addEventListener('abort', () => { aborted = true; }); started();
  });
  const old = c.onText('旧问题'); await began; await c.onText('返回小爱'); finish('stale reply'); await old;
  assert.equal(aborted, true); assert.ok(!calls.includes('stale reply'));
});
test('failure restores XiaoAI mode; expired mode leaves native instruction alone', async () => {
  const { c, muse, calls } = fixture();
  await c.onText('和缪斯聊天'); c.until = Date.now() - 1;
  const count = calls.length; await c.onText('播放音乐'); assert.equal(calls.length, count);
  muse.ask = async () => { throw new Error('offline'); };
  await c.onText('问缪斯怎么了'); assert.equal(c.status().mode, 'xiaoai');
  assert.equal(calls.at(-1), 'Muse暂时不可用，已返回小爱模式');
});
test('native command supersedes a pending one-shot Muse reply without interruption', async () => {
  const { c, muse, calls } = fixture();
  let finish, started; const began = new Promise(resolve => { started = resolve; });
  muse.ask = () => new Promise(resolve => { finish = resolve; started(); });
  const old = c.onText('问缪斯你好'); await began;
  const count = calls.length; await c.onText('播放音乐');
  finish('stale one-shot reply'); await old;
  assert.equal(calls.length, count); assert.equal(c.status().mode, 'xiaoai');
});
test('long playback holds Muse mode and starts idle timeout after playback', async () => {
  const { c, calls } = fixture(); await c.onText('和缪斯聊天');
  c.onPlaying(true); c.until = Date.now() - 1;
  await c.onText('接着说'); assert.equal(calls.at(-1), 'answer:接着说');
  c.onPlaying(false); assert.ok(c.until > Date.now());
});
test('accepts only final SpeechRecognizer events and tolerates malformed data', () => {
  const e = { event: 'instruction', data: { NewLine: JSON.stringify({ header: { namespace: 'SpeechRecognizer', name: 'RecognizeResult' }, payload: { is_final: true, results: [{ text: 'hello' }] } }) } };
  assert.equal(recognizedText(JSON.stringify(e)), 'hello');
  assert.equal(recognizedText('bad'), null);
  e.data.NewLine = e.data.NewLine.replace('true', 'false'); assert.equal(recognizedText(e), null);
});
test('reply text is shell quoted, including apostrophes and command substitutions', async () => {
  const text = "it's $(touch /tmp/pwned) `id`";
  assert.equal(shellQuote("a'b"), "'a'\\''b'");
  let command;
  const s = new Speaker({ run_shell: async script => { command = script; return JSON.stringify({ exit_code: 0, stdout: '{"code":0}' }); } });
  await s.say(text);
  assert.equal(command, 'ubus call mibrain text_to_speech ' + shellQuote(JSON.stringify({ text, save: 0 })));
});
test('direct Codex request uses fixed backend and suppresses late reply after native command',async()=>{
 const {c,calls}=fixture();let finish,signal;c.codex={ask:(_,__,s)=>{signal=s;return new Promise(r=>finish=r);}};
 const pending=c.onDirectText('task','codex');await Promise.resolve();await c.onText('播放音乐');finish('late');await pending;
 assert.equal(signal.aborted,true);assert.ok(!calls.includes('late'));
});
test('Codex waiting user announcement is once and serialized before final',async()=>{
 const {c,calls}=fixture();c.codex={ask:async(_,__,___,status)=>{await status('waiting_user');await status('waiting_user');return 'done';}};
 await c.onDirectText('task','codex');assert.deepEqual(calls,['Codex正在等待你在Mac上确认。','done']);
});
test('Codex long task speaks accepted once and cancels timer on completion',async()=>{
 const {c,calls}=fixture();c.codexAcceptedDelay=5;let finish;c.codex={ask:()=>new Promise(r=>finish=r)};
 const task=c.onDirectText('long','codex');await new Promise(r=>setTimeout(r,15));finish('done');await task;
 assert.deepEqual(calls,['Codex已接受任务，正在处理。','done']);
});
test('Codex and Muse switching cancels old request and suppresses stale status',async()=>{
 const {c,calls}=fixture();let finish,callback,signal;c.codex={ask:(_,__,s,status)=>{signal=s;callback=status;return new Promise(r=>finish=r);}};
 const old=c.onDirectText('task','codex');await c.onDirectText('hello','muse');await callback('waiting_user');finish('stale');await old;
 assert.equal(signal.aborted,true);assert.deepEqual(calls,['answer:hello']);
});
test('absent Codex fails safely without invoking Muse',async()=>{
 const {c,calls,muse}=fixture();muse.ask=()=>assert.fail('fallback must not call Muse');await c.onDirectText('task','codex');assert.deepEqual(calls,['Codex暂时不可用，请稍后再试。']);
});
test('final waits for interim playback and rechecks cancellation after playback',async()=>{
 for(const cancel of [false,true]){
  const {c,calls}=fixture();let release,started;const began=new Promise(r=>started=r);
  c.progressPlayback=async action=>{await action();if(calls.at(-1)!=='final'){started();await new Promise(r=>release=r);}};
  c.codex={ask:async(_,__,___,status)=>{void status('waiting_user');await began;return 'final';}};
  const task=c.onDirectText('task','codex');await began;await Promise.resolve();assert.ok(!calls.includes('final'));
  if(cancel)await c.onText('播放音乐');release();await task;assert.equal(calls.includes('final'),!cancel);
 }
});
test('direct final reply waits for confirmed playback before completing the request',async()=>{
 const {c,calls}=fixture();let release;let announced;const began=new Promise(r=>announced=r);
 c.codex={ask:async()=> 'answer'};
 c.progressPlayback=async action=>{await action();announced();await new Promise(r=>release=r);};
 let complete=false;const task=c.onDirectText('question','codex').then(()=>complete=true);
 await Promise.race([began,new Promise(r=>setTimeout(r,30))]);assert.equal(complete,false);
 assert.deepEqual(calls,['answer']);release();await task;assert.equal(complete,true);
});
