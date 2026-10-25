import json, tempfile, unittest, plistlib
from pathlib import Path
from unittest.mock import Mock
from .core import Journal, InstallError
from .lifecycle import configure, job_plists, readiness, busy, await_ready
from unittest.mock import patch

class InstallTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.home=self.root/'home';self.home.mkdir();self.j=Journal(self.root,self.home)
  (self.root/'config').mkdir();(self.root/'config/wake-words.json').write_text('{"custom":"preserve"}')
  self.settings={'speaker':'192.168.100.10','mac_ip':'192.168.100.20','node':'/example/node','codex':'/example/codex'}
 def test_generated_configuration_is_private_portable_and_idempotent(self):
  configure(self.j,self.settings)
  conf=self.root/'mac/codex-service/private/config.json';first=conf.read_bytes();configure(self.j,self.settings)
  self.assertEqual(conf.read_bytes(),first);self.assertEqual(conf.stat().st_mode&0o777,0o600)
  self.assertEqual(json.loads((self.root/'config/wake-words.json').read_text()),{'custom':'preserve'})
  self.assertFalse((self.root/'config/speakers.json').exists())
  registry=json.loads((self.root/'mac/installer/private/speakers.json').read_text());self.assertEqual(registry['mode'],'single');self.assertEqual(registry['devices'][0]['ip'],self.settings['speaker'])
  runtime=json.loads((self.root/'mac/installer/private/runtime.json').read_text());self.assertFalse(runtime['muse_enabled'])
 def test_plists_scope_controls_and_inherit_private_registry(self):
  configure(self.j,self.settings);plists=job_plists(self.j,self.settings)
  self.assertEqual(len(plists),3)
  for name,body in plists.items():
   p=plistlib.loads(body);self.assertIn(self.j.data['id'],p['Label']);self.assertEqual(p['WorkingDirectory'],str(self.root));self.assertTrue(p['EnvironmentVariables']['SPEAKERS_CONFIG'].endswith('/private/speakers.json'));self.assertNotIn('key',p['EnvironmentVariables'])
 def test_foreign_private_config_refused(self):
  p=self.root/'mac/codex-service/private/config.json';p.parent.mkdir(parents=True);p.write_bytes(b'foreign')
  with self.assertRaises(InstallError):configure(self.j,self.settings)
  self.assertEqual(p.read_bytes(),b'foreign')
 def test_health_is_not_human_acceptance(self):
  fetch=Mock(side_effect=[{'voice':{'state':'idle','speaker_connected':True,'models_ready':True}},{'codex':{'ready':True}},{'active':False},{'active':False}])
  s=readiness(self.j,fetch);self.assertTrue(s['connected']);self.assertFalse(s['conversation_verified'])
 def test_busy_refuses_stop_on_active_or_pending(self):
  self.assertTrue(busy({'pending':True}));self.assertTrue(busy({'voice':{'state':'waiting'}}));self.assertFalse(busy({'voice':{'state':'idle'}}))
 def test_connected_without_pcm_never_passes_install_acceptance(self):
  report={'services_ready':True,'connected':True,'pcm_received':False,'active':False,'conversation_verified':False}
  with patch('tools.installer.lifecycle.readiness',return_value=report),patch('tools.installer.lifecycle.time.monotonic',side_effect=[0,0,2]),patch('tools.installer.lifecycle.time.sleep'):
   with self.assertRaises(InstallError):await_ready(self.j,seconds=1)
  report['pcm_received']=True
  with patch('tools.installer.lifecycle.readiness',return_value=report):self.assertEqual(await_ready(self.j),report)
  self.assertFalse(busy({'voice':{'state':'idle'},'native_voice':None,'realtime_voice':None}))
 def test_foreign_log_directory_is_refused_and_owned_log_contents_are_not_journaled(self):
  from .lifecycle import install_jobs
  logs=self.home/'Library/Logs/xiaoai-gpt'/self.j.data['id']/'native';logs.mkdir(parents=True)
  with self.assertRaises(InstallError):install_jobs(self.j,self.settings)
  self.assertFalse((self.home/'Library/LaunchAgents').exists())
  import shutil
  shutil.rmtree(logs)
  install_jobs(self.j,self.settings)
  stdout=logs/'stdout.log';stdout.write_text('runtime log')
  self.j.rollback();self.assertEqual(stdout.read_text(),'runtime log')
  install_jobs(self.j,self.settings);self.assertEqual(stdout.read_text(),'runtime log')
if __name__=='__main__':unittest.main()
