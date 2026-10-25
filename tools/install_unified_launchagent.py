"""Prepare unified LaunchAgent. Runtime credentials stay in private files."""
from pathlib import Path
import os
import plistlib
ROOT=Path(__file__).resolve().parents[1]
LABEL='com.LOCAL_USER.xiaoai-unified'
def prepare():
    node=Path('/Users/YOUR_USER/.local/bin/node')
    python=ROOT/'.codex-runs/mac-voice-env/bin/python'
    if not node.exists() or not python.exists():raise ValueError('Explicit runtimes required')
    for name in ('mac/codex-service/private/config.json','mac/muse-service/private/config.json'):
        if not (ROOT/name).exists():raise ValueError('Private configuration required')
    logs=Path.home()/'Library/Logs/xiaoai-unified';logs.mkdir(parents=True,exist_ok=True,mode=0o700);logs.chmod(0o700)
    for name in ('service.log','service-error.log'):
        p=logs/name
        if p.is_symlink():raise ValueError('Log symlink refused')
        p.touch(exist_ok=True);p.chmod(0o600)
    values=dict(Label=LABEL,ProgramArguments=[str(node),str(ROOT/'mac/unified-service/index.mjs')],WorkingDirectory=str(ROOT),RunAtLoad=True,KeepAlive=True,ThrottleInterval=30,EnvironmentVariables={'PATH':str(node.parent)+':/usr/bin:/bin:/usr/sbin:/sbin'},StandardOutPath=str(logs/'service.log'),StandardErrorPath=str(logs/'service-error.log'))
    target=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist';target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_symlink():raise ValueError('Plist symlink refused')
    if target.exists() and plistlib.loads(target.read_bytes())!=values:raise ValueError('Different existing agent; refusing replacement')
    target.write_bytes(plistlib.dumps(values));target.chmod(0o600)
    print(str(target))
if __name__=='__main__':prepare()
