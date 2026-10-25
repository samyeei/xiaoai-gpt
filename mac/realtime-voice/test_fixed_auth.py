import subprocess,tempfile,unittest
from pathlib import Path
from fixed_auth import SETUP,GATE,STARTUP,ROLLBACK
class FixedAuthTests(unittest.TestCase):
 def test_original_keys_preserved_and_candidate_idempotent(self):
  with tempfile.TemporaryDirectory() as folder:
   base=Path(folder);target=base/'original';target.write_text('old-key-one\nold-key-two')
   d=base/'managed'
   script=SETUP.replace('/data/xiaoai-voice-auth',str(d)).replace('/etc/dropbear/authorized_keys',str(target))
   for _ in range(2):
    p=subprocess.run(['sh','-c',script],input=b'new-restricted-key\n',capture_output=True);self.assertEqual(p.returncode,0,p.stderr)
   self.assertEqual(target.read_text(),'old-key-one\nold-key-two')
   self.assertEqual((d/'authorized_keys').read_text(),'old-key-one\nold-key-two\nnew-restricted-key\n')
   target.write_text('changed-original')
   p=subprocess.run(['sh','-c',script],input=b'new-restricted-key\n',capture_output=True);self.assertNotEqual(p.returncode,0)
 def test_foreign_file_mount_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   info=Path(folder)/'mountinfo';info.write_text('1 2 0:1 /other/key /etc/dropbear/authorized_keys rw - tmpfs tmpfs rw\n')
   p=subprocess.run(['sh','-c',GATE.replace('/proc/self/mountinfo',str(info))],capture_output=True)
   self.assertNotEqual(p.returncode,0)
 def test_scripts_parse_and_bind_only_single_key_file(self):
  for s in [SETUP,GATE,STARTUP,ROLLBACK]:self.assertEqual(subprocess.run(['sh','-n'],input=s.encode(),capture_output=True).returncode,0)
  self.assertIn('mount -o bind "$task_dir/authorized_keys" /etc/dropbear/authorized_keys',STARTUP)
  self.assertNotIn('umount /root',ROLLBACK)
