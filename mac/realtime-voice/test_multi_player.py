import json,tempfile,unittest,os
from unittest.mock import patch
from pathlib import Path
from player import PlayerConfig
from devices import device_ip

class MultiPlayerTests(unittest.TestCase):
 def test_private_registry_override_and_default_fallback(self):
  with tempfile.TemporaryDirectory() as root:
   base=Path(root)/'config/speakers.json';base.parent.mkdir();
   private=Path(root)/'private-speakers.json'
   template=lambda ip:{'version':1,'mode':'single','devices':[{'id':'lx06-primary','ip':ip},{'id':'lx06-secondary','ip':'192.168.1.99'}]}
   base.write_text(json.dumps(template('192.168.1.20')))
   private.write_text(json.dumps(template('192.168.1.21')))
   with patch.dict(os.environ,{'SPEAKERS_CONFIG':str(private)}):
    self.assertEqual(device_ip(root,'lx06-primary'),'192.168.1.21')
   with patch.dict(os.environ,{},clear=True):
    self.assertEqual(device_ip(root,'lx06-primary'),'192.168.1.20')
 def test_fixed_registry_routes_secondary_and_single_mode_denies_it(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root)/'config/speakers.json';p.parent.mkdir()
   c={'version':1,'mode':'multiple','devices':[{'id':'lx06-primary','ip':'192.168.100.186'},{'id':'lx06-secondary','ip':'192.168.100.181'}]}
   p.write_text(json.dumps(c))
   self.assertIn('root@192.168.100.181',PlayerConfig(root,'managed','lx06-secondary').command())
   with self.assertRaises(ValueError):PlayerConfig(root,'managed','root@evil')
   c['mode']='single';p.write_text(json.dumps(c))
   with self.assertRaises(ValueError):PlayerConfig(root,'managed','lx06-secondary')
