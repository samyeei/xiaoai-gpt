import test from 'node:test';import assert from 'node:assert/strict';import {classifyVoiceCommand} from './voice-mode.mjs';
test('user-selected continuous entry aliases match the whole command only',()=>{
 for(const text of ['开启连续对话','打开连续对话。','打开语音','激活连续对话！'])assert.equal(classifyVoiceCommand(text),'enter');
 for(const text of ['请解释打开语音的意思','怎么开启连续对话','打开语音是什么','他说激活连续对话'])assert.equal(classifyVoiceCommand(text),'question');
});
test('observed command with missing opening verb still enters; explanatory questions do not',()=>{
 assert.equal(classifyVoiceCommand('连续对话。'),'enter');
 for(const text of ['连续对话是什么意思','请解释连续对话','我不想连续对话'])assert.equal(classifyVoiceCommand(text),'question');
});
test('observed truncated and concatenated fixed control utterances enter without substring matching',()=>{
 for(const s of ['续对话','激活连续对话激活语音','打开连续对话打开语音','连续对话连续对话'])assert.equal(classifyVoiceCommand(s),'enter');
 for(const s of ['解释续对话是什么意思','激活连续对话一加一等于几','激活语音是什么意思','连续对话'.repeat(4)])assert.equal(classifyVoiceCommand(s),'question');
});
test('whole commands are local and quoted questions stay questions',()=>{for(const text of ['进入对话模式','开始连续对话。'])assert.equal(classifyVoiceCommand(text),'enter');for(const text of ['退下吧','好的，退下吧。','退出对话模式'])assert.equal(classifyVoiceCommand(text),'exit');for(const text of ['请解释退下吧的意思','一加一等于几',''])assert.equal(classifyVoiceCommand(text),'question');});
test('native GPT opener is a whole one-shot command, not continuous entry',()=>{for(const text of ['打开机劈替','打开机批替。','打开 GPT','打开ＧＰＴ！'])assert.equal(classifyVoiceCommand(text),'single');for(const text of ['请解释打开机劈替是什么意思','怎么打开GPT','打开机劈替一加一等于几'])assert.equal(classifyVoiceCommand(text),'question');assert.equal(classifyVoiceCommand('开启连续对话'),'enter');});
