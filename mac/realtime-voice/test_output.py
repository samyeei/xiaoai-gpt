import unittest,numpy as np
from unittest.mock import AsyncMock,Mock,patch
from player import ActivityGate
from output import OutputSink
class OutputTests(unittest.IsolatedAsyncioTestCase):
 def fixture(self,**kwargs):
  events=[];player=Mock(process=None);gate=ActivityGate();queue=Mock()
  async def write(data):player.process=object()
  async def drain():self.assertTrue(gate.active);player.process=None
  player.write=AsyncMock(side_effect=write);player.drain=AsyncMock(side_effect=drain)
  return OutputSink(player,gate,queue,events.append,**kwargs),player,gate,events
 async def test_prebuffer_holds_first_600ms_and_preserves_all_pcm_in_order(self):
  sink,player,gate,events=self.fixture()
  for value in range(1,30):await sink.feed(np.full(960,value*100,dtype=np.int16))
  self.assertTrue(gate.active);player.write.assert_not_awaited();self.assertEqual(events,[{'type':'playing'}])
  await sink.feed(np.full(960,3000,dtype=np.int16))
  player.write.assert_awaited_once()
  expected=np.repeat(np.arange(1,31,dtype=np.int16)*100,960*2)
  np.testing.assert_array_equal(np.frombuffer(player.write.call_args.args[0],dtype='<i2'),expected)
  await sink.feed(np.full(960,3100,dtype=np.int16))
  self.assertEqual(player.write.await_count,2)
 async def test_short_answer_is_flushed_on_end_and_gate_waits_for_actual_drain(self):
  sink,player,gate,events=self.fixture()
  await sink.feed(np.full(960,1000,dtype=np.int16));player.write.assert_not_awaited()
  with patch('output.asyncio.sleep',AsyncMock()):await sink.drain()
  player.write.assert_awaited_once();player.drain.assert_awaited_once();self.assertFalse(gate.active);self.assertEqual(events,[{'type':'playing'},{'type':'listening'}])
  with patch('output.asyncio.sleep',AsyncMock()):await sink.drain()
  self.assertEqual(player.drain.await_count,1)
 async def test_trailing_silence_flushes_short_answer_and_next_answer_prebuffers_again(self):
  sink,player,gate,events=self.fixture()
  with patch('output.asyncio.sleep',AsyncMock()):
   await sink.feed(np.full(960,1000,dtype=np.int16))
   for _ in range(25):await sink.feed(np.zeros(960,dtype=np.int16))
  player.drain.assert_awaited_once();self.assertFalse(gate.active)
  player.write.reset_mock();await sink.feed(np.full(960,2000,dtype=np.int16));player.write.assert_not_awaited();self.assertTrue(gate.active)
 async def test_idle_silence_does_not_open_player_or_claim_playback(self):
  sink,player,gate,events=self.fixture()
  await sink.feed(np.zeros(960,dtype=np.int16));player.write.assert_not_awaited();self.assertEqual(events,[])
 async def test_gain_applies_to_buffered_short_answers(self):
  sink,player,gate,events=self.fixture(gain=4)
  await sink.feed(np.full(960,1000,dtype=np.int16))
  with patch('output.asyncio.sleep',AsyncMock()):await sink.drain()
  self.assertTrue(np.all(np.frombuffer(player.write.call_args.args[0],dtype='<i2')==4000))
 async def test_400ms_bursty_arrivals_do_not_starve_playback_after_prebuffer(self):
  now=0;remaining=0;last_write=None;underruns=0
  sink,player,gate,events=self.fixture()
  async def write(data):
   nonlocal remaining,last_write,underruns
   if last_write is not None:
    remaining-=now-last_write
    if remaining<-.001:underruns+=1
   remaining=max(0,remaining)+len(data)/(48000*4);last_write=now;player.process=object()
  player.write.side_effect=write
  for n in range(250):
   now=max(now,n*.02+(.4 if n%50>=40 else 0))
   await sink.feed(np.full(960,1000,dtype=np.int16))
  self.assertGreater(player.write.await_count,100);self.assertEqual(underruns,0)
 async def test_configured_reserve_holds_2400ms_without_losing_or_repeating_pcm(self):
  sink,player,gate,events=self.fixture(buffer_ms=2400)
  for _ in range(119):await sink.feed(np.full(960,1000,dtype=np.int16))
  player.write.assert_not_awaited();self.assertTrue(gate.active)
  await sink.feed(np.full(960,1000,dtype=np.int16))
  player.write.assert_awaited_once();self.assertEqual(len(player.write.call_args.args[0]),2400*192)
 def test_buffer_is_bounded_and_rejects_invalid_values(self):
  for value in [0,99,3001,True,'2400',float('nan')]:
   with self.assertRaises(ValueError):self.fixture(buffer_ms=value)
 async def test_long_answer_supply_deficit_exhausts_old_buffer_but_not_configured_reserve(self):
  async def simulate(buffer_ms):
   sink,player,gate,events=self.fixture(buffer_ms=buffer_ms)
   now=0;remaining=0;last=None;under=0
   async def write(data):
    nonlocal remaining,last,under
    if last is not None:
     remaining-=now-last
     if remaining<-.001:under+=1
    remaining=max(0,remaining)+len(data)/192000;last=now;player.process=object()
   player.write.side_effect=write
   for n in range(1200):
    now=n*.0216
    await sink.feed(np.full(960,1000,dtype=np.int16))
   return under
  self.assertGreater(await simulate(600),0)
  self.assertEqual(await simulate(2400),0)
