import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
export function playFarewell(root,mode,device='lx06-primary'){
 if(!['diagnostic','managed'].includes(mode))throw Error('invalid_player_mode');
 return new Promise((resolveDone,reject)=>{
  const child=spawn(resolve(root,'.codex-runs/realtime-voice-env/bin/python'),[resolve(root,'mac/realtime-voice/farewell.py'),mode,device],{cwd:root,stdio:'ignore',timeout:10000});
  child.once('error',()=>reject(Error('farewell_failed')));
  child.once('close',code=>code===0?resolveDone():reject(Error('farewell_failed')));
 });
}
