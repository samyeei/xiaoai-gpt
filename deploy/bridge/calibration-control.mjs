import {timingSafeEqual} from 'node:crypto';
export async function calibrationControl(req,res,voice,key){
 const send=(code,value)=>{res.writeHead(code,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
 const a=Buffer.from(req.headers.authorization??''),b=Buffer.from('Bearer '+(key??''));
 if(!key||a.length!==b.length||!timingSafeEqual(a,b)){send(401,{error:'unauthorized'});return;}
 if(req.headers.origin&&!['null','http://127.0.0.1:4398'].includes(req.headers.origin)){send(403,{error:'origin'});return;}
 if(req.method!=='POST'||req.url!=='/calibrate'){send(404,{error:'not_found'});return;}
 try{let body='';for await(const chunk of req){body+=chunk;if(Buffer.byteLength(body)>1024){send(413,{error:'size'});return;}}const p=JSON.parse(body||'{}');if(!p||Array.isArray(p)||typeof p!=='object'||Object.keys(p).length){send(400,{error:'invalid'});return;}
  if(!voice?.calibrate()){send(409,{error:'voice_busy'});return;}send(200,{state:'calibrating',seconds:60,session_id:voice.calibrationSession});
 }catch{if(!res.writableEnded)send(400,{error:'invalid'});}
}
