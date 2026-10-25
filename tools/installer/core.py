"""Private, crash-recoverable installation ownership journal. No service I/O."""
import base64, contextlib, fcntl, hashlib, ipaddress, json, os, secrets
from pathlib import Path

class InstallError(Exception):
 """Only fixed safe error codes are displayed to the agent."""

def sha(data):return hashlib.sha256(data).hexdigest()
def private_dir(path):
 path=Path(path)
 for part in [path,*path.parents]:
  if part.is_symlink():raise InstallError('symlink_path_refused')
 path.mkdir(parents=True,exist_ok=True,mode=0o700);path.chmod(0o700)

def atomic(path,data,mode=0o600):
 path=Path(path)
 if path.is_symlink():raise InstallError('symlink_path_refused')
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 temporary=path.with_name('.'+path.name+'.'+secrets.token_hex(6))
 try:
  fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.chmod(temporary,mode);os.replace(temporary,path)
  fd=os.open(path.parent,os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)
 finally:
  if temporary.exists():temporary.unlink()

def encoded_json(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
def validate_settings(settings):
 if set(settings)-{'speaker','mac_ip','node','codex'}:raise InstallError('unknown_setting')
 for k in ('speaker','mac_ip'):
  try:ip=ipaddress.IPv4Address(settings[k])
  except (KeyError,ValueError,TypeError):raise InstallError('private_ipv4_required') from None
  if not any(ip in n for n in (ipaddress.IPv4Network('10.0.0.0/8'),ipaddress.IPv4Network('172.16.0.0/12'),ipaddress.IPv4Network('192.168.0.0/16'))):raise InstallError('private_ipv4_required')
 if settings['speaker']==settings['mac_ip']:raise InstallError('distinct_device_addresses_required')
 for k in ('node','codex'):
  if k in settings and (not isinstance(settings[k],str) or not Path(settings[k]).is_absolute() or '\n' in settings[k]):raise InstallError('absolute_executable_required')
 return dict(settings)

class Journal:
 def __init__(self,root,home):
  self.root=Path(root).resolve();self.home=Path(home).resolve();self.directory=self.root/'mac/installer/private';self.path=self.directory/'state.json'
  self.data=self._read_state() or {'version':1,'id':secrets.token_hex(6),'root':str(self.root),'home':str(self.home),'key':secrets.token_hex(32),'admin_key':secrets.token_hex(32),'files':{},'steps':[],'installed':False}
 def _read_state(self):
  if any(part.is_symlink() for part in (self.path,self.directory,self.directory.parent,self.directory.parent.parent)):raise InstallError('symlink_state_refused')
  if not self.path.exists():return None
  if self.path.stat().st_mode&0o077:raise InstallError('private_state_permissions_required')
  data=json.loads(self.path.read_text())
  if data.get('version')!=1 or data.get('root')!=str(self.root) or data.get('home')!=str(self.home):raise InstallError('installation_location_changed')
  return data
 def save(self):private_dir(self.directory);atomic(self.path,encoded_json(self.data))
 @contextlib.contextmanager
 def lock(self):
  private_dir(self.directory);p=self.directory/'install.lock'
  if p.is_symlink():raise InstallError('symlink_lock_refused')
  fd=os.open(p,os.O_CREAT|os.O_RDWR,0o600)
  try:
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:raise InstallError('another_install_is_running') from None
   fresh=self._read_state()
   if fresh is not None:self.data=fresh
   yield
  finally:os.close(fd)
 def allowed(self,path):
  path=Path(os.path.abspath(path))
  if not any(path.is_relative_to(base) for base in (self.root,self.home/'Library/LaunchAgents',self.home/'Library/Logs/xiaoai-gpt',self.home/'Applications',self.home/'Desktop')):raise InstallError('unowned_path_refused')
  for part in [path,*path.parents]:
   if part.is_symlink():raise InstallError('symlink_path_refused')
  return path
 def write(self,path,data,replace=False,mode=0o600):
  path=self.allowed(path);name=str(path);record=self.data['files'].get(name);current=path.read_bytes() if path.exists() else None
  if record:
   accepted={record['after'],record['before_sha'],record.get('pending')}
   if current is not None and sha(current) not in accepted:raise InstallError('owned_file_changed_externally')
   if current is None and (record['before'] is not None or record.get('promoted',True)):raise InstallError('owned_file_removed_externally')
   if record.get('pending'):
    if current is not None and sha(current)==record['pending']:record['after']=record['pending']
    record.pop('pending');self.save()
   record['pending']=sha(data);record['mode']=mode
  else:
   if current is not None and not replace:raise InstallError('existing_file_requires_manual_migration')
   record={'before':base64.b64encode(current).decode() if current is not None else None,'before_sha':sha(current) if current is not None else None,'before_mode':path.stat().st_mode&0o777 if current is not None else None,'after':sha(data),'mode':mode,'promoted':False}
   self.data['files'][name]=record
  # Intent is durable before mutation, so interruption at either side is recoverable.
  self.save();atomic(path,data,mode)
  record['after']=sha(data);record.pop('pending',None);record['promoted']=True;self.save()
 def check_rollback(self):
  for name,record in self.data['files'].items():
   p=self.allowed(name);current=p.read_bytes() if p.exists() else None
   if current is None:
    if record['before'] is not None:raise InstallError('rollback_external_change')
   elif sha(current) not in (record['after'],record['before_sha'],record.get('pending')):raise InstallError('rollback_external_change')
 def rollback(self):
  self.check_rollback()
  for name,record in list(self.data['files'].items())[::-1]:
   p=self.allowed(name)
   if record['before'] is None:
    if p.exists():p.unlink()
   else:atomic(p,base64.b64decode(record['before']),record['before_mode'])
   del self.data['files'][name];self.save()
  self.data['installed']=False;self.data['steps']=[];self.save()
 def step(self,name):
  if name not in self.data['steps']:self.data['steps'].append(name)
  self.save()
