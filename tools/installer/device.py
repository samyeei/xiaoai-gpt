"""Bounded LX06 SSH transaction. Remote content stays in the private journal."""

import base64
import os
from pathlib import Path
import re
import subprocess

from .core import InstallError, private_dir, sha, validate_settings


FORCED = 'command="aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty'
PATHS = {'route': '/data/open-xiaoai/server.txt',
         'init': '/data/open-xiaoai/init.sh',
         'keys': '"$HOME/.ssh/authorized_keys"'}


def authorized_line(public):
    if '\n' in public or '\r' in public:
        raise InstallError('invalid_device_public_key')
    fields = public.strip().split()
    if len(fields) < 2 or fields[0] != 'ssh-rsa' or not re.fullmatch(r'[A-Za-z0-9+/=]{8,8192}', fields[1]):
        raise InstallError('invalid_device_public_key')
    try:
        base64.b64decode(fields[1], validate=True)
    except ValueError:
        raise InstallError('invalid_device_public_key') from None
    return (FORCED + ' ssh-rsa ' + fields[1] + ' xiaoai-realtime-voice').encode()


def _default_run(args, input=None, interactive=False, timeout=8):
    if interactive:
        return subprocess.run(args, input=input, timeout=timeout, check=False)
    return subprocess.run(args, input=input, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=timeout, check=False)


class Device:
    def __init__(self, journal, settings, run=_default_run):
        self.journal = journal
        self.settings = validate_settings(settings)
        self.run = run
        self.key = journal.root / 'mac/realtime-voice/private/device_rsa'
        self.known_hosts = journal.root / '.codex-runs/lx06-known-hosts'
        self.socket_dir = Path('/tmp').resolve() / ('xiaoai-gpt-' + str(os.getuid()) + '-' + journal.data['id'])
        self.socket = self.socket_dir / 'control'

    def _invoke(self, args, *, input=None, interactive=False, timeout=8):
        try:
            result = self.run(args, input=input, interactive=interactive, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            raise InstallError('device_ssh_failed') from None
        return result

    def _base(self, interactive=False, managed=False):
        private_dir(self.known_hosts.parent)
        if self.known_hosts.is_symlink():
            raise InstallError('symlink_known_hosts_refused')
        if not self.known_hosts.exists():
            fd = os.open(self.known_hosts, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        self.known_hosts.chmod(0o600)
        strict = 'ask' if interactive else 'yes'
        args = ['ssh', '-F', '/dev/null', '-o', 'GlobalKnownHostsFile=/dev/null',
                '-o', 'HostKeyAlgorithms=+ssh-rsa', '-o', 'PubkeyAcceptedAlgorithms=+ssh-rsa',
                '-o', 'BatchMode=' + ('no' if interactive else 'yes'),
                '-o', 'StrictHostKeyChecking=' + strict,
                '-o', 'UserKnownHostsFile=' + str(self.known_hosts),
                '-o', 'ConnectTimeout=8']
        if managed:
            args += ['-i', str(self.key), '-o', 'IdentitiesOnly=yes',
                     '-o', 'ControlMaster=no', '-o', 'ControlPath=none']
        else:
            args += ['-o', 'ControlPath=' + str(self.socket), '-o', 'ControlMaster=auto']
        return args

    def connect(self, interactive=False):
        """Establish the management mux; only a terminal may prompt for trust/auth."""
        private_dir(self.socket_dir)
        if self.socket.is_symlink():
            raise InstallError('symlink_control_socket_refused')
        host = 'root@' + self.settings['speaker']
        if self.socket.exists():
            check = self._invoke(self._base() + ['-S', str(self.socket), '-O', 'check', host])
            if check.returncode == 0:
                return {'management_connected': True}
            raise InstallError('device_management_socket_invalid')
        args = self._base(interactive=interactive) + ['-M', '-S', str(self.socket), '-fN', host]
        result = self._invoke(args, interactive=interactive, timeout=60 if interactive else 12)
        if result.returncode or not self.socket.exists():
            raise InstallError('device_interactive_auth_failed' if interactive else 'device_interactive_auth_required')
        return {'management_connected': True}

    def close(self):
        """Close only this installation's management master."""
        if self.socket.is_symlink():
            raise InstallError('symlink_control_socket_refused')
        if not self.socket.exists():
            return {'management_closed': True}
        host = 'root@' + self.settings['speaker']
        check = self._invoke(self._base() + ['-S', str(self.socket), '-O', 'check', host])
        if check.returncode:
            self.socket.unlink(missing_ok=True)
            return {'management_closed': True}
        result = self._invoke(self._base() + ['-S', str(self.socket), '-O', 'exit',
                                              host])
        if result.returncode:
            raise InstallError('device_management_close_failed')
        return {'management_closed': True}

    def _remote(self, script, *, input=None, managed=False):
        args = self._base(managed=managed)
        args += ['root@' + self.settings['speaker'], script]
        result = self._invoke(args, input=input, timeout=12)
        if result.returncode:
            raise InstallError('device_remote_command_failed')
        return result.stdout

    def _read(self, kind):
        path = PATHS[kind]
        script = f'''# DEVICE_READ_{kind.upper()}
set -eu
if test -f {path}; then
 printf 'PRESENT\\n'
 base64 < {path}
else printf 'ABSENT\\n'; fi'''
        out = self._remote(script)
        if out == b'ABSENT\n':
            return None
        if not out.startswith(b'PRESENT\n'):
            raise InstallError('device_snapshot_invalid')
        try:
            return base64.b64decode(b''.join(out.splitlines()[1:]), validate=True)
        except ValueError:
            raise InstallError('device_snapshot_invalid') from None

    def _cas(self, kind, before, after):
        """Compare full content hash then replace atomically; input never goes in argv."""
        path = PATHS[kind]
        expected = sha(before).encode() if before is not None else b'ABSENT'
        payload = expected + b'\n' + (base64.b64encode(after) if after is not None else b'ABSENT') + b'\n'
        key_setup = ('test ! -L "$HOME/.ssh" || exit 15\n'
                     'mkdir -p "$HOME/.ssh"\nchmod 700 "$HOME/.ssh"') if kind == 'keys' else ''
        script = f'''# DEVICE_CAS_{kind.upper()}
set -eu
umask 077
target={path}
test ! -L "$target" || exit 15
{key_setup}
IFS= read -r expected
IFS= read -r encoded
if test -f "$target"; then current="$(sha256sum "$target" | cut -d ' ' -f1)"; else current=ABSENT; fi
test "$current" = "$expected" || exit 14
if test "$encoded" = ABSENT; then rm -f "$target"; printf 'OK\\n'; exit 0; fi
tmp="$target.xiaoai-install.$$"
trap 'rm -f "$tmp"' EXIT HUP INT TERM
printf '%s' "$encoded" | base64 -d > "$tmp"
chmod 600 "$tmp"
mv "$tmp" "$target"
trap - EXIT HUP INT TERM
printf 'OK\\n' '''
        if self._remote(script, input=payload) != b'OK\n':
            raise InstallError('device_write_unconfirmed')

    def _key_line(self):
        private_dir(self.key.parent)
        pub = self.key.with_suffix('.pub')
        # Playback identity outlives individual device route transactions.
        record = self.journal.data.setdefault('player_identity', {})
        if self.key.is_symlink() or pub.is_symlink() or self.key.exists() != pub.exists():
            raise InstallError('device_keypair_invalid')
        if self.key.exists() and not record.get('key_generation_intent'):
            raise InstallError('foreign_device_keypair_refused')
        if not self.key.exists():
            record['key_generation_intent'] = True
            self.journal.save()
            result = self._invoke(['ssh-keygen', '-q', '-t', 'rsa', '-b', '3072', '-N', '',
                                   '-C', 'xiaoai-realtime-voice', '-f', str(self.key)], timeout=30)
            if result.returncode or not self.key.is_file() or not pub.is_file():
                raise InstallError('device_key_generation_failed') from None
        self.key.chmod(0o600)
        pub.chmod(0o600)
        line = authorized_line(pub.read_text().strip())
        public_sha = sha(pub.read_bytes())
        if record.get('public_key_sha') not in (None, public_sha):
            raise InstallError('device_keypair_changed')
        record['public_key_sha'] = public_sha
        self.journal.save()
        return line

    def prepare(self):
        probe = '''# DEVICE_PREFLIGHT
set -eu
test "$(micocfg_model)" = LX06
test -x /data/open-xiaoai/client
LC_ALL=C grep -a -q start_recording /data/open-xiaoai/client
LC_ALL=C grep -a -q run_shell /data/open-xiaoai/client
LC_ALL=C grep -a -q get_version /data/open-xiaoai/client
test -f /data/open-xiaoai/init.sh
test -f /data/open-xiaoai/server.txt
test ! -L /data/open-xiaoai/server.txt
test ! -L /data/open-xiaoai/init.sh
test ! -L "$HOME/.ssh"
test ! -L "$HOME/.ssh/authorized_keys"
test -w "$HOME"
command -v aplay >/dev/null
command -v base64 >/dev/null
command -v sha256sum >/dev/null
printf 'LX06\\n' '''
        if self._remote(probe) != b'LX06\n':
            raise InstallError('device_prerequisite_failed')
        record = self.journal.data.setdefault('device', {})
        if record.get('speaker') not in (None, self.settings['speaker']):
            raise InstallError('device_identity_changed')
        record['speaker'] = self.settings['speaker']
        self.journal.save()
        for kind in PATHS:
            if kind not in record:
                value = self._read(kind)
                if kind != 'keys' and value is None:
                    raise InstallError('device_prerequisite_failed')
                record[kind] = {'before': base64.b64encode(value).decode() if value is not None else None,
                                'before_sha': sha(value) if value is not None else None}
                self.journal.save()
        route_after = base64.b64encode(('ws://' + self.settings['mac_ip'] + ':4399\n').encode()).decode()
        if record.get('route_after') not in (None, route_after):
            raise InstallError('device_target_changed')
        record['route_after'] = route_after
        line = self._key_line()
        if record.get('key_line') and record['key_line'] != base64.b64encode(line).decode():
            raise InstallError('device_keypair_changed')
        record['key_line'] = base64.b64encode(line).decode()
        self.journal.save()
        return {'device_prepared': True}

    def _values(self):
        record = self.journal.data.get('device')
        if not record or any(kind not in record for kind in PATHS) or 'key_line' not in record:
            raise InstallError('device_not_prepared')
        original = {kind: (base64.b64decode(record[kind]['before']) if record[kind]['before'] is not None else None) for kind in PATHS}
        line = base64.b64decode(record['key_line'])
        route = base64.b64decode(record['route_after'])
        return original, line, route

    def _key_content(self, keys, line):
        if keys is None:
            keys = b''
        if line in keys.splitlines():
            return keys
        return keys + (b'\n' if keys and not keys.endswith(b'\n') else b'') + line + b'\n'

    def activate(self):
        original, line, route = self._values()
        if self._read('init') != original['init']:
            raise InstallError('device_init_changed')
        keys = self._read('keys')
        if (keys is None or line not in keys.splitlines()) and keys != original['keys']:
            raise InstallError('device_keys_changed_before_install')
        desired = self._key_content(keys, line)
        if keys != desired:
            self.journal.data['device']['keys_after_sha'] = sha(desired)
            self.journal.save()
            self._cas('keys', keys, desired)
        probe = '''# DEVICE_PROBE
printf XIAOAI_PERMISSION_PROBE'''
        result = self._invoke(self._base(managed=True) + ['root@' + self.settings['speaker'], probe],
                              input=bytes(3840), timeout=12)
        if result.returncode or result.stdout:
            raise InstallError('device_restricted_key_unverified')
        current = self._read('route')
        if current not in (original['route'], route):
            raise InstallError('device_route_changed')
        if current != route:
            self.journal.data['device']['route_write_intent'] = True
            self.journal.save()
            self._cas('route', current, route)
            self._restart()
        return {'device_route_active': True, 'managed_player_verified': True}

    def _restart(self):
        original, _, _ = self._values()
        expected = sha(original['init'])
        script = '''# DEVICE_RESTART
set -eu
test -f /data/open-xiaoai/init.sh
test "$(sha256sum /data/open-xiaoai/init.sh | cut -d ' ' -f1)" = EXPECTED_INIT
sh -c 'trap "" HUP; exec sh /data/open-xiaoai/init.sh' > /tmp/xiaoai-gpt-client.log 2>&1 < /dev/null &
printf 'OK\\n' '''.replace('EXPECTED_INIT', expected)
        if self._remote(script) != b'OK\n':
            raise InstallError('device_restart_unconfirmed')

    def check_restore(self):
        original, line, route = self._values()
        if self._read('init') != original['init']:
            raise InstallError('device_init_changed')
        if self._read('route') not in (original['route'], route):
            raise InstallError('device_route_changed')
        keys = self._read('keys')
        if keys is None and original['keys'] is not None:
            raise InstallError('device_keys_removed')
        if keys is not None and line in keys.splitlines() and not self.journal.data['device'].get('keys_after_sha'):
            raise InstallError('device_key_ownership_unknown')
        return {'device_restore_safe': True}

    def restore(self):
        self.check_restore()
        original, line, route = self._values()
        current_route = self._read('route')
        if current_route == route and current_route != original['route']:
            self._cas('route', current_route, original['route'])
            self._restart()
        keys = self._read('keys')
        if keys is not None and line in keys.splitlines():
            if sha(keys) == self.journal.data['device'].get('keys_after_sha'):
                restored = original['keys']
            else:
                kept = [entry for entry in keys.splitlines(keepends=True) if entry.rstrip(b'\r\n') != line]
                restored = b''.join(kept)
            self._cas('keys', keys, restored)
        return {'device_route_restored': True, 'managed_key_removed': True}
