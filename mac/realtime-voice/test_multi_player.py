import json,tempfile,unittest
from pathlib import Path
from player import PlayerConfig

class MultiPlayerTests(unittest.TestCase):
 def test_fixed_registry_routes_secondary_and_single_mode_denies_it(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root)/'config/speakers.json';p.parent.mkdir()
   c={'version':1,'mode':'multiple','devices':[{'id':'lx06-primary','ip':'192.168.100.186'},{'id':'lx06-secondary','ip':'192.168.100.181'}]}
   p.write_text(json.dumps(c))
   self.assertIn('root@192.168.100.181',PlayerConfig(root,'managed','lx06-secondary').command())
   with self.assertRaises(ValueError):PlayerConfig(root,'managed','root@evil')
   c['mode']='single';p.write_text(json.dumps(c))
   with self.assertRaises(ValueError):PlayerConfig(root,'managed','lx06-secondary')
