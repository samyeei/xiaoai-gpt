import {readFileSync,statSync} from 'node:fs';
const defaultPath=new URL('../../config/voice-commands.json',import.meta.url);
const groups=['single','continuous','exit'];
const normalize=text=>String(text??'').normalize('NFKC').toLowerCase().replace(/[，。！？、,.!?\s]+/g,'');

// Literal segmentation preserves the existing 1–3 combined entry commands.
// Configuration text is never compiled as a regular expression.
function continuousMatch(text,phrases){
 if(!text||text.length>240)return false;
 let positions=new Set([0]);
 for(let count=0;count<3;count++){
  const next=new Set();
  for(const position of positions)for(const phrase of phrases)if(text.startsWith(phrase,position))next.add(position+phrase.length);
  if(next.has(text.length))return true;
  positions=next;
 }
 return false;
}
export function validateVoiceCommands(c){
 if(!c||typeof c!=='object'||Array.isArray(c)||c.version!==1||Object.keys(c).some(k=>!['version',...groups].includes(k)))throw Error('Invalid voice command configuration');
 const seen=new Set(),result={version:1},normalized={};
 for(const group of groups){
  const list=c[group];
  if(!Array.isArray(list)||list.length>32||(group==='exit'&&list.length===0))throw Error('Invalid voice command group: '+group);
  normalized[group]=[];
  for(const phrase of list){
   if(typeof phrase!=='string'||phrase.length<1||phrase.length>80||/[\u0000-\u001f\u007f]/.test(phrase))throw Error('Invalid voice command phrase: '+group);
   const value=normalize(phrase);
   if(!value||seen.has(value))throw Error('Duplicate or empty voice command');
   seen.add(value);normalized[group].push(value);
  }
  result[group]=Object.freeze([...list]);
 }
 for(const phrase of [...normalized.single,...normalized.exit])if(continuousMatch(phrase,normalized.continuous))throw Error('Ambiguous voice command groups');
 return Object.freeze(result);
}
export function loadVoiceCommands(path=defaultPath){
 if(statSync(path).size>16384)throw Error('Voice command configuration too large');
 return validateVoiceCommands(JSON.parse(readFileSync(path,'utf8')));
}
export function createVoiceCommandClassifier(config){
 const c=validateVoiceCommands(config),single=new Set(c.single.map(normalize)),exit=new Set(c.exit.map(normalize)),continuous=c.continuous.map(normalize);
 return text=>{
  const clean=normalize(text);
  if(single.has(clean))return 'single';
  if(continuousMatch(clean,continuous))return 'enter';
  if(exit.has(clean))return 'exit';
  return 'question';
 };
}
export function exitInstructions(config){
 const c=validateVoiceCommands(config);
 return '用户说完整退出口令时，简短告别并结束通话。退出口令列表（JSON字符串数组）：'+JSON.stringify(c.exit)+'。';
}
