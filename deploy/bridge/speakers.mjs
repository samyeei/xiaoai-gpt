import {readFileSync} from 'node:fs';
import {isIPv4} from 'node:net';
export function validateSpeakers(c){
 if(!c||c.version!==1||!['single','multiple'].includes(c.mode)||!Array.isArray(c.devices)||c.devices.length!==2)throw Error('Invalid speaker registry');
 const ids=new Set(),ips=new Set();
 for(const d of c.devices){
  if(!d||!['lx06-primary','lx06-secondary'].includes(d.id)||!isIPv4(d.ip)||ids.has(d.id)||ips.has(d.ip)||Object.keys(d).some(k=>!['id','ip'].includes(k)))throw Error('Invalid speaker identity');
  ids.add(d.id);ips.add(d.ip);
 }
 return {...c,devices:c.devices.filter(d=>c.mode==='multiple'||d.id==='lx06-primary')};
}
export function loadSpeakers(){return validateSpeakers(JSON.parse(readFileSync(process.env.SPEAKERS_CONFIG??new URL('../../config/speakers.json',import.meta.url),'utf8')));}
