import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {loadRuntime,unavailableMuseClient,deriveWakeConfig} from './runtime-config.mjs';

function fixture(t, config) {
  const root=mkdtempSync(resolve(tmpdir(),'xiaoai-runtime-'));
  t.after(()=>rmSync(root,{recursive:true,force:true}));
  if(config!==undefined){mkdirSync(resolve(root,'mac/installer/private'),{recursive:true});writeFileSync(resolve(root,'mac/installer/private/runtime.json'),JSON.stringify(config));}
  return root;
}
const valid={version:1,node:'/opt/homebrew/bin/node',bridge_host:'192.168.1.20',labels:{native:'org.xiaoaigpt.ab12.native',realtime:'org.xiaoaigpt.ab12.realtime',unified:'org.xiaoaigpt.ab12.unified'},muse_enabled:false};

test('missing private runtime keeps legacy Muse route and uses current Node',t=>{
  const runtime=loadRuntime(fixture(t));
  assert.equal(runtime.node,process.execPath);
  assert.equal(runtime.muse_enabled,true);
  assert.equal(runtime.bridge_host,undefined);
});
test('installed runtime selects private bridge host and launchd labels',t=>{
  assert.deepEqual(loadRuntime(fixture(t,valid)),valid);
});
test('installed runtime rejects invalid paths, hosts, labels, and Muse activation',t=>{
  for(const change of [{node:'node'},{bridge_host:'8.8.8.8'},{bridge_host:'localhost'},{labels:{...valid.labels,realtime:'com.other.realtime'}},{muse_enabled:true},{version:2}]){
    assert.throws(()=>loadRuntime(fixture(t,{...valid,...change})),/Invalid private runtime/);
  }
});
test('Codex-only Muse route reports unavailable without connection attempt',async()=>{
  const muse=unavailableMuseClient();
  assert.deepEqual(await muse.health(),{ready:false,state:'unavailable'});
  await assert.rejects(muse.ask('id','text'),/Muse unavailable/);
});
test('Codex-only derived wake config disables Muse without changing public routes',()=>{
  const publicConfig={version:1,routes:[
    {label:'HEY_GPT',backend:'codex',enabled:true,phrases:['你好GPT'],kws_tokens:['K']},
    {label:'HEY_MUSE',backend:'muse',enabled:true,phrases:['hey muse'],kws_tokens:['M']},
  ]};
  const derived=deriveWakeConfig(publicConfig,false);
  assert.equal(derived.routes[0].enabled,true);
  assert.equal(derived.routes[1].enabled,false);
  assert.equal(publicConfig.routes[1].enabled,true);
  assert.deepEqual(deriveWakeConfig(publicConfig,true),publicConfig);
});
test('Codex-only runtime rejects wake config without an enabled Codex route',()=>{
  assert.throws(()=>deriveWakeConfig({version:1,routes:[{backend:'muse',enabled:true}]},false),/enabled Codex wake route/);
});
