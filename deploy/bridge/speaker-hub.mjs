import {WebSocketServer} from 'ws';
import {SpeakerTransport} from './speaker-transport.mjs';
export class SpeakerHub{
 constructor({devices,port=4399,host='0.0.0.0',peerAddress=req=>req.socket.remoteAddress}){
  this.devices=new Map(devices.map(d=>[d.id,new SpeakerTransport({listen:false})]));
  const byIP=new Map(devices.map(d=>[d.ip,this.devices.get(d.id)]));
  this.server=new WebSocketServer({port,host,maxPayload:2*1024*1024});
  this.server.on('connection',(socket,req)=>{
   socket.on('error',()=>{});
   const ip=peerAddress(req)?.replace(/^::ffff:/,'');
   const target=byIP.get(ip);if(!target){socket.close(1008,'Unknown speaker');return;}
   target.accept(socket);
  });
 }
 async close(){await Promise.all([...this.devices.values()].map(d=>d.close()));await new Promise(r=>this.server.close(r));}
}
