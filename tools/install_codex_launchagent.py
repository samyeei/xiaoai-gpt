"""Prepare a user LaunchAgent without copying authentication into the plist."""
import os
from pathlib import Path
import plistlib
import shutil

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'com.LOCAL_USER.xiaoai-codex'


def prepare():
    private = ROOT / 'mac/codex-service/private'
    if not (private / 'config.json').exists():
        raise ValueError('Create private service configuration first')
    node = shutil.which('node')
    if not node:
        raise ValueError('Node 22 not found')
    target = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    logs = Path.home() / 'Library/Logs/xiaoai-codex'
    values = dict(Label=LABEL, ProgramArguments=[node, str(ROOT / 'mac/codex-service/index.mjs')],
                  WorkingDirectory=str(ROOT), RunAtLoad=True, KeepAlive=True, ThrottleInterval=30,
                  EnvironmentVariables={'PATH': str(Path(node).parent) + ':/usr/bin:/bin:/usr/sbin:/sbin'},
                  StandardOutPath=str(logs / 'service.log'), StandardErrorPath=str(logs / 'service-error.log'))
    if target.exists():
        previous = plistlib.loads(target.read_bytes())
        expected = {**values, 'StandardOutPath': str(private / 'service.log'), 'StandardErrorPath': str(private / 'service-error.log')}
        if previous not in (values, expected):
            raise ValueError('Existing LaunchAgent differs; refusing replacement')
    target.parent.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ('service.log', 'service-error.log'):
        log = logs / name
        log.touch(exist_ok=True)
        log.chmod(0o600)
    with target.open('wb') as stream:
        plistlib.dump(values, stream)
    target.chmod(0o600)
    print(str(target))
    print('Prepared only. Load with launchctl bootstrap gui/' + str(os.getuid()) + ' ' + str(target))


if __name__ == '__main__':
    prepare()
