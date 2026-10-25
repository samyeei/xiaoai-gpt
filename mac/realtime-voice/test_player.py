import unittest
from player import PlayerConfig, ActivityGate
class PlayerTests(unittest.TestCase):
 def test_only_fixed_device_and_owned_auth_paths(self):
  c=PlayerConfig('/project','diagnostic');a=c.command();self.assertIn('/project/.codex-runs/lx06-diagnostic/control',a);self.assertEqual(a[-1],'aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000')
  with self.assertRaises(ValueError):PlayerConfig('/project','other')
 def test_tail_after_player_drain_not_last_packet(self):
  g=ActivityGate();g.playing();self.assertFalse(g.can_listen(10));g.drained(10);self.assertFalse(g.can_listen(10.2));self.assertTrue(g.can_listen(10.5))
class PreflightTests(unittest.IsolatedAsyncioTestCase):
 async def test_preflight_opens_actual_aplay_and_drains_silence(self):
  from unittest.mock import AsyncMock,patch
  class Process:
   returncode=0
   wait=AsyncMock(return_value=0)
   communicate=AsyncMock(return_value=(b'',b''))
  p=Process()
  with patch('player.asyncio.create_subprocess_exec',AsyncMock(return_value=p)) as create:
   await PlayerConfig('/project').preflight()
   self.assertEqual(create.call_args.args[-1],'aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000')
   self.assertEqual(p.communicate.call_args.args[0],bytes(3840))
class DrainTests(unittest.IsolatedAsyncioTestCase):
 async def test_drain_closes_stdin_and_waits_without_writing_after_eof(self):
  from unittest.mock import AsyncMock,Mock
  from player import Player
  p=Mock();p.returncode=0;p.wait=AsyncMock(return_value=0);p.communicate=AsyncMock(side_effect=AssertionError('stdin already closed'))
  player=Player(None);player.process=p
  await player.drain();p.stdin.close.assert_called_once();p.wait.assert_awaited_once();self.assertIsNone(player.process)
 def test_managed_uses_same_rsa_key_as_provisioner(self):
  self.assertIn('/project/mac/realtime-voice/private/device_rsa',PlayerConfig('/project','managed').command())
class PlaybackDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
 async def test_actual_child_stderr_is_consumed_without_blocking_pcm_and_without_raw_storage(self):
  import sys
  from player import Player
  from output_diagnostics import OutputDiagnostics
  class Config:
   def command(self):return [sys.executable,'-c',"import sys;sys.stderr.write('underrun!!!\\n');sys.stderr.flush();sys.stdin.buffer.read()"]
  diagnostics=OutputDiagnostics();player=Player(Config());player.on_stderr=diagnostics.player_stderr;player.on_write=diagnostics.written
  await player.write(bytes(3840));await player.drain()
  self.assertEqual(diagnostics.snapshot()['player_underruns'],1)
  self.assertIsNone(player.process);self.assertIsNone(player.stderr_task)
