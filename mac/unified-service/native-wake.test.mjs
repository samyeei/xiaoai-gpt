import {dispatchNativeText} from '../../deploy/bridge/native-commands.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {nativeWakeOptIn} from '../../deploy/bridge/native-voice-client.mjs';
test('manager clears inherited native voice config and injects fixed private admin authentication',()=>{const source=readFileSync(new URL('./index.mjs',import.meta.url),'utf8');assert.ok(source.indexOf('delete bridge.native_voice;')<source.indexOf('nativeWakeOptIn(JSON.parse'));assert.match(source,/native-wake\.json/);assert.match(source,/codex\.admin_key/);assert.deepEqual(nativeWakeOptIn({enabled:true},'private'),{url:'http://127.0.0.1:4417',key:'private'});});
test('native mode owns the single dynamic mirror and suppresses controller text',()=>{const source=readFileSync(new URL('../../deploy/bridge/index.mjs',import.meta.url),'utf8');assert.match(source,/new AudioMirror\(directEnabled && !config.native_voice/);});

test('native questions stay suppressed while local control is allowed through the same gate',async()=>{let questions=0,controls=0;const controller={onText:async()=>questions++};const voice={nativeBlocked:()=>true,onNativeText:async text=>{if(text==='退下吧'){controls++;return true;}return false;}};assert.equal(await dispatchNativeText(voice,controller,'天气如何'),false);assert.equal(questions,0);assert.equal(await dispatchNativeText(voice,controller,'退下吧'),true);assert.equal(controls,1);assert.equal(questions,0);});
