import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createVoiceCommandClassifier,loadVoiceCommands,validateVoiceCommands} from './voice-commands.mjs';

const custom=()=>({version:1,single:['问助手'],continuous:['开始聊天','继续聊'],exit:['结束聊天']});
test('custom configuration replaces all three built-in command groups',()=>{
 const classify=createVoiceCommandClassifier(custom());
 for(const [text,kind] of [['问助手','single'],['开始聊天。','enter'],['继续聊','enter'],['结束聊天','exit']])assert.equal(classify(text),kind);
 for(const text of ['打开机劈替','开启连续对话','退下吧','好的退下吧','请解释结束聊天的意思'])assert.equal(classify(text),'question');
});
test('normalization and whole literal matching preserve bounded combined entry commands',()=>{
 const c=custom();c.single=['打开 GPT'];c.continuous=['开启(C++)','继续聊'];
 const classify=createVoiceCommandClassifier(c);
 assert.equal(classify('打开ＧＰＴ！'),'single');
 assert.equal(classify('开启(C++)继续聊'),'enter');
 for(const text of ['开启CCCC','请解释开启(C++)','继续聊'.repeat(4)])assert.equal(classify(text),'question');
});
test('invalid or ambiguous configuration fails instead of silently using old commands',()=>{
 const bad=[];
 for(const value of [null,{},[],{...custom(),version:2},{...custom(),exit:[]},{...custom(),unknown:1}])bad.push(value);
 for(const value of [[''],['a','Ａ'],[null],['a'.repeat(81)]])bad.push({...custom(),single:value});
 bad.push({...custom(),single:['开始聊天']});
 bad.push({...custom(),single:['开始聊天继续聊']});
 for(const c of bad)assert.throws(()=>validateVoiceCommands(c));
});
test('loader reads edited JSON and rejects oversized or malformed files',()=>{
 const dir=mkdtempSync(join(tmpdir(),'voice-commands-')),file=join(dir,'commands.json');
 try{
  writeFileSync(file,JSON.stringify(custom()));assert.equal(createVoiceCommandClassifier(loadVoiceCommands(file))('问助手'),'single');
  writeFileSync(file,'{');assert.throws(()=>loadVoiceCommands(file));
  writeFileSync(file,' '.repeat(17000));assert.throws(()=>loadVoiceCommands(file));
 }finally{rmSync(dir,{recursive:true,force:true});}
});
