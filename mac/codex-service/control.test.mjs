import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

class Element {
  children=[];value='';textContent='';
  constructor(tag='div'){this.tag=tag;}
  append(child){child.parent=this;this.children.push(child);}
  replaceChildren(...children){this.children=children;}
  remove(){this.parent.children=this.parent.children.filter(x=>x!==this);}
  descendants(tag){return this.children.flatMap(x=>[...(x.tag===tag?[x]:[]),...x.descendants(tag)]);}
}
test('unchanged polls and another pending request preserve typed input and submit that draft',async()=>{
  const nodes=Object.fromEntries(['key','connect','status','pending','jobs'].map(id=>[id,new Element()]));
  nodes.key.value='local-test-key';
  const pending=[{id:'question1',method:'item/tool/requestUserInput',params:{questions:[{id:'choice',question:'你希望什么？'}]}}],submitted=[];
  let poll;
  const script=readFileSync(new URL('./control.html',import.meta.url),'utf8').match(/<script[^>]*>([\s\S]*?)<\/script>/)[1];
  const context={document:{getElementById:id=>nodes[id],createElement:tag=>new Element(tag)},setInterval:fn=>{poll=fn;},fetch:async(path,opts)=>{
    if(path==='/control/respond')submitted.push(JSON.parse(opts.body));
    const data=path==='/control/status'?{ready:true}:path==='/control/pending'?pending:path==='/control/jobs'?[]:{ok:true};
    return{ok:true,json:async()=>JSON.parse(JSON.stringify(data))};
  }};
  runInNewContext(script,context);nodes.connect.onclick();await new Promise(r=>setImmediate(r));
  const input=nodes.pending.descendants('textarea')[0];input.value='请保留这个答案';
  await poll();await poll();
  pending.push({id:'approval2',method:'item/fileChange/requestApproval',params:{}});await poll();
  assert.equal(nodes.pending.descendants('textarea')[0],input);assert.equal(input.value,'请保留这个答案');
  const submit=nodes.pending.descendants('button').find(x=>x.textContent==='提交回答');await submit.onclick();
  assert.deepEqual(submitted,[{id:'question1',result:{answers:{choice:{answers:['请保留这个答案']}}}}]);
});
test('manager outage does not prevent original Codex replies refreshing',async()=>{
  const ids=['key','connect','status','pending','jobs','unified','unified-status','sdk-token','pair-start','pair-stop','save-sdk','muse-text','muse-ask','muse-reply'];
  const nodes=Object.fromEntries(ids.map(id=>[id,new Element()]));nodes.key.value='test-key';let jobPolls=0;
  const script=readFileSync(new URL('./control.html',import.meta.url),'utf8').match(/<script[^>]*>([\s\S]*?)<\/script>/)[1].replace('__UNIFIED__','true');
  runInNewContext(script,{document:{getElementById:id=>nodes[id],createElement:tag=>new Element(tag)},setInterval:()=>{},fetch:async path=>{if(path.startsWith('/control/unified'))throw Error('offline');if(path==='/control/jobs')jobPolls++;return{ok:true,json:async()=>path==='/control/status'?{ready:true}:path==='/control/jobs'?[{request_id:'x',status:'completed',reply:'final Codex answer'}]:[]};}});
  nodes.connect.onclick();await new Promise(r=>setImmediate(r));assert.equal(jobPolls,1);assert.equal(nodes.jobs.descendants('pre')[0].textContent,'final Codex answer');
});
