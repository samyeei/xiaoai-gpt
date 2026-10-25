import {spawn} from 'node:child_process';
import {EventEmitter} from 'node:events';
import {resolve} from 'node:path';
export class MediaChild extends EventEmitter{
 constructor(init,{root,executable}={}){super();this.init=init;this.root=root;this.executable=executable;this.closed=false;}
 async start(){
  this.child=spawn(this.executable??resolve(this.root,'.codex-runs/realtime-voice-env/bin/python'),[resolve(this.root,'mac/realtime-voice/media.py')],{cwd:this.root,stdio:['pipe','pipe','pipe']});
  this.exit=new Promise(r=>this.child.once('close',code=>{this.emit('exit',code);r();}));
  let buffer='';this.child.stdout.setEncoding('utf8');this.child.stdout.on('data',chunk=>{buffer+=chunk;if(buffer.length>65536){this.emit('event',{type:'error',code:'media_failed'});this.child.kill();return;}let end;while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);try{this.emit('event',JSON.parse(line));}catch{this.emit('event',{type:'error',code:'media_failed'});}}});
  this.child.stderr.setEncoding('utf8');this.child.stderr.on('data',chunk=>{for(const line of chunk.split('\n'))if(/^media diagnostic: phase=(player_preflight|media_setup) mode=(managed|diagnostic) exception=[A-Za-z]+$/.test(line)||line.startsWith('player diagnostic: '))process.stderr.write(line+'\n');});this.child.stdin.on('error',()=>{});this.child.on('error',()=>this.emit('event',{type:'error',code:'media_failed'}));this.send(this.init);
 }
 send(packet){if(this.child&&!this.closed)this.child.stdin.write(JSON.stringify(packet)+'\n');}
 async close(){if(this.closed)return;this.send({op:'close'});this.closed=true;if(!this.child)return;this.child.stdin.end();let timer;await Promise.race([this.exit,new Promise(r=>{timer=setTimeout(()=>{this.child.kill('SIGKILL');r();},10000);})]);clearTimeout(timer);await this.exit;}
}
