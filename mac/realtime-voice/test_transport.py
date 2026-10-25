import asyncio
import unittest
from transport import candidate_summary, watch_task

class TransportTests(unittest.IsolatedAsyncioTestCase):
    def test_candidate_summary_retains_counts_and_never_addresses_or_credentials(self):
        sdp='a=ice-pwd:secret-password\r\na=candidate:1 1 UDP 1 192.168.100.106 9999 typ host\r\na=candidate:2 1 UDP 1 1.2.3.4 2222 typ srflx\r\n'
        result=candidate_summary(sdp)
        self.assertEqual(result,{'host':1,'srflx':1,'relay':0,'prflx':0,'udp':2,'tcp':0})
        self.assertNotIn('secret',str(result));self.assertNotIn('192.168',str(result))

    async def test_command_task_exception_is_reported_and_fails_immediately_without_sensitive_text(self):
        events=[];failures=[]
        async def bad_answer():
            raise ValueError('secret-sdp-and-password')
        task=asyncio.create_task(bad_answer());watch_task(task,events.append,failures.append)
        await asyncio.sleep(0);await asyncio.sleep(0)
        self.assertEqual(failures,['media_failed'])
        self.assertEqual(events,[{'type':'transport_diagnostic','phase':'commands','exception_type':'ValueError'}])
        self.assertNotIn('secret',str(events))

    async def test_normal_or_cancelled_command_task_does_not_claim_failure(self):
        events=[];failures=[]
        async def ok():return None
        task=asyncio.create_task(ok());watch_task(task,events.append,failures.append)
        await task;await asyncio.sleep(0)
        self.assertFalse(events);self.assertFalse(failures)
