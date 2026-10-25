import subprocess,tempfile,unittest,json
from .environment import platform as environment_platform
from pathlib import Path
from unittest.mock import patch
from .environment import validate_platform, check_ports, schema_support, discover, make_runtime, dependencies
from .core import Journal,InstallError
class EnvironmentTests(unittest.TestCase):
 def test_older_macos_blocks_before_any_dependency_work(self):
  with patch.object(environment_platform,'mac_ver',return_value=('13.6.9',('','',''),'arm64')):
   with self.assertRaisesRegex(InstallError,'requires_macos_14_or_later'):validate_platform('Darwin','arm64')
 def test_unsupported_platform_is_explicit(self):
  for system,machine in [('Linux','aarch64'),('Darwin','x86_64')]:
   with self.assertRaises(InstallError):validate_platform(system,machine)
 def test_schema_requires_actual_realtime_v3_webrtc(self):
  self.assertFalse(schema_support('thread/realtime/start'))
  self.assertFalse(schema_support('thread/realtime/start v3'))
  request={'oneOf':[{'properties':{'method':{'enum':['thread/realtime/start']},'params':{'$ref':'#/definitions/ThreadRealtimeStartParams'}}}],
   'definitions':{'ThreadRealtimeStartParams':{'properties':{'version':{'$ref':'#/definitions/RealtimeConversationVersion'},'transport':{'$ref':'#/definitions/ThreadRealtimeStartTransport'},'voice':{'$ref':'#/definitions/RealtimeVoice'}}},
   'RealtimeConversationVersion':{'enum':['v3']},'ThreadRealtimeStartTransport':{'oneOf':[{'properties':{'type':{'enum':['webrtc']},'sdp':{'type':'string'}}}]},'RealtimeVoice':{'enum':['maple']}}}
  self.assertTrue(schema_support(json.dumps(request)))
  request['definitions']['ThreadRealtimeStartParams']['properties'].pop('voice')
  self.assertFalse(schema_support(json.dumps(request)))
 def test_ports_closed_and_conflicts_reported(self):
  check_ports(lambda port:False)
  with self.assertRaises(InstallError):check_ports(lambda port:port==4399)
 def test_unrelated_schema_tokens_do_not_imply_realtime_support(self):
  self.assertFalse(schema_support('{"method":"thread/realtime/start","unrelated":["v3","webrtc","voice"]}'))
 def test_interrupted_venv_creation_records_owned_intent_for_resume(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root);home=p/'home';home.mkdir();j=Journal(p,home)
   def interrupted(args,**_):
    if args[1:3]==['-m','venv']:
     Path(args[3]).mkdir(parents=True,exist_ok=True)
     raise RuntimeError('interrupted venv')
    return subprocess.CompletedProcess(args,0,b'')
   with self.assertRaises(RuntimeError):dependencies(j,interrupted)
   resumed=Journal(p,home)
   self.assertIn('mac-voice-env',resumed.data.get('environments',[]))
 def test_interrupted_signed_bundle_copy_resumes_owned_bundle(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root);home=p/'home';home.mkdir();source=p/'node';source.write_bytes(b'binary');j=Journal(p,home)
   def run(args,**_):
    if args[1:3]==['--verify','--strict']:
     app=Path(args[-1]);complete=(app/'Contents/MacOS/node').exists() and (app/'Contents/Info.plist').exists()
     return subprocess.CompletedProcess(args,0 if complete else 1,b'')
    return subprocess.CompletedProcess(args,0,b'')
   real=j.write;count=0
   def interrupted(path,data,**kwargs):
    nonlocal count
    count+=1
    if count==2:raise RuntimeError('interrupted copy')
    return real(path,data,**kwargs)
   with patch.object(j,'write',side_effect=interrupted):
    with self.assertRaises(RuntimeError):make_runtime(j,source,run)
   resumed=Journal(p,home)
   self.assertEqual(make_runtime(resumed,source,run),str(resumed.home/'Applications'/('Xiaoai GPT '+j.data['id']+'.app')/'Contents/MacOS/node'))
 def test_resigned_but_modified_owned_runtime_is_refused(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root);home=p/'home';home.mkdir();source=p/'node';source.write_bytes(b'binary');j=Journal(p,home)
   run=lambda args,**_:subprocess.CompletedProcess(args,0,b'')
   binary=Path(make_runtime(j,source,run));binary.write_bytes(b'foreign binary')
   with self.assertRaises(InstallError):make_runtime(j,source,run)
if __name__=='__main__':unittest.main()
