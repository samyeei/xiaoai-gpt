import contextlib,io,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from . import cli
from .core import InstallError,Journal

class LifecycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.home=self.root/'home';self.home.mkdir();self.args=['install','--speaker','192.168.100.10','--mac-ip','192.168.100.20','--non-interactive','--json']
  self.settings={'speaker':'192.168.100.10','mac_ip':'192.168.100.20','node':'/example/node','codex':'/example/codex'}
 def call(self,args):
  out=io.StringIO()
  with contextlib.redirect_stdout(out):code=cli.main(args,root=self.root,home=self.home)
  return code,json.loads(out.getvalue())
 def patches(self):
  stack=contextlib.ExitStack();self.addCleanup(stack.close)
  for key in ['validate_platform','check_ports','dependencies','prepare_models']:
   stack.enter_context(patch.object(cli,key))
  stack.enter_context(patch.object(cli,'discover',return_value=self.settings))
  stack.enter_context(patch.object(cli,'make_runtime',return_value='/example/copied-node'))
  stack.enter_context(patch.object(cli,'run',return_value=subprocess.CompletedProcess([],1,b'',b'')))
  stack.enter_context(patch.object(cli,'port_open',return_value=False))
  launch=stack.enter_context(patch.object(cli,'launch'))
  report={'services_ready':True,'connected':True,'active':False,'conversation_verified':False}
  stack.enter_context(patch.object(cli,'readiness',return_value=report))
  stack.enter_context(patch.object(cli,'require_idle'))
  ready=stack.enter_context(patch.object(cli,'await_ready',return_value=report))
  device=stack.enter_context(patch.object(cli,'Device')).return_value
  return launch,ready,device
 def test_complete_install_and_resume_preserve_credentials(self):
  launch,_,device=self.patches();code,result=self.call(self.args)
  self.assertEqual(code,0);self.assertTrue(result['installed']);self.assertFalse(result['conversation_verified']);self.assertEqual(device.activate.call_count,1)
  before=Journal(self.root,self.home).data;code,result=self.call(['install','--non-interactive'])
  self.assertEqual(code,0);self.assertEqual(device.activate.call_count,1);after=Journal(self.root,self.home).data;self.assertEqual(before['admin_key'],after['admin_key'])
  self.assertNotIn(after['admin_key'],json.dumps(result));self.assertEqual(launch.call_count,1)
 def test_activation_failure_restores_generated_files(self):
  launch,_,device=self.patches();device.activate.side_effect=InstallError('fake_device_failure')
  with patch.object(cli,'loaded_jobs',return_value=['owned-job']):code,result=self.call(self.args)
  self.assertEqual(code,1);self.assertEqual(result['error'],'fake_device_failure');self.assertFalse((self.root/'mac/codex-service/private/config.json').exists());self.assertFalse(Journal(self.root,self.home).data['installed']);self.assertEqual(launch.call_count,2)
 def test_status_is_read_only_before_install(self):
  code,result=self.call(['status']);self.assertEqual(code,0);self.assertFalse(result['installed']);self.assertFalse((self.root/'mac').exists())
 def test_mac_address_is_inferred_without_extra_user_prompt(self):
  self.patches()
  with patch.object(cli,'infer_mac_ip',return_value='192.168.100.20'):
   code,result=self.call(['install','--speaker','192.168.100.10','--non-interactive'])
  self.assertEqual(code,0);self.assertTrue(result['installed'])
 def test_uncertain_idle_never_stops_services_during_rollback(self):
  launch,_,device=self.patches();device.activate.side_effect=InstallError('fake_device_failure')
  with patch.object(cli,'loaded_jobs',return_value=['owned-job']),patch.object(cli,'require_idle',side_effect=InstallError('cannot_confirm_owned_services_idle')):
   code,result=self.call(self.args)
  self.assertEqual(code,1);self.assertEqual(result['error'],'installation_failed_recovery_required_use_same_checkout')
  self.assertEqual(launch.call_count,1);self.assertTrue(Journal(self.root,self.home).data['recovery_required'])
 def test_stop_then_uninstall_does_not_require_running_controls(self):
  launch,_,device=self.patches();self.assertEqual(self.call(self.args)[0],0)
  self.assertEqual(self.call(['stop'])[0],0)
  self.assertFalse(Journal(self.root,self.home).data['services_started'])
  self.assertEqual(self.call(['uninstall','--non-interactive'])[0],0)
  self.assertFalse(Journal(self.root,self.home).data['installed'])
 def test_installed_resume_refuses_modified_owned_configuration(self):
  launch,_,_=self.patches();self.assertEqual(self.call(self.args)[0],0)
  self.call(['stop']);calls=launch.call_count
  (self.root/'mac/codex-service/private/config.json').write_bytes(b'external change')
  with patch.object(cli,'readiness',return_value={'services_ready':False,'active':False}):code,result=self.call(['install','--non-interactive'])
  self.assertEqual(code,1);self.assertEqual(launch.call_count,calls)
 def test_settings_secrets_are_never_echoed(self):
  self.patches();p=self.root/'settings.json';p.write_text(json.dumps({'password':'do-not-print-this'}));p.chmod(0o600)
  code,result=self.call(['install','--settings',str(p),'--non-interactive']);self.assertEqual(code,1);self.assertNotIn('do-not-print-this',json.dumps(result))
if __name__=='__main__':unittest.main()
