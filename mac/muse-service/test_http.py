import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from service import JobService, JobError

class Backend:
    ready=True
    def __init__(self):self.calls=[];self.block=asyncio.Event()
    async def ask(self,text,session_id):self.calls.append((text,session_id));await self.block.wait();return 'final'

class JobFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.backend=Backend();self.service=JobService(Path(self.temp.name),self.backend)
        self.service.start()
    async def asyncTearDown(self):await self.service.close();self.temp.cleanup()

class JobTests(JobFixture):
    async def test_duplicates_conflicts_cancel_and_no_late_final(self):
        first=await self.service.submit('id','private question')
        self.assertEqual(await self.service.submit('id','private question'),first)
        with self.assertRaises(JobError):await self.service.submit('id','different')
        await asyncio.sleep(.01);await self.service.cancel('id');self.backend.block.set();await asyncio.sleep(.01)
        self.assertEqual(self.service.get('id')['status'],'cancelled');self.assertEqual(len(self.backend.calls),1)
        self.assertNotIn('private question',(Path(self.temp.name)/'jobs.json').read_text())
    async def test_restart_uncertain_no_replay_and_session_persisted(self):
        await self.service.submit('restart','hello');await asyncio.sleep(.01)
        saved=json.loads((Path(self.temp.name)/'jobs.json').read_text());self.assertEqual(saved['jobs']['restart']['status'],'running')
        fresh=JobService(Path(self.temp.name),self.backend)
        self.assertEqual(fresh.session_id,self.service.session_id);self.assertEqual(fresh.get('restart')['status'],'failed')
        await fresh.submit('restart','hello');self.assertEqual(len(self.backend.calls),1)
    async def test_bounded_queue_invalid_ids_text_and_success(self):
        for bad in ['', '../x', 'x'*129]:
            with self.assertRaises(JobError):await self.service.submit(bad,'hello')
        with self.assertRaises(JobError):await self.service.submit('x','你'*700)
        for i in range(8):await self.service.submit(str(i),'hello')
        with self.assertRaises(JobError):await self.service.submit('full','hello')
        self.backend.block.set();await asyncio.sleep(.03);self.assertEqual(self.service.get('0')['reply'],'final')

    async def test_cancelled_queue_does_not_admit_unstored_job(self):
        # Without yielding, fill queue then cancel entries that are still enqueued.
        for i in range(8):await self.service.submit('q'+str(i),'hello')
        for i in range(8):await self.service.cancel('q'+str(i))
        with self.assertRaises(JobError):await self.service.submit('new','hello')
        self.assertNotIn('new',self.service.jobs)
    async def test_running_ledger_failure_never_sends_and_worker_survives(self):
        from unittest.mock import patch
        await self.service.submit('disk','hello')
        original=self.service.persist
        def fail_once():
            self.service.persist=original
            raise OSError('synthetic disk failure')
        self.service.persist=fail_once
        await asyncio.sleep(.01)
        self.assertEqual(self.backend.calls,[])
        self.assertEqual(self.service.get('disk')['status'],'failed')
        self.assertFalse(self.service.worker.done())

from muse_http import JobHTTP

class HTTPTests(JobFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp();self.http=JobHTTP(self.service,port=0);await self.http.start();self.port=self.http.server.sockets[0].getsockname()[1]
    async def asyncTearDown(self):await self.http.close();await super().asyncTearDown()
    async def request(self,path,method='GET',body=None,key=None,extra=''):
        reader,writer=await asyncio.open_connection('127.0.0.1',self.port)
        data=b'' if body is None else json.dumps(body).encode()
        auth=self.service.config['key'] if key is None else key
        writer.write(f'{method} {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {auth}\r\nContent-Length: {len(data)}\r\n{extra}\r\n'.encode()+data);await writer.drain()
        raw=await reader.read();writer.close();await writer.wait_closed()
        head,_,content=raw.partition(b'\r\n\r\n');return int(head.split()[1]),json.loads(content)
    async def test_auth_every_route_and_no_exception_content(self):
        for path,method in [('/health','GET'),('/requests','POST'),('/requests/id','GET'),('/requests/id/cancel','POST')]:
            code,body=await self.request(path,method,key='BAD');self.assertEqual(code,401);self.assertEqual(body,{'error':'Muse request unavailable'})
        code,body=await self.request('/health');self.assertEqual(code,200);self.assertTrue(body['ready'])
        code,_=await self.request('/requests','POST',{'request_id':'http','text':'hello'});self.assertEqual(code,202)
        self.backend.block.set();await asyncio.sleep(.02)
        code,body=await self.request('/requests/http');self.assertEqual((code,body['reply']),(200,'final'))
        code,_=await self.request('/requests','POST',{'request_id':'http','text':'changed'});self.assertEqual(code,409)
    async def test_body_header_and_transfer_limits(self):
        code,_=await self.request('/requests','POST',{'request_id':'large','text':'z'*9000});self.assertEqual(code,413)
        code,_=await self.request('/requests','POST',{},extra='Transfer-Encoding: chunked\r\n');self.assertEqual(code,400)
        code,_=await self.request('/requests','POST',{});self.assertEqual(code,400)

    async def test_optional_digest_fences_prior_job_query_and_cancel(self):
        await self.service.submit('prior','original');await asyncio.sleep(.01)
        prior=self.service.jobs['prior'];self.assertEqual(prior['status'],'running')
        wrong='X-Request-Digest: '+'d'*64+'\r\n'
        for path,method in [('/requests/prior','GET'),('/requests/prior/cancel','POST')]:
            code,_=await self.request(path,method,extra=wrong);self.assertEqual(code,409)
        self.assertEqual(prior['status'],'running')
        correct='X-Request-Digest: '+prior['digest']+'\r\n'
        code,_=await self.request('/requests/prior',extra=correct);self.assertEqual(code,200)
        code,_=await self.request('/requests/prior/cancel','POST',extra=correct);self.assertEqual(code,200)
        self.assertEqual(prior['status'],'cancelled')
        code,_=await self.request('/requests/prior');self.assertEqual(code,200)

class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_unpaired_service_reads_new_pairing_and_manual_token_later(self):
        from unittest.mock import patch
        from service import MuseBackend
        from musegadget.link_client import Outcome
        from pair import save_private_json
        import service
        with tempfile.TemporaryDirectory() as directory:
            backend=MuseBackend(Path(directory));records=[];stop_run=asyncio.Event()
            class Session:
                def __init__(self,**kwargs):self.registered_at=None;records.append(kwargs)
                async def run(self,stop):self.registered_at=1;await stop.wait();return Outcome.STOPPED
            async def pause(delay):await asyncio.sleep(.002)
            backend.pause=pause
            def fetch(access,root):return ([{'vm_id':'vm','vm_auth_token':'synthetic','is_default':True}],200)
            def refresh(*args):
                self.assertEqual(args[1],backend.identity.node_id);self.assertEqual(args[3],'manual-synthetic');return ({'access_token':'new','refresh_token':'new-refresh'},200)
            with patch.object(service,'ChatSession',Session),patch.object(service.muse_api,'fetch_vms_with_status',fetch),patch.object(service.muse_api,'refresh_device_token',refresh),patch.object(service,'read_sdk_token',return_value='manual-synthetic') as token:
                task=asyncio.create_task(backend.run());await asyncio.sleep(.01)
                self.assertFalse(backend.ready);token.assert_not_called()
                save_private_json('pairing.json',{'access_token':'old','refresh_token':'old-refresh','access_token_saved_at':0},Path(directory))
                for _ in range(100):
                    if backend.ready:break
                    await asyncio.sleep(.002)
                self.assertTrue(backend.ready);self.assertEqual(len(records),1);token.assert_called_once()
                backend.stop.set();await asyncio.wait_for(task,1);self.assertFalse(backend.ready)
    async def test_reconnect_refetches_vm_without_retrying_job(self):
        from unittest.mock import patch
        from service import MuseBackend
        from musegadget.link_client import Outcome
        from pair import save_private_json
        import service,time
        with tempfile.TemporaryDirectory() as directory:
            backend=MuseBackend(Path(directory));count=0;selected=[]
            save_private_json('pairing.json',{'access_token':'synthetic','refresh_token':'synthetic','access_token_saved_at':time.time()},Path(directory))
            class Session:
                def __init__(self,**kwargs):self.registered_at=1;self.vm=kwargs['vm_id'];self.assert_vm();selected.append(self.vm)
                def assert_vm(self):assert self.vm=='name-fallback'
                async def run(self,stop):return Outcome.CLOSED
            def fetch(*args):
                nonlocal count
                count+=1
                if count==3:backend.stop.set()
                return ([{'vm_name':'name-fallback','vm_auth_token':'fresh-'+str(count)}],200)
            async def pause(delay):await asyncio.sleep(0)
            backend.pause=pause
            with patch.object(service,'ChatSession',Session),patch.object(service.muse_api,'fetch_vms_with_status',fetch):await asyncio.wait_for(backend.run(),1)
            self.assertEqual(count,3);self.assertEqual(selected,['name-fallback']*3)

    async def test_registration_deadline_stops_unregistered_session_and_reconnects(self):
        from unittest.mock import patch
        from service import MuseBackend
        from musegadget.link_client import Outcome
        from pair import save_private_json
        import service,time
        with tempfile.TemporaryDirectory() as directory:
            backend=MuseBackend(Path(directory));backend.registration_timeout=.01;sessions=[]
            save_private_json('pairing.json',{'access_token':'synthetic','refresh_token':'synthetic','access_token_saved_at':time.time()},Path(directory))
            class Session:
                def __init__(self,**kwargs):self.registered_at=None;self.stopped=False;sessions.append(self)
                async def run(self,stop):await stop.wait();self.stopped=True;return Outcome.STOPPED
            def fetch(*args):
                if len(sessions)==2:backend.stop.set()
                return ([{'vm_id':'vm','vm_auth_token':'synthetic'}],200)
            async def pause(delay):await asyncio.sleep(0)
            backend.pause=pause
            with patch.object(service,'ChatSession',Session),patch.object(service.muse_api,'fetch_vms_with_status',fetch):await asyncio.wait_for(backend.run(),1)
            self.assertGreaterEqual(len(sessions),2);self.assertTrue(all(s.stopped for s in sessions));self.assertFalse(backend.ready)
