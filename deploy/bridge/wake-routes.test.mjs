import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {loadWakeRoutes} from './wake-routes.mjs';

test('routing follows only enabled configured labels and rejects duplicate phrases',()=>{
 const dir=mkdtempSync(join(tmpdir(),'wake-config-')),path=join(dir,'words.json');
 const data={version:1,routes:[{label:'CUSTOM',backend:'codex',enabled:true,phrases:['hey ming'],kws_tokens:['HH']},{label:'OFF',backend:'muse',enabled:false,phrases:['hey muse'],kws_tokens:['M']}]};
 try{writeFileSync(path,JSON.stringify(data));const routes=loadWakeRoutes(path);assert.equal(routes.get('CUSTOM'),'codex');assert.equal(routes.has('OFF'),false);assert.equal(routes.has('HEY_LUKA'),false);
 data.routes[1].phrases=['HEY, MING!'];writeFileSync(path,JSON.stringify(data));assert.throws(()=>loadWakeRoutes(path));
 data.routes[1].phrases=['hey muse'];data.routes[0].enabled='true';writeFileSync(path,JSON.stringify(data));assert.throws(()=>loadWakeRoutes(path));
 assert.throws(()=>loadWakeRoutes(join(dir,'missing.json')));
 }finally{rmSync(dir,{recursive:true});}
});

test('DirectVoice ignores a disabled default label and routes a custom one',async()=>{
 const {DirectVoice}=await import('./direct-voice.mjs');
 const voice=Object.assign(Object.create(DirectVoice.prototype),{wakeRoutes:new Map([['CUSTOM','codex']]),state:'idle',generation:0,send(){},speaker:{say:async()=>{}},playback:async(_,action)=>action()});
 await voice.wake('HEY_LUKA');assert.equal(voice.state,'idle');await voice.wake('CUSTOM');assert.equal(voice.state,'listening');assert.equal(voice.backend,'codex');
});
