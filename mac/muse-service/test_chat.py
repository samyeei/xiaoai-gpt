"""Offline encrypted wire tests. Pipe/FakeVm adapted from Meta SDK Apache-2.0 tests.
Copyright (c) Meta Platforms, Inc. and affiliates. Licensed Apache-2.0;
see vendor/LICENSE. No live Muse subscription behavior is claimed here.
"""
import asyncio
import json
import unittest
from chat import ChatSession
from musegadget.link_client import DeviceDescription, MessageDecoder
from musegadget.noise import ApplicationResponse, BodyChunk, NoiseFrameDecoder, NoiseXXResponder, ServiceFrame, encode_noise_frames
from musegadget.noise.transport import decode_request_envelope, encode_response_envelope

class Pipe:
    def __init__(self, inbox, outbox): self.inbox,self.outbox=inbox,outbox
    async def send(self,data): await self.outbox.put(data)
    async def recv(self):
        data=await self.inbox.get()
        if data is None: raise ConnectionError('closed')
        return data
    async def close(self): await self.outbox.put(None)

class FakeVm:
    def __init__(self,ws): self.ws=ws;self.decoder=NoiseFrameDecoder()
    async def handshake(self):
        responder=NoiseXXResponder();responder.initialize()
        await self.ws.send(responder.read_message1_and_write_message2(await self.ws.recv()))
        responder.read_message3(await self.ws.recv());self.send_cipher,self.recv_cipher=responder.split()
    async def frame(self):
        while True:
            decoded=self.decoder.decode(self.recv_cipher.decrypt_with_ad(b'',await self.ws.recv()))
            if decoded is not None: return decode_request_envelope(decoded)
    async def send(self,frame):
        for chunk in encode_noise_frames(encode_response_envelope(frame)):
            await self.ws.send(self.send_cipher.encrypt_with_ad(b'',chunk))
    async def response(self,sid,body=b'',end=False,status=200):
        await self.send(ServiceFrame.response(sid,ApplicationResponse(status=status,body=body,end_body=end)))
    async def event(self,sid,event,split=False):
        raw=json.dumps(event).encode()+b'\n'
        chunks=[raw[:9],raw[9:]] if split else [raw]
        for chunk in chunks: await self.send(ServiceFrame.body_chunk(sid,BodyChunk(data=chunk)))

class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        a,b=asyncio.Queue(),asyncio.Queue();self.vm=FakeVm(Pipe(b,a))
        async def connect(*args): return Pipe(a,b)
        self.session=ChatSession(noise_host='hatch.metaaivm.com',vm_id='vm',vm_auth_token='synthetic',device=DeviceDescription('node','Mac','1',{}),run_command=lambda *a:{'ok':False,'error':'unsupported'},connect=connect)
        self.stop=asyncio.Event();self.runner=asyncio.create_task(self.session.run(self.stop))
        await self.vm.handshake();control=await self.vm.frame();self.control=control.stream_id
        await self.vm.response(self.control)
        register=MessageDecoder().feed((await self.vm.frame()).value.data)[0]
        assert register['params']['commands_v2']=={}
        from musegadget.link_client import encode_message
        await self.vm.send(ServiceFrame.body_chunk(self.control,BodyChunk(data=encode_message({'type':'res','id':register['id'],'ok':True}))))
        await asyncio.sleep(0)
    async def asyncTearDown(self):
        self.stop.set();await asyncio.wait_for(self.runner,2)
    async def start_chat(self):
        task=asyncio.create_task(self.session.ask('hello','side',timeout=1))
        subscribe=await self.vm.frame();self.assertEqual(subscribe.value.path,'/chat/subscribe')
        self.assertEqual(json.loads(subscribe.value.body),{'session_id':'side'})
        # Sending cannot happen until subscription HTTP success.
        with self.assertRaises(asyncio.TimeoutError): await asyncio.wait_for(self.vm.frame(),.01)
        await self.vm.response(subscribe.stream_id)
        sent=await self.vm.frame();self.assertEqual(sent.value.path,'/chat/stream')
        self.assertEqual(json.loads(sent.value.body)['session_id'],'side')
        return task,subscribe.stream_id,sent.stream_id
    async def test_real_noise_split_final_before_ack_correlated_only(self):
        task,sid,send=await self.start_chat()
        await self.vm.event(sid,{'type':'message.assistant','message_id':'bad','reply_to_message_id':'other','text':'wrong'})
        await self.vm.event(sid,{'type':'delta.message_start','message_id':'answer','parent_message_id':'user'})
        await self.vm.event(sid,{'type':'delta.text_append','message_id':'answer','text':'final '},True)
        await self.vm.event(sid,{'type':'delta.message_done','message_id':'answer','text':'final reply'},True)
        await asyncio.sleep(.01);self.assertFalse(task.done())
        await self.vm.response(send,b'{"message_id":"user"}',True)
        self.assertEqual(await task,'final reply')
        self.assertEqual((await self.vm.frame()).kind,'reset')
    async def test_unknown_unparented_final_and_partial_do_not_complete(self):
        task,sid,send=await self.start_chat();await self.vm.response(send,b'{"message_id":"user"}',True)
        await self.vm.event(sid,{'type':'message.assistant','text':'unrelated'})
        await self.vm.event(sid,{'type':'delta.text_append','message_id':'a','reply_to_message_id':'user','text':'partial'})
        await asyncio.sleep(.01);self.assertFalse(task.done());task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual((await self.vm.frame()).kind,'reset')
    async def test_disconnect_is_uncertain_and_never_resends(self):
        task,sid,send=await self.start_chat();await self.vm.ws.close()
        with self.assertRaises(ConnectionError): await task
    async def test_subscription_rejection_never_sends_question(self):
        task=asyncio.create_task(self.session.ask('hello','side',timeout=.2));sub=await self.vm.frame()
        await self.vm.response(sub.stream_id,end=True,status=403)
        with self.assertRaises(ConnectionError):await task
        self.assertEqual((await self.vm.frame()).kind,'reset')

    async def test_official_nested_event_format_and_utf8_chunks(self):
        task,sid,send=await self.start_chat()
        await self.vm.response(send,b'{"result":{"message_id":"user"}}',True)
        await self.vm.event(sid,{'type':'event','event_name':'message.assistant','payload':{'message_id':'a','reply_to_message_id':'user','display_text':'你好','display_text_ready':False}},True)
        await asyncio.sleep(.01);self.assertFalse(task.done())
        await self.vm.event(sid,{'type':'event','event_name':'message.assistant','payload':{'message_id':'a','reply_to_message_id':'user','display_text':'你好','display_text_ready':True}},True)
        self.assertEqual(await task,'你好')
    async def test_invoke_is_denied_without_calling_executor(self):
        from musegadget.link_client import encode_message
        def forbidden(*args):self.fail('Executor must never run')
        self.session._run_command=forbidden
        await self.vm.send(ServiceFrame.body_chunk(self.control,BodyChunk(data=encode_message({'method':'link.invoke','id':'attack','command':'system.run','params':{'command':'private'}}))))
        response=MessageDecoder().feed((await self.vm.frame()).value.data)[0]
        self.assertEqual(response,{'method':'link.result','id':'attack','ok':False,'error':'unsupported'})
    async def test_reply_timeout_resets_both_streams(self):
        task=asyncio.create_task(self.session.ask('hello','side',timeout=.03));sub=await self.vm.frame();await self.vm.response(sub.stream_id)
        sent=await self.vm.frame();await self.vm.response(sent.stream_id,b'{"message_id":"user"}',True)
        with self.assertRaises(asyncio.TimeoutError):await task
        self.assertEqual((await self.vm.frame()).kind,'reset');self.assertEqual((await self.vm.frame()).kind,'reset')
    async def test_ack_older_parent_never_accepts_sibling_or_history_final(self):
        task,sid,send=await self.start_chat()
        await self.vm.response(send,b'{"message_id":"new-user","reply_to_message_id":"old-parent"}',True)
        await self.vm.event(sid,{'type':'message.assistant','message_id':'stale','reply_to_message_id':'old-parent','text':'stale','display_text_ready':True})
        await asyncio.sleep(.01);self.assertFalse(task.done())
        await self.vm.event(sid,{'type':'message.assistant','message_id':'current','reply_to_message_id':'new-user','text':'current','display_text_ready':True})
        self.assertEqual(await task,'current')

    async def test_full_assistant_needs_explicit_readiness_and_user_role_is_ignored(self):
        task,sid,send=await self.start_chat();await self.vm.response(send,b'{"message_id":"user"}',True)
        await self.vm.event(sid,{'type':'message.assistant','message_id':'a','reply_to_message_id':'user','text':'not final'})
        await self.vm.event(sid,{'type':'delta.message_done','message_id':'b','reply_to_message_id':'user','text':'user text','role':'user'})
        await asyncio.sleep(.01);self.assertFalse(task.done())
        await self.vm.event(sid,{'type':'message.assistant','message_id':'a','reply_to_message_id':'user','text':'ready','display_text_ready':True})
        self.assertEqual(await task,'ready')
