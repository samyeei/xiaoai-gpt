import test from 'node:test';
import assert from 'node:assert/strict';
import {validatePreset,loadPreset} from './preset.mjs';
test('single-question effort can differ from continuous voice with a legacy fallback',()=>{
 const p=loadPreset();
 assert.equal(validatePreset({...p,single_reasoning_effort:'medium'}).single_reasoning_effort,'medium');
 assert.equal(validatePreset({...p,single_reasoning_effort:'medium'}).reasoning_effort,'high');
 const {single_reasoning_effort,...legacy}=p;
 assert.equal(validatePreset(legacy).single_reasoning_effort,'high');
 for(const v of ['fast',null,3])assert.throws(()=>validatePreset({...p,single_reasoning_effort:v}));
});
test('public assistant preset contains actual task, voice and playback settings',()=>{
 const p=loadPreset();assert.equal(p.model,'gpt-5.6-luna');assert.equal(p.reasoning_effort,'high');assert.equal(p.voice,'maple');assert.equal(p.output_gain,4);
 for(const change of [{output_gain:0},{output_gain:9},{output_gain:NaN},{reasoning_effort:'fast'},{voice:'maple;cmd'},{version:2},{key:'secret'}])assert.throws(()=>validatePreset({...p,...change}));
});
test('playback buffer is editable and bounded with a legacy default',()=>{const {output_buffer_ms,...old}=loadPreset();assert.equal(validatePreset(old).output_buffer_ms,600);assert.equal(validatePreset({...old,output_buffer_ms:2400}).output_buffer_ms,2400);for(const value of [null,99,3001,NaN,2400.5,'2400',true])assert.throws(()=>validatePreset({...old,output_buffer_ms:value}));});
