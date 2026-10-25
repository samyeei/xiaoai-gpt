import {readFileSync,statSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const defaultPath=fileURLToPath(new URL('../../config/wake-words.json',import.meta.url));
const normalize=s=>s.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}_]/gu,'');
const exactFields=(object,fields)=>object&&typeof object==='object'&&!Array.isArray(object)&&Object.keys(object).length===fields.length&&fields.every(k=>Object.hasOwn(object,k));

export function loadWakeRoutes(path=process.env.WAKE_WORDS_CONFIG??defaultPath){
 if(statSync(path).size>65536)throw Error('Wake configuration too large');
 const c=JSON.parse(readFileSync(path,'utf8')),labels=new Set(),phrases=new Set(),routes=new Map();
 if(!exactFields(c,['version','routes'])||c.version!==1||!Array.isArray(c.routes)||c.routes.length<1||c.routes.length>32)throw Error('Invalid wake configuration');
 for(const r of c.routes){
  if(!exactFields(r,['label','backend','enabled','phrases','kws_tokens'])||typeof r.label!=='string'||!/^[A-Z][A-Z0-9_]{0,47}$/.test(r.label)||labels.has(r.label)||!['codex','muse'].includes(r.backend)||typeof r.enabled!=='boolean')throw Error('Invalid wake route');
  labels.add(r.label);
  if(!Array.isArray(r.phrases)||r.phrases.length<1||r.phrases.length>16)throw Error('Invalid wake phrases');
  for(const phrase of r.phrases){if(typeof phrase!=='string'||phrase.length<1||phrase.length>80||!normalize(phrase)||phrases.has(normalize(phrase)))throw Error('Invalid or duplicate wake phrase');phrases.add(normalize(phrase));}
  if(!Array.isArray(r.kws_tokens)||r.kws_tokens.length<1||r.kws_tokens.length>128||r.kws_tokens.some(x=>typeof x!=='string'||!/^[^\s@:$#]{1,32}$/u.test(x)))throw Error('Invalid wake pronunciation');
  if(r.enabled)routes.set(r.label,r.backend);
 }
 if(!routes.size)throw Error('At least one wake route must be enabled');
 return routes;
}
