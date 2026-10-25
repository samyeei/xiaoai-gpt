import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from . import core
from .core import Journal, InstallError, validate_settings

class JournalTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.home=self.root/'home';self.home.mkdir()
 def test_resume_reuses_identity_and_keys(self):
  j=Journal(self.root,self.home);j.save();other=Journal(self.root,self.home)
  self.assertEqual(j.data['id'],other.data['id']);self.assertEqual(j.data['key'],other.data['key']);self.assertNotEqual(j.data['key'],j.data['admin_key']);self.assertEqual(j.path.stat().st_mode&0o777,0o600)
 def test_rollback_restores_original_and_refuses_external_edits(self):
  j=Journal(self.root,self.home);p=self.root/'config.json';p.write_bytes(b'original')
  j.write(p,b'new',replace=True);j.write(p,b'new');self.assertEqual(len(j.data['files']),1)
  p.write_bytes(b'external')
  with self.assertRaises(InstallError):j.rollback()
  self.assertEqual(p.read_bytes(),b'external');p.write_bytes(b'new');j.rollback();self.assertEqual(p.read_bytes(),b'original')
 def test_foreign_and_symlink_files_are_not_overwritten(self):
  j=Journal(self.root,self.home);p=self.home/'file';p.write_bytes(b'existing')
  with self.assertRaises(InstallError):j.write(p,b'new')
  q=self.home/'link';q.symlink_to(p)
  with self.assertRaises(InstallError):j.write(q,b'x',replace=True)
 def test_interrupted_planned_write_is_recovered(self):
  j=Journal(self.root,self.home);p=self.root/'config';p.write_bytes(b'old');j.write(p,b'new',replace=True)
  # Simulate a crash before os.replace: journal already durable, old bytes remain.
  p.write_bytes(b'old');j.rollback();self.assertEqual(p.read_bytes(),b'old')
 def test_rejects_bad_addresses_and_unknown_settings(self):
  for settings in ({'speaker':'8.8.8.8','mac_ip':'192.168.100.20'},{'speaker':'192.168.100.10;rm','mac_ip':'192.168.100.20'},{'speaker':'192.168.100.10','mac_ip':'192.168.100.10'},{'speaker':'192.168.100.10','mac_ip':'192.168.100.20','password':'secret'}):
   with self.subTest(settings=settings),self.assertRaises(InstallError):validate_settings(settings)
 def test_conflicting_mutation_lock(self):
  j=Journal(self.root,self.home)
  with j.lock():
   with self.assertRaises(InstallError):
    with Journal(self.root,self.home).lock():pass
 def test_parent_traversal_never_escapes_owned_roots(self):
  owned=self.root/'owned';owned.mkdir();j=Journal(owned,self.home)
  with self.assertRaises(InstallError):j.write(owned/'../outside',b'x')
 def test_interrupted_rewrite_accepts_previous_owned_hash_for_rollback(self):
  j=Journal(self.root,self.home);p=self.root/'settings';j.write(p,b'first')
  real=core.atomic
  def interrupted(path,data,mode=0o600):
   if Path(path)==p:raise OSError('interrupted promotion')
   return real(path,data,mode)
  with patch.object(core,'atomic',side_effect=interrupted):
   with self.assertRaises(OSError):j.write(p,b'second')
  resumed=Journal(self.root,self.home)
  resumed.rollback();self.assertFalse(p.exists())
 def test_lock_refreshes_state_created_after_journal_construction(self):
  first=Journal(self.root,self.home);stale=Journal(self.root,self.home)
  with first.lock():first.write(self.root/'owned',b'first')
  with stale.lock():
   self.assertIn(str(self.root/'owned'),stale.data['files'])

if __name__=='__main__':unittest.main()
