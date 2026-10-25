import test from 'node:test';import assert from 'node:assert/strict';
import {createControlServer} from './server.mjs';
test('secondary is accepted only in explicit device registry',async()=>{
 let started;
 const server=createControlServer({session:{start:async id=>{started=id;return {active:true,device_id:id};}},key:'k',port:0,devices:['lx06-primary','lx06-secondary'],nativeStatus:async()=>({active:false})});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{
  const post=id=>fetch('http://127.0.0.1:'+server.address().port+'/start',{method:'POST',headers:{Authorization:'Bearer k'},body:JSON.stringify({device_id:id,mode:'continuous'})});
  assert.equal((await post('lx06-secondary')).status,200);assert.equal(started,'lx06-secondary');
  assert.equal((await post('unknown')).status,400);assert.equal(started,'lx06-secondary');
 }finally{await new Promise(r=>server.close(r));}
});
test('authorization and origin are checked before state mutation',async()=>{let calls=0;const session={status:()=>({active:false}),start:async()=>{calls++;return {};},stop:async()=>({})};const server=createControlServer({session,key:'secret',port:0,nativeStatus:async()=>({active:false})});await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port;
 try{assert.equal((await fetch(url+'/start',{method:'POST',body:'{}'})).status,401);assert.equal((await fetch(url+'/start',{method:'POST',headers:{Authorization:'Bearer secret',Origin:'https://external'},body:'{}'})).status,403);assert.equal(calls,0);}finally{await new Promise(r=>server.close(r));}});
test('active native lease blocks realtime acquisition',async()=>{let calls=0;const server=createControlServer({session:{start:async()=>{calls++;}},key:'k',port:0,nativeStatus:async()=>({active:true})});await new Promise(r=>server.listen(0,'127.0.0.1',r));try{const res=await fetch('http://127.0.0.1:'+server.address().port+'/start',{method:'POST',headers:{Authorization:'Bearer k'},body:JSON.stringify({device_id:'lx06-primary',mode:'continuous'})});assert.equal(res.status,409);assert.equal(calls,0);}finally{await new Promise(r=>server.close(r));}});
