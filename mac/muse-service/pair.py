"""Mac-only pairing with a new identity and a manually filled private token file."""
from __future__ import annotations
import argparse
import contextlib
import json
import logging
import os
import pathlib
import signal
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
sys.path.insert(0,str(pathlib.Path(__file__).parent/'vendor'))
from musegadget import __version__,config,identity,muse_api,network
from musegadget.ble_setup import Credentials,ProvisionFailed,SetupController
from musegadget.pairing import PairingSession
from ble_macos import BleServer
from mac_setup import MacSetupController

DEFAULT_STATE=pathlib.Path(__file__).parent/'private'

def private_directory(directory):
    directory=pathlib.Path(directory)
    if directory.is_symlink():raise ValueError('Private state directory cannot be a symlink')
    directory.mkdir(parents=True,exist_ok=True,mode=0o700);directory.chmod(0o700)
    return directory

def save_private_json(name,data,directory):
    directory=private_directory(directory);dest=directory/name
    if dest.is_symlink():raise ValueError('Private state file cannot be a symlink')
    fd,tmp=tempfile.mkstemp(prefix='.'+name+'.',dir=directory)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            json.dump(data,out,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
        os.replace(tmp,dest)
        dfd=os.open(directory,os.O_RDONLY)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:
        with contextlib.suppress(FileNotFoundError):os.unlink(tmp)

def initialize_state(directory=DEFAULT_STATE):
    directory=private_directory(directory)
    for name in (config.IDENTITY_FILE,config.SDK_TOKEN_FILE,config.PAIRING_FILE):
        path=directory/name
        if path.is_symlink():raise ValueError('Private state file cannot be a symlink')
        if path.exists():path.chmod(0o600)
    # Never replace a corrupt existing identity with a fresh identity silently.
    if (directory/config.IDENTITY_FILE).exists():
        stored=config.load_json(config.IDENTITY_FILE,directory)
        if not stored or not isinstance(stored.get('mac'),str) or not identity._MAC_RE.fullmatch(stored['mac']):
            raise ValueError('Stored Mac identity is invalid; preserve it for review')
        ident=identity.Identity(stored['mac'])
    else:
        ident=identity.Identity(identity.generate_mac());save_private_json(config.IDENTITY_FILE,{'mac':ident.mac},directory)
    token=directory/config.SDK_TOKEN_FILE
    if not token.exists():
        fd=os.open(token,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    return ident

def read_sdk_token(directory):
    path=pathlib.Path(directory)/config.SDK_TOKEN_FILE
    if path.is_symlink():raise ValueError('SDK token file cannot be a symlink')
    if path.exists():path.chmod(0o600)
    # Do not use token env vars; file is the single explicit input channel.
    token=path.read_text(encoding='utf-8').strip() if path.exists() else ''
    if token and not config._SDK_TOKEN.fullmatch(token):raise ValueError('SDK token file is invalid')
    return token or None

def _https_api(value):
    if not value:return ''
    url=urlsplit(value)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ProvisionFailed('auth_failed')
    # Pairing credentials come from the app, but must not send bearer tokens
    # to an arbitrary peer-provided host. This installation uses Muse public API.
    if url.hostname!='api.muse.ai' or url.port not in (None,443):raise ProvisionFailed('auth_failed')
    return value.rstrip('/')

def verify_and_save(credentials,commit,directory=DEFAULT_STATE,*,fetch=None):
    if not credentials.access_token or not credentials.refresh_token:raise ProvisionFailed('auth_failed')
    api_url=_https_api(credentials.api_url);api_v2=_https_api(credentials.api_url_v2)
    fetch=fetch or muse_api.fetch_vms_with_status
    try:vms,status=fetch(credentials.access_token,muse_api.api_root(api_v2))
    except Exception:raise ProvisionFailed('auth_failed') from None
    if status!=200 or not vms:raise ProvisionFailed('auth_failed')
    record={'access_token':credentials.access_token,'refresh_token':credentials.refresh_token,'token_type':'device','username':credentials.username,'api_url':api_url,'api_url_v2':api_v2,'noise_host':credentials.noise_host,'access_token_saved_at':int(time.time())}
    def save():save_private_json(config.PAIRING_FILE,record,directory);return True
    try:success=commit(save)
    except Exception:raise ProvisionFailed('error_storage') from None
    if not success:raise ProvisionFailed('error_storage')

class MacNetwork:
    is_online=staticmethod(network.is_online)
    current_connection_entry=staticmethod(lambda:{'ssid':network.CURRENT_CONNECTION_LABEL,'rssi':-40,'secure':False})

def run_pair(directory,timeout):
    ident=initialize_state(directory)
    if (directory/config.PAIRING_FILE).exists():raise ValueError('Mac already has pairing state; preserve it before a separate re-pair operation')
    token=read_sdk_token(directory)
    if not token:raise ValueError('SDK token required: fill private/sdk_token locally from gadgets.muse.ai')
    pairing=PairingSession(node_id=ident.node_id,device_id=ident.device_id,mac=ident.mac,firmware_version=__version__,sdk_token=token)
    completed=threading.Event();controller=None;finish_timer=None
    server=BleServer(ident.ble_name,lambda p:controller.on_write(p),lambda:controller.on_disconnect())
    def finish():
        nonlocal finish_timer
        completed.set();finish_timer=threading.Timer(1.5,server.stop);finish_timer.daemon=True;finish_timer.start()
    controller=MacSetupController(pairing=pairing,identity=ident,version=__version__,transport=server,network=MacNetwork(),provision=lambda c,commit:verify_and_save(c,commit,directory),on_complete=finish)
    timer=threading.Timer(timeout,server.stop);timer.daemon=True
    previous={s:signal.signal(s,lambda *args:server.stop()) for s in (signal.SIGINT,signal.SIGTERM)}
    print(json.dumps({'pairing':'open','name':ident.ble_name,'timeout_seconds':timeout}),flush=True)
    controller.start();timer.start()
    try:server.run()
    finally:
        timer.cancel();controller.stop();pairing.reset()
        if finish_timer:finish_timer.cancel()
        for s,handler in previous.items():signal.signal(s,handler)
    print(json.dumps({'pairing':'complete' if completed.is_set() else 'cancelled_or_timed_out'}),flush=True)
    return 0 if completed.is_set() else 2

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['init','probe','pair','status']);parser.add_argument('--state-dir',type=pathlib.Path,default=DEFAULT_STATE);parser.add_argument('--timeout',type=float,default=600)
    args=parser.parse_args(argv)
    if not 0<args.timeout<=3600:parser.error('timeout must be between 0 and 3600 seconds')
    # Protocol logs are deliberately disabled: attacker-controlled action/error
    # fields must never become a secret-bearing log or exception traceback.
    logging.getLogger('musegadget').disabled=True
    for name in ['musegadget.ble_setup','musegadget.muse_api','musegadget.pairing']:logging.getLogger(name).disabled=True
    try:
        if args.command=='init':
            ident=initialize_state(args.state_dir);print(json.dumps({'identity_ready':True,'name':ident.ble_name,'token_file':str(args.state_dir/config.SDK_TOKEN_FILE)}));return 0
        if args.command=='status':
            print(json.dumps({'identity_ready':(args.state_dir/config.IDENTITY_FILE).exists(),'sdk_token_ready':bool(read_sdk_token(args.state_dir)),'paired':(args.state_dir/config.PAIRING_FILE).exists()}));return 0
        if args.command=='probe':
            server=BleServer('MuseGadgetPROBE',lambda _:None,lambda:None,startup_timeout=min(args.timeout,15))
            timer=threading.Timer(args.timeout,server.stop);timer.daemon=True;timer.start()
            try:server.run()
            finally:timer.cancel();print(json.dumps({'bluetooth':server.status(),'stopped':True}),flush=True)
            return 0
        return run_pair(args.state_dir,args.timeout)
    except (ValueError,RuntimeError,OSError):
        print(json.dumps({'error':'pairing_unavailable','action':'Check Mac Bluetooth permission/state and private SDK token file; credentials were not printed.'}),file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
