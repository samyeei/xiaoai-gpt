import unittest
from provision import authorized_line
class ProvisionTests(unittest.TestCase):
 def test_dedicated_key_only_allows_fixed_player(self):
  line=authorized_line('ssh-rsa AAAAB3NzaC1yc2E= local-comment')
  self.assertIn('command="aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000"',line)
  self.assertIn('no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty',line)
  self.assertTrue(line.endswith('xiaoai-realtime-voice'))
 def test_shell_or_wrong_key_type_is_rejected(self):
  for value in ['ssh-rsa BAD;echo secret','ssh-ed25519 AAAA','ssh-rsa AAAA\nssh-rsa BBBB']:
   with self.assertRaises(ValueError):authorized_line(value)
class ProvisionShellTests(unittest.TestCase):
 def test_append_is_idempotent_and_rollback_preserves_other_keys(self):
  import tempfile,subprocess
  from pathlib import Path
  from provision import INSTALL,REMOVE
  with tempfile.TemporaryDirectory() as root:
   directory=Path(root)/'.ssh';directory.mkdir();auth=directory/'authorized_keys';auth.write_text('existing-key\n')
   line=authorized_line('ssh-rsa AAAAB3NzaC1yc2E=')
   run=lambda script:subprocess.run(['sh','-c',script.replace('$HOME',root)],input=(line+'\n').encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout
   self.assertEqual(run(INSTALL),b'ADDED\n');self.assertEqual(run(INSTALL),b'EXISTING\n');self.assertEqual(auth.read_text().splitlines(),['existing-key',line]);run(REMOVE);self.assertEqual(auth.read_text(),'existing-key\n')
