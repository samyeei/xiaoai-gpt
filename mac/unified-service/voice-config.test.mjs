import test from 'node:test';import assert from 'node:assert/strict';import {configureVoiceFlags} from './voice-config.mjs';
import {asrWakeTestEnv,asrWakeEnv} from './voice-config.mjs';
test('live ASR wake test is explicit, time bounded and cannot inherit extra options',()=>{
 assert.deepEqual(asrWakeTestEnv({enabled:true,expires_at:1600},1000),{ASR_WAKE_TEST_EXPIRES_AT:'1600'});
 for(const flag of [null,{}, {enabled:false,expires_at:1600},{enabled:true,expires_at:999},{enabled:true,expires_at:2201},{enabled:true,expires_at:1600,route:'muse'},{enabled:true,expires_at:'1600'}])assert.deepEqual(asrWakeTestEnv(flag,1000),{});
});
test('valid realtime flag excludes inherited native routes and fixes credentials',()=>{const c=configureVoiceFlags({native_voice:{key:'external'},realtime_voice:{url:'external'}},{realtimeFlag:{enabled:true},nativeFlag:{enabled:true}},'local');assert.equal(c.native_voice,undefined);assert.equal(c.realtime_voice.key,'local');assert.equal(c.realtime_voice.url,'http://127.0.0.1:4418');});
test('malformed realtime does not activate and native fallback remains explicit',()=>{const c=configureVoiceFlags({realtime_voice:{enabled:true}},{realtimeFlag:{enabled:true,max_session_seconds:9999},nativeFlag:{enabled:true}},'local');assert.equal(c.realtime_voice,undefined);assert.equal(c.native_voice.url,'http://127.0.0.1:4417');});

test('permanent ASR requires exact explicit private opt-in',()=>{
 assert.deepEqual(asrWakeEnv({enabled:true}),{ASR_WAKE_ENABLED:'1'});
 for(const flag of [null,{},[],{enabled:false},{enabled:'true'},{enabled:true,expires_at:999}])assert.deepEqual(asrWakeEnv(flag),{});
});
