"""Only configured device identities may select a fixed SSH destination."""
import json,ipaddress
from pathlib import Path

def device_ip(root,device_id):
 p=Path(root)/'config/speakers.json'
 if not p.exists():
  if device_id=='lx06-primary':return '192.168.100.186'
  raise ValueError('unknown_device')
 c=json.loads(p.read_text())
 if c.get('version')!=1 or c.get('mode') not in ('single','multiple') or len(c.get('devices',[]))!=2:raise ValueError('invalid_registry')
 ids=set();ips=set();selected=None
 for d in c['devices']:
  if set(d)!= {'id','ip'} or d['id'] not in ('lx06-primary','lx06-secondary') or d['id'] in ids:raise ValueError('invalid_device')
  ip=str(ipaddress.IPv4Address(d['ip']))
  if ip in ips:raise ValueError('duplicate_ip')
  ids.add(d['id']);ips.add(ip)
  if d['id']==device_id:selected=ip
 if selected is None or c['mode']=='single' and device_id!='lx06-primary':raise ValueError('unknown_device')
 return selected
