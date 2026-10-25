import { createServer } from 'node:http';
import { timingSafeEqual, randomBytes } from 'node:crypto';
import { readFileSync } from 'node:fs';

const send=(res,status,data)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(data));};
const authorized=(req,key)=>{
  const actual=Buffer.from(req.headers.authorization ?? ''),expected=Buffer.from('Bearer '+key);
  return actual.length===expected.length && timingSafeEqual(actual,expected);
};
async function body(req) {
  if(!req.headers['content-type']?.startsWith('application/json')) throw Object.assign(new Error('JSON required'),{status:415});
  const chunks=[];let size=0;
  for await(const chunk of req){size+=chunk.length;if(size<=16384)chunks.push(chunk);}
  if(size>16384)throw Object.assign(new Error('Request too large'),{status:413});
  try{return JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw Object.assign(new Error('Invalid JSON'),{status:400});}
}
const errorStatus=error=>error.status ?? (/Not found/.test(error.message)?404:/conflict/.test(error.message)?409:/unavailable|capacity/.test(error.message)?503:400);
export function createEndpoints({service,key,adminKey,host='127.0.0.1',port=4411,controlPort=4412,unified=false}) {
  if(!/^[a-f0-9]{64}$/.test(key) || !/^[a-f0-9]{64}$/.test(adminKey) || key===adminKey)throw new Error('Invalid independent bridge/control keys');
  const lan=createServer(async(req,res)=>{
    try{
      if(!authorized(req,key)){send(res,401,{error:'Unauthorized'});return;}
      if(req.method==='GET' && req.url==='/health'){send(res,200,service.status());return;}
      if(req.method==='POST' && req.url==='/requests'){send(res,202,service.submit(await body(req)));return;}
      const path=req.url?.match(/^\/requests\/([a-zA-Z0-9_-]{1,80})(\/cancel)?$/);
      if(path && req.headers['x-request-digest']!==undefined){
        const expected=service.jobs.get(path[1])?.digest,actual=req.headers['x-request-digest'];
        if(!/^[a-f0-9]{64}$/.test(actual)||!expected||!timingSafeEqual(Buffer.from(actual),Buffer.from(expected))){send(res,409,{error:'Request ID conflict'});return;}
      }
      if(path && !path[2] && req.method==='GET'){send(res,200,service.get(path[1]));return;}
      if(path?.[2] && req.method==='POST'){send(res,200,await service.cancel(path[1]));return;}
      send(res,404,{error:'Not found'});
    }catch(error){send(res,errorStatus(error),{error:error.message});}
  });
  const control=createServer(async(req,res)=>{
    try{
      const expected=`127.0.0.1:${control.address().port}`;
      if(req.headers.host!==expected || (req.headers.origin && req.headers.origin!==`http://${expected}`)){send(res,403,{error:'Local origin required'});return;}
      if(req.method==='GET' && req.url==='/'){
        const nonce=randomBytes(18).toString('base64');
        res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':`default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`});
        res.end(readFileSync(new URL('./control.html',import.meta.url),'utf8').replaceAll('__NONCE__',nonce).replace('__UNIFIED__',unified?'true':'false'));return;
      }
      if(!authorized(req,adminKey)){send(res,401,{error:'Unauthorized'});return;}
      if(unified && req.url?.startsWith('/control/unified/')){
        const route=req.url.slice('/control/unified'.length);
        if(!['/status','/token','/pair/start','/pair/stop','/muse/ask','/muse/get'].includes(route)){send(res,404,{error:'Not found'});return;}
        const payload=req.method==='POST'?await body(req):undefined;
        const upstream=await fetch('http://127.0.0.1:4413'+route,{method:req.method,headers:{Authorization:'Bearer '+adminKey,'Content-Type':'application/json'},body:payload?JSON.stringify(payload):undefined,signal:AbortSignal.timeout(7000)});send(res,upstream.status,await upstream.json());return;
      }
      if(req.method==='GET' && req.url==='/control/status'){send(res,200,service.status());return;}
      if(req.method==='GET' && req.url==='/control/pending'){send(res,200,service.approvals());return;}
      if(req.method==='GET' && req.url==='/control/jobs'){send(res,200,[...service.jobs.keys()].reverse().slice(0,30).map(id=>service.get(id)));return;}
      if(req.method==='POST' && req.url==='/control/respond'){const x=await body(req);service.resolve(x.id,x.result);send(res,200,{ok:true});return;}
      if(req.method==='POST' && req.url==='/control/cancel'){const x=await body(req);send(res,200,await service.cancel(x.id));return;}
      send(res,404,{error:'Not found'});
    }catch(error){send(res,errorStatus(error),{error:error.message});}
  });
  for(const server of [lan,control]){server.requestTimeout=10000;server.headersTimeout=10000;server.maxHeadersCount=32;}
  lan.listen(port,host);control.listen(controlPort,'127.0.0.1');return {lan,control};
}
