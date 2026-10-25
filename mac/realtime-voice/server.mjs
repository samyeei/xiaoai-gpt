import {createServer} from 'node:http';
import {timingSafeEqual} from 'node:crypto';
export function createControlServer({session,key,port=4418,devices=['lx06-primary'],nativeStatus}){
 return createServer(async(req,res)=>{const send=(code,value)=>{res.writeHead(code,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
  const a=Buffer.from(req.headers.authorization??''),b=Buffer.from('Bearer '+key);
  if(a.length!==b.length||!timingSafeEqual(a,b)){send(401,{error:'unauthorized'});return;}
  if(req.headers.origin&& !['null',`http://127.0.0.1:${port}`].includes(req.headers.origin)){send(403,{error:'origin'});return;}
  try{
   if(req.method==='GET'&&req.url==='/status'){send(200,session.status());return;}
   if(req.method!=='POST'||!['/start','/stop','/listen'].includes(req.url)){send(404,{error:'not_found'});return;}
   let data='';for await(const chunk of req){data+=chunk;if(Buffer.byteLength(data)>1024){send(413,{error:'size'});return;}}
   const p=JSON.parse(data||'{}');if(!p||Array.isArray(p)||typeof p!=='object')throw Error();
   if(req.url==='/start'){
    if(!devices.includes(p.device_id)||p.mode!=='continuous'||Object.keys(p).some(k=>!['device_id','mode'].includes(k))){send(400,{error:'invalid_start'});return;}
    const native=await nativeStatus();if(native.active){send(409,{error:'audio_busy'});return;}
    send(200,await session.start(p.device_id));
   }else{
    if(Object.keys(p).some(k=>k!=='session_id')||p.session_id!==undefined&&typeof p.session_id!=='string'){send(400,{error:'invalid_control'});return;}
    send(200,req.url==='/listen'?session.listen(p.session_id):await session.stop(p.session_id));
   }
  }catch{if(!res.writableEnded)send(400,{error:'request_failed'});}
 });
}
