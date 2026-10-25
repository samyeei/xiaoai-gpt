"""Bounded one-request asyncio HTTP server; loopback and bearer authentication only."""
import asyncio
import contextlib
import hmac
import json
import re
from service import JobError

class JobHTTP:
    def __init__(self,service,port=4414):
        self.service=service;self.port=port;self.server=None;self.tasks=set();self.writers=set()
    async def start(self):self.server=await asyncio.start_server(self.accept,'127.0.0.1',self.port,limit=4096,backlog=32)
    def accept(self,reader,writer):
        if len(self.tasks)>=32:writer.close();return
        task=asyncio.create_task(self.handle(reader,writer));self.tasks.add(task);self.writers.add(writer)
        task.add_done_callback(self.tasks.discard)
    async def handle(self,reader,writer):
        code=400;result={'error':'Muse request unavailable'}
        try:
            async with asyncio.timeout(5):
                line=await reader.readline()
                if len(line)>4096:raise JobError(413)
                method,path,version=line.decode('ascii').strip().split(' ')
                if version!='HTTP/1.1' or method not in ('GET','POST'):raise JobError()
                headers={};total=len(line)
                while True:
                    line=await reader.readline();total+=len(line)
                    if not line or total>8192:raise JobError(413)
                    if line==b'\r\n':break
                    name,value=line.decode('ascii').strip().split(':',1);name=name.lower()
                    if name in headers:raise JobError()
                    headers[name]=value.strip()
                if not hmac.compare_digest(headers.get('authorization',''),'Bearer '+self.service.config['key']):raise JobError(401)
                if 'transfer-encoding' in headers:raise JobError()
                length=headers.get('content-length','0')
                if not re.fullmatch('[0-9]{1,8}',length):raise JobError()
                length=int(length)
                if length>8192:raise JobError(413)
                data=await reader.readexactly(length)
                if method=='GET' and length:raise JobError()
                if method=='GET' and path=='/health':code,result=200,self.service.health()
                elif method=='POST' and path=='/requests':
                    body=json.loads(data)
                    if not isinstance(body,dict) or set(body)!={'request_id','text'}:raise JobError()
                    result=await self.service.submit(body['request_id'],body['text']);code=202
                else:
                    match=re.fullmatch('/requests/([A-Za-z0-9_-]{1,128})(/cancel)?',path)
                    if not match:raise JobError(404)
                    request_id,cancel=match.groups()
                    digest=headers.get('x-request-digest')
                    if digest is not None:
                        job=self.service.jobs.get(request_id)
                        if not re.fullmatch('[a-f0-9]{64}',digest) or not job or not hmac.compare_digest(digest,job['digest']):raise JobError(409)
                    if method=='GET' and not cancel:result=self.service.get(request_id)
                    elif method=='POST' and cancel and not data:result=await self.service.cancel(request_id)
                    else:raise JobError(404)
                    code=200
        except JobError as error:code=error.status
        except (ValueError,UnicodeError,asyncio.IncompleteReadError):code=400
        except asyncio.TimeoutError:code=408
        except asyncio.CancelledError:raise
        except Exception:code=503
        finally:
            with contextlib.suppress(Exception):
                payload=json.dumps(result,separators=(',',':')).encode()
                writer.write(f'HTTP/1.1 {code} Result\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n'.encode()+payload)
                await asyncio.wait_for(writer.drain(),1)
            writer.close();self.writers.discard(writer)
            with contextlib.suppress(Exception):await asyncio.wait_for(writer.wait_closed(),1)
    async def close(self):
        if self.server:self.server.close();await self.server.wait_closed()
        for task in list(self.tasks):task.cancel()
        for writer in list(self.writers):writer.close()
        if self.tasks:await asyncio.gather(*list(self.tasks),return_exceptions=True)
