import {readFileSync,statSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const path=fileURLToPath(new URL('../../config/assistant.json',import.meta.url));
export function validatePreset(p){
 const fields=['version','model','reasoning_effort','voice','output_gain'];
 if(!p||typeof p!=='object'||Array.isArray(p)||Object.keys(p).some(k=>!fields.includes(k)&&!['output_buffer_ms','single_reasoning_effort'].includes(k))||!fields.every(k=>Object.hasOwn(p,k))||p.version!==1||typeof p.model!=='string'||!/^[a-zA-Z0-9._-]{1,100}$/.test(p.model)||!['none','minimal','low','medium','high','xhigh','max','ultra'].includes(p.reasoning_effort)||typeof p.voice!=='string'||!/^[a-z][a-z0-9_-]{0,31}$/.test(p.voice)||typeof p.output_gain!=='number'||!Number.isFinite(p.output_gain)||p.output_gain<.25||p.output_gain>8)throw Error('Invalid assistant preset');
 const singleEffort=p.single_reasoning_effort??p.reasoning_effort;if(Object.hasOwn(p,'single_reasoning_effort')&&!['none','minimal','low','medium','high','xhigh','max','ultra'].includes(p.single_reasoning_effort))throw Error('Invalid single-question effort');
 const buffer=Object.hasOwn(p,'output_buffer_ms')?p.output_buffer_ms:600;if(!Number.isInteger(buffer)||buffer<100||buffer>3000)throw Error('Invalid playback buffer');
 return Object.freeze({...p,single_reasoning_effort:singleEffort,output_buffer_ms:buffer});
}
export function loadPreset(){if(statSync(path).size>4096)throw Error('Assistant preset too large');return validatePreset(JSON.parse(readFileSync(path,'utf8')));}
