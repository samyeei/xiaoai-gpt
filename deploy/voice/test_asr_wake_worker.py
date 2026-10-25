import asyncio,json,unittest,time,os
from unittest.mock import patch
import numpy as np
import worker
class IntegrationTests(unittest.IsolatedAsyncioTestCase):
 async def exercise(self,cancel=False,live=False,expired=False,kws_wins=False,permanent=False,config=None,asr_text=None,kws_label='HEY_LUKA'):
  packets=[];done=asyncio.Event()
  class Models:
   def __init__(self,*a):self.calls=0
   def stream(self):return object()
   def calibration_decoder(self,*a):return lambda data:None
   def keyword(self,*a):
    self.calls+=1
    return kws_label if kws_wins and self.calls==62 else None
   def transcribe(self,audio):
    if cancel or kws_wins:time.sleep(.08)
    return asr_text if asr_text is not None else ('Hey Luka' if live else '嘿，撸卡')
  class WS:
   async def send(self,p):packets.append(json.loads(p))
   async def close(self,*a):pass
   async def __aiter__(self):
    yield json.dumps({'type':'arm'} if live else {'type':'calibrate','session':'owned'})
    for data in [np.full(320,1000,dtype=np.int16)]*20+[np.zeros(320,dtype=np.int16)]*45:
     yield data.tobytes();await asyncio.sleep(.001)
    if cancel:yield json.dumps({'type':'pause'})
    await asyncio.sleep(.15)
  class Server:
   def __init__(self,handler,*a,**kw):self.handler=handler
   async def __aenter__(self):await self.handler(WS());done.set();return self
   async def __aexit__(self,*a):pass
  selected=config if config is not None else {'version':1,'routes':[{'label':'HEY_LUKA','backend':'codex','enabled':True,'phrases':['hey luka','嘿撸卡'],'kws_tokens':['HH','EY1']}]}
  with patch.object(worker,'load_config',return_value=selected),patch.object(worker,'Models',Models),patch.object(worker,'serve',Server),patch.dict(os.environ,{'ASR_WAKE_ENABLED':'1' if permanent else '0','ASR_WAKE_TEST_EXPIRES_AT':str(time.time()-1 if expired else time.time()+60) if live else '0'}):
   task=asyncio.create_task(worker.main());await asyncio.wait_for(done.wait(),3);task.cancel()
   with self.assertRaises(asyncio.CancelledError):await task
  return packets
 async def test_expiring_live_test_routes_exact_english_wake_once(self):
  packets=await self.exercise(live=True)
  self.assertEqual([p for p in packets if p['type']=='wake'],[{'type':'wake','keyword':'HEY_LUKA'}])
  self.assertFalse(any(p['type']=='text' for p in packets))
  self.assertNotIn('Hey Luka',str(packets))
 async def test_custom_config_controls_real_worker_asr_and_keyword_routes(self):
  c={'version':1,'routes':[{'label':'CUSTOM','backend':'codex','enabled':True,'phrases':['hey ming'],'kws_tokens':['HH']},{'label':'HEY_LUKA','backend':'codex','enabled':False,'phrases':['hey luka'],'kws_tokens':['HH']}]}
  for kws in [False,True]:
   packets=await self.exercise(live=True,config=c,asr_text='hey ming',kws_wins=kws,kws_label='CUSTOM')
   self.assertEqual([p for p in packets if p['type']=='wake'],[{'type':'wake','keyword':'CUSTOM'}])
  packets=await self.exercise(live=True,config=c,asr_text='hey luka',kws_wins=True)
  self.assertFalse(any(p['type']=='wake' for p in packets))
  self.assertNotIn('hey ming',str(packets))
 async def test_permanent_wake_works_after_test_expiry(self):
  packets=await self.exercise(live=True,expired=True,permanent=True)
  self.assertEqual(len([p for p in packets if p['type']=='wake']),1)
 async def test_live_candidate_expiry_disables_auxiliary_wake(self):
  packets=await self.exercise(live=True,expired=True)
  self.assertFalse(any(p['type']=='wake' for p in packets))
 async def test_live_test_cancel_ignores_pending_recognition(self):
  packets=await self.exercise(live=True,cancel=True)
  self.assertFalse(any(p['type']=='wake' for p in packets))
 async def test_keyword_wins_without_duplicate_auxiliary_wake(self):
  packets=await self.exercise(live=True,kws_wins=True)
  self.assertEqual(len([p for p in packets if p['type']=='wake']),1)
 async def test_shadow_asr_reports_counts_but_emits_no_wake_or_transcript(self):
  packets=await self.exercise()
  self.assertFalse(any(p['type'] in ('wake','text') for p in packets))
  self.assertNotIn('嘿，撸卡',str(packets))
  reports=[p['data']['calibration'] for p in packets if 'calibration' in p.get('data',{})]
  self.assertEqual(reports[-1]['asr_shadow_wakes'],1)
  self.assertEqual(reports[-1]['calibration_id'],'owned')
 async def test_cancelled_calibration_ignores_late_asr_result(self):
  packets=await self.exercise(cancel=True)
  reports=[p['data']['calibration'] for p in packets if 'calibration' in p.get('data',{})]
  self.assertTrue(reports)
  self.assertTrue(all(r['asr_shadow_wakes']==0 for r in reports))
  self.assertFalse(any(p['type'] in ('wake','text') for p in packets))
 async def test_current_public_wake_routes_real_worker_to_single_gpt(self):
  packets=await self.exercise(live=True,config=worker.load_config(),asr_text='你好GPT')
  self.assertEqual([p for p in packets if p['type']=='wake'],[{'type':'wake','keyword':'HEY_GPT'}])

if __name__=='__main__':unittest.main()
