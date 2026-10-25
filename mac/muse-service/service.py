"""Private job ledger and reconnecting Muse backend. No question is persisted."""
from __future__ import annotations
import asyncio
import contextlib
import hashlib
import hmac
import json
import pathlib
import re
import secrets
import time
import uuid
from pair import DEFAULT_STATE, initialize_state, private_directory, save_private_json, read_sdk_token, _https_api
from musegadget import config, muse_api
from musegadget.link_client import DeviceDescription, Outcome
from chat import ChatSession

class JobError(Exception):
    def __init__(self,status=400):self.status=status;super().__init__('Muse request unavailable')

def read_private(name,directory):
    path=pathlib.Path(directory)/name
    if path.is_symlink():raise ValueError('Invalid private state')
    if not path.exists():return None
    path.chmod(0o600)
    value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('Invalid private state')
    return value

def load_config(directory):
    directory=private_directory(directory);record=read_private('config.json',directory)
    if record is None:
        record={'url':'http://127.0.0.1:4414','key':secrets.token_hex(32),'session_id':str(uuid.uuid4())}
        save_private_json('config.json',record,directory)
    if not isinstance(record.get('key'),str) or not re.fullmatch('[0-9a-f]{64}',record['key']):raise ValueError('Invalid Muse configuration')
    if not isinstance(record.get('session_id'),str) or not re.fullmatch('[A-Za-z0-9-]{1,128}',record['session_id']):raise ValueError('Invalid Muse configuration')
    return record

class JobService:
    def __init__(self,directory,backend):
        self.directory=private_directory(directory);self.backend=backend;self.config=load_config(directory);self.session_id=self.config['session_id']
        stored=read_private('jobs.json',directory) or {'jobs':{}}
        self.storage_ok=True;self.jobs=stored['jobs'];self.queue=asyncio.Queue(maxsize=8);self.current=None;self.worker=None;self.closed=False
        for job in self.jobs.values():
            if job['status'] in ('queued','running'):job.update(status='failed',error='Muse delivery uncertain')
        self.persist()
    def persist(self):
        try:save_private_json('jobs.json',{'jobs':self.jobs},self.directory)
        except Exception:self.storage_ok=False;raise
        self.storage_ok=True
    def start(self):self.worker=asyncio.create_task(self.run())
    def health(self):return {'service':'mac-muse','ready':bool(self.backend.ready and self.storage_ok and not self.closed and self.worker and not self.worker.done()),'state':getattr(self.backend,'state','ready' if self.backend.ready else 'offline'),'queue_depth':self.queue.qsize()}
    def get(self,request_id):
        job=self.jobs.get(request_id)
        if not job:raise JobError(404)
        return {k:v for k,v in job.items() if k!='digest'}
    async def submit(self,request_id,text):
        if not isinstance(request_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',request_id):raise JobError()
        if not isinstance(text,str) or not text.strip() or len(text.encode('utf-8'))>2048:raise JobError()
        digest=hmac.new(bytes.fromhex(self.config['key']),text.encode(),hashlib.sha256).hexdigest()
        if request_id in self.jobs:
            if not hmac.compare_digest(self.jobs[request_id]['digest'],digest):raise JobError(409)
            return self.get(request_id)
        if self.closed or not self.storage_ok or not self.backend.ready:raise JobError(503)
        if self.queue.full() or sum(j['status'] in ('queued','running') for j in self.jobs.values())>=8:raise JobError(429)
        prior=dict(self.jobs)
        if len(self.jobs)>=1000:
            oldest=next((k for k,j in self.jobs.items() if j['status'] not in ('queued','running')),None)
            if oldest is None:raise JobError(429)
            del self.jobs[oldest]
        self.jobs[request_id]={'request_id':request_id,'status':'queued','digest':digest}
        try:self.persist()
        except Exception:self.jobs=prior;raise JobError(503) from None
        self.queue.put_nowait((request_id,text));return self.get(request_id)
    async def cancel(self,request_id):
        job=self.jobs.get(request_id)
        if not job:raise JobError(404)
        if job['status'] in ('queued','running'):
            job['status']='cancelled';self.persist()
            if self.current and self.current[0]==request_id:self.current[1].cancel()
        return self.get(request_id)
    async def run(self):
        while True:
            request_id,text=await self.queue.get();job=self.jobs[request_id]
            try:
                if job['status']!='queued':continue
                # Persist uncertain delivery before any possible network submission.
                job['status']='running'
                try:self.persist()
                except Exception:
                    job.update(status='failed',error='Muse storage unavailable')
                    with contextlib.suppress(Exception):self.persist()
                    continue
                task=asyncio.create_task(self.backend.ask(text,self.session_id));self.current=(request_id,task)
                try:
                    reply=await task
                    if not isinstance(reply,str) or not reply.strip() or len(reply.encode())>65536:raise ValueError()
                    if job['status']=='running':job.update(status='completed',reply=reply)
                except asyncio.CancelledError:
                    if job['status']=='running':job.update(status='failed',error='Muse delivery uncertain')
                    if self.closed:raise
                except Exception:
                    if job['status']=='running':job.update(status='failed',error='Muse request unavailable')
                finally:
                    self.current=None
                    with contextlib.suppress(Exception):self.persist()
            finally:self.queue.task_done()
    async def close(self):
        self.closed=True
        if self.worker:
            self.worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):await self.worker
        for job in self.jobs.values():
            if job['status']=='queued':job['status']='cancelled'
        self.persist()

class MuseBackend:
    def __init__(self,directory=DEFAULT_STATE):
        self.registration_timeout=20;self.directory=private_directory(directory);self.identity=initialize_state(directory);self.session=None;self.state='unpaired';self.stop=asyncio.Event()
    @property
    def ready(self):return bool(self.session and self.session.registered_at is not None and self.state=='connected')
    async def ask(self,text,session_id):
        session=self.session
        if not self.ready:raise ConnectionError('Muse unavailable')
        return await session.ask(text,session_id)
    async def refresh(self,record,root):
        # Read the manual SDK token on demand, including after late phone pairing.
        token=read_sdk_token(self.directory)
        if not token:raise ConnectionError('Muse unavailable')
        tokens,status=await asyncio.to_thread(muse_api.refresh_device_token,record['refresh_token'],self.identity.node_id,root,token)
        if status!=200 or not tokens:raise ConnectionError('Muse unavailable')
        record.update(access_token=tokens['access_token'],refresh_token=tokens['refresh_token'],access_token_saved_at=int(time.time()))
        save_private_json(config.PAIRING_FILE,record,self.directory)
    async def run(self):
        delay=2;unpaired_signature=None
        while not self.stop.is_set():
            try:
                record=read_private(config.PAIRING_FILE,self.directory)
                if not record or not record.get('access_token') or not record.get('refresh_token'):
                    self.state='unpaired';await self.pause(2);continue
                signature=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).digest()
                if signature==unpaired_signature:self.state='unpaired';await self.pause(2);continue
                root=_https_api(record.get('api_url_v2')) or muse_api.API_BASE
                host=record.get('noise_host') or 'hatch.metaaivm.com'
                if host!='hatch.metaaivm.com':raise ValueError('Invalid Muse host')
                if time.time()-record.get('access_token_saved_at',0)>=10800:await self.refresh(record,root)
                self.state='connecting'
                vms,status=await asyncio.to_thread(muse_api.fetch_vms_with_status,record['access_token'],root)
                if status==401:
                    await self.refresh(record,root)
                    vms,status=await asyncio.to_thread(muse_api.fetch_vms_with_status,record['access_token'],root)
                if status!=200 or not vms:raise ConnectionError('Muse unavailable')
                vm=next((v for v in vms if v.get('is_default')),vms[0])
                vm_id=vm.get('vm_id') or vm.get('vm_name')
                if not isinstance(vm_id,str) or not vm_id:raise ValueError('Invalid VM')
                device=DeviceDescription(self.identity.node_id,'Mac Muse','1',{})
                self.session=ChatSession(noise_host=host,vm_id=vm_id,vm_auth_token=vm['vm_auth_token'],device=device,run_command=lambda *args:{'ok':False,'error':'unsupported'})
                session_stop=asyncio.Event();runner=asyncio.create_task(self.session.run(session_stop));self.state='connecting'
                stopper=asyncio.create_task(self.stop.wait())
                try:
                    async with asyncio.timeout(self.registration_timeout):
                        while self.session.registered_at is None and not runner.done() and not self.stop.is_set():await asyncio.sleep(.01)
                    if self.session.registered_at is not None:self.state='connected'
                    # Rotate at the 3h deadline, re-fetch per-VM auth on every connection.
                    expiry=max(1,10800-(time.time()-record.get('access_token_saved_at',0)))
                    done,_=await asyncio.wait((runner,stopper),timeout=expiry,return_when=asyncio.FIRST_COMPLETED)
                    if runner in done:
                        outcome=runner.result()
                        if outcome is Outcome.UNPAIRED:unpaired_signature=signature
                    else:session_stop.set();await asyncio.wait_for(runner,5)
                finally:
                    stopper.cancel();session_stop.set()
                    try:await asyncio.wait_for(asyncio.shield(runner),5)
                    except (Exception,asyncio.CancelledError):
                        runner.cancel()
                        with contextlib.suppress(asyncio.CancelledError,Exception):await runner
                delay=2
            except asyncio.CancelledError:raise
            except Exception:self.state='offline'
            finally:self.session=None
            if not self.stop.is_set():await self.pause(delay);delay=min(60,delay*2)
        self.state='stopped'
    async def pause(self,delay):
        with contextlib.suppress(asyncio.TimeoutError):await asyncio.wait_for(self.stop.wait(),delay)
