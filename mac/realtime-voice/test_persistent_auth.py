import unittest
from persistent_auth import validate_root_state, validate_hook, ROOT_GATE, STARTUP, HOOK, ROLLBACK, validate_key_location
class PersistentAuthTests(unittest.TestCase):
 def test_only_empty_or_exact_owned_mount_is_allowed(self):
  validate_root_state([],None)
  validate_root_state(['.ssh'],'/xiaoai-voice-auth/root')
  for entries,source in [(['profile'],None),([], '/other/root')]:
   with self.assertRaises(ValueError):validate_root_state(entries,source)
 def test_existing_unrelated_hook_is_not_replaced(self):
  validate_hook(None);validate_hook(HOOK)
  with self.assertRaises(ValueError):validate_hook('# existing user startup\n')
 def test_device_scripts_parse_and_startup_avoids_broad_process_kills(self):
  import subprocess
  for script in [ROOT_GATE,STARTUP,HOOK]:
   self.assertEqual(subprocess.run(['sh','-n'],input=script.encode(),capture_output=True).returncode,0)
  import re
  self.assertFalse(any(re.match(r'\s*(kill|killall)\b',line) for line in STARTUP.splitlines()))
  self.assertIn('/proc/[0-9]*/cmdline',STARTUP)
  self.assertIn('exit 0',STARTUP)
 def test_actual_root_gate_rejects_nonempty_unmounted_directory(self):
  import subprocess,tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)/'root';root.mkdir();mountinfo=Path(folder)/'mountinfo';mountinfo.write_text('')
   script=ROOT_GATE.replace('/proc/self/mountinfo',str(mountinfo)).replace('/root',str(root))
   p=subprocess.run(['sh','-c',script],capture_output=True);self.assertEqual(p.stdout,b'EMPTY\n')
   (root/'existing').write_text('preserve')
   p=subprocess.run(['sh','-c',script],capture_output=True);self.assertNotEqual(p.returncode,0)
   self.assertEqual((root/'existing').read_text(),'preserve')

class AuthLocationTests(unittest.TestCase):
 def test_firmware_fixed_key_path_stops_root_installer(self):
  validate_key_location('HOME')
  with self.assertRaises(ValueError):validate_key_location('FIXED_ETC')
 def test_rollback_leaves_mounted_directory_before_unmount(self):
  self.assertIn('cd /; umount /root',ROLLBACK)
