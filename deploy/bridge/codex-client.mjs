import { setTimeout as delay } from 'node:timers/promises';
import { isIP } from 'node:net';
import { createHash } from 'node:crypto';
const safeError = status => Object.assign(new Error('Codex request unavailable'),Number.isInteger(status)?{status}:{});
const definitive = error => error?.status>=400 && error.status<500 && error.status!==408;
export class CodexClient {
  constructor(config) {
    let endpoint; try { endpoint = new URL(config.url); } catch { throw new Error('Invalid Codex configuration'); }
    const host=endpoint.hostname;
    const lanIP=isIP(host)===4 && (/^10\./.test(host)||/^192\.168\./.test(host)||/^172\.(1[6-9]|2\d|3[01])\./.test(host)||host==='127.0.0.1');
    const lanName=/^[a-z0-9-]+(?:\.local|\.lan)?$/i.test(host);
    if(endpoint.protocol!=='http:'||!endpoint.port||endpoint.username||endpoint.password||endpoint.search||endpoint.hash||endpoint.pathname!=='/'||(!lanIP&&!lanName)||!/^[a-f0-9]{64}$/.test(config.key))throw new Error('Invalid Codex configuration');
    this.activeDigests=new Map();this.url=endpoint.origin;this.key=config.key;this.timeout=config.request_timeout_ms??900000;this.pollInterval=750;
    if(!Number.isFinite(this.timeout)||this.timeout<=0)throw new Error('Invalid Codex configuration');
  }
  digest(text){return createHash('sha256').update(text,'utf8').digest('hex');}
  async http(path,method='GET',body,signal,digest) {
    try {
      const timeout=AbortSignal.timeout(4000);
      const response=await fetch(this.url+path,{method,headers:{Authorization:`Bearer ${this.key}`,'Content-Type':'application/json',...(digest?{'X-Request-Digest':digest}:{})},body:body?JSON.stringify(body):undefined,signal:signal?AbortSignal.any([signal,timeout]):timeout});
      if(!response.ok)throw safeError(response.status);return await response.json();
    } catch(error) {throw safeError(error?.status);}
  }
  health(){return this.http('/health');}
  async cancel(id,digest){try{await this.http(`/requests/${encodeURIComponent(id)}/cancel`,'POST',undefined,undefined,digest);}catch{}}
  async ask(id,text,signal,onStatus) {
    if(this.activeDigests.has(id))throw safeError();
    let digest,cancelAllowed=false;
    const taskSignal=signal?AbortSignal.any([signal,AbortSignal.timeout(this.timeout)]):AbortSignal.timeout(this.timeout);
    const path=`/requests/${encodeURIComponent(id)}`;let previous;
    try {
      if(typeof text!=='string'||!text.trim()||Buffer.byteLength(text,'utf8')>2048)throw safeError();
      digest=this.digest(text);this.activeDigests.set(id,digest);cancelAllowed=true;
      let job;try{job=await this.http('/requests','POST',{request_id:id,text},taskSignal);}catch(error){if(definitive(error)){cancelAllowed=false;throw error;}if(taskSignal.aborted)throw error;job=await this.http(path,'GET',undefined,taskSignal,digest);}
      while(!taskSignal.aborted){
        if(!['queued','running','waiting_user','completed','failed','cancelled'].includes(job?.status))throw safeError();
        if(job.status!==previous){previous=job.status;await onStatus?.(job.status);}
        if(job.status==='completed'){if(typeof job.reply!=='string'||!job.reply.trim())throw safeError();return job.reply;}
        if(['failed','cancelled'].includes(job.status))throw safeError();
        await delay(this.pollInterval,undefined,{signal:taskSignal});job=await this.http(path,'GET',undefined,taskSignal,digest);
      }
      throw safeError();
    }catch(error){if(definitive(error))cancelAllowed=false;throw safeError(error?.status);}finally{if(cancelAllowed)await this.cancel(id,digest);this.activeDigests.delete(id);}
  }
}
