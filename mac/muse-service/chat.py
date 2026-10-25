"""Minimal final-reply subscription on the pinned SDK's encrypted transport."""
from __future__ import annotations
import asyncio
import contextlib
import json
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).parent/'vendor'))
from musegadget.link_client import LinkSession, _Request
from musegadget.noise import Header

MAX_BYTES=1024*1024

class Subscription:
    def __init__(self):
        loop=asyncio.get_running_loop();self.ready=loop.create_future();self.done=loop.create_future()
        self.buffer=bytearray();self.pending=[];self.parents=set();self.messages={};self.total=0
    def fail(self):
        for future in (self.ready,self.done):
            if not future.done():future.set_exception(ConnectionError('Muse unavailable'))
    def on_frame(self,frame):
        if self.done.done():return
        if frame.kind=='reset':self.fail();return
        if frame.kind=='response':
            if not 200<=frame.value.status<300:self.fail();return
            if not self.ready.done():self.ready.set_result(True)
            data,ended=frame.value.body,frame.value.end_body
        elif frame.kind=='body_chunk':data,ended=frame.value.data,frame.value.end_body
        else:self.fail();return
        self.total+=len(data);self.buffer.extend(data)
        if self.total>MAX_BYTES:self.fail();return
        while b'\n' in self.buffer:
            raw,_,tail=self.buffer.partition(b'\n');self.buffer=bytearray(tail)
            if not raw.strip():continue
            try:event=json.loads(raw)
            except (ValueError,UnicodeError):self.fail();return
            if not isinstance(event,dict):continue
            if not self.parents:
                if len(self.pending)>=64:self.fail();return
                self.pending.append(event)
            else:self.event(event)
        if ended:self.fail()
    def acknowledge(self,ack):
        if not isinstance(ack,dict):raise ConnectionError('Muse unavailable')
        row=ack.get('result',ack)
        if not isinstance(row,dict) or not isinstance(row.get('message_id'),str) or not row['message_id']:raise ConnectionError('Muse unavailable')
        self.parents={row['message_id']}
        # An ACK's own parent describes older history, not the current user turn.
        for event in self.pending:self.event(event)
        self.pending.clear()
    def event(self,event):
        name=event.get('event_name') or event.get('event') or event.get('type')
        row=event.get('payload',event)
        if not isinstance(row,dict) or ('role' in row and row['role']!='assistant'):return
        mid=row.get('message_id',row.get('id'));parent=row.get('reply_to_message_id',row.get('parent_message_id'))
        if not isinstance(mid,str) or not mid:return
        if name not in ('delta.message_start','delta.text_append','delta.message_done','message.assistant'):return
        if parent and parent not in self.parents:
            self.messages.pop(mid,None);return
        known=self.messages.get(mid)
        if not parent and known is None:return
        if known is None:
            if len(self.messages)>=64:self.fail();return
            known={'text':''};self.messages[mid]=known
        text=next((row[key] for key in ('display_text','content','text') if isinstance(row.get(key),str)),'')
        if name=='delta.text_append':known['text']+=text
        elif text:known['text']=text
        if len(known['text'].encode())>65536:self.fail();return
        if (name=='delta.message_done' or (name=='message.assistant' and row.get('display_text_ready') is True)) and known['text'].strip() and not self.done.done():self.done.set_result(known['text'])

class ChatSession(LinkSession):
    async def _invoke(self,message):
        # No execution hook is ever called, even for malicious unregistered invokes.
        if message.get('id'):await self.send({'method':'link.result','id':message['id'],'ok':False,'error':'unsupported'})
    async def ask(self,text,session_id,timeout=180):
        subscription=Subscription();ids=[]
        try:
            async with asyncio.timeout(timeout):
                # Side-chat subscription body is an explicit, unverified upstream assumption.
                encrypted=self._transport.encrypt_http_request('POST','/chat/subscribe',json.dumps({'session_id':session_id}).encode(),headers=[Header('Content-Type','application/json')])
                sid=encrypted.stream_id;ids.append(sid);self._requests[sid]=subscription
                await self._send_frames(encrypted.frames)
                await asyncio.wait_for(asyncio.shield(subscription.ready),15)
                encrypted=self._transport.encrypt_http_request('POST','/chat/stream',json.dumps({'message':text,'output_modality':'text','device_id':self._device.node_id,'session_id':session_id}).encode(),headers=[Header('Content-Type','application/json')])
                ack=_Request(asyncio.get_running_loop().create_future());sid=encrypted.stream_id;ids.append(sid);self._requests[sid]=ack
                await self._send_frames(encrypted.frames)
                status,body=await asyncio.wait_for(ack.done,60)
                if not 200<=status<300:raise ConnectionError('Muse unavailable')
                subscription.acknowledge(json.loads(body))
                return await subscription.done
        finally:
            for sid in ids:
                request=self._requests.pop(sid,None)
                if request and not request.done.done():request.done.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._send_frames(self._transport.encrypt_reset(sid)),2)
            for future in (subscription.ready,subscription.done):
                if not future.done():future.cancel()
                elif not future.cancelled():future.exception()
