"""Manual finite Native Voice route lease. Never opens or controls Native Voice UI."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
LABEL = 'com.LOCAL_USER.xiaoai-unified'


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise RuntimeError('Private file symlink refused')
    temp = path.with_name(path.name + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def validate_seconds(seconds):
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ValueError('seconds must be finite, greater than zero and at most 300')


class Session:
    def __init__(self, seconds, host, control_path, known_hosts, root=ROOT, dynamic_mirror=False):
        validate_seconds(seconds)
        if not host or host.startswith('-') or any(c.isspace() for c in host):
            raise ValueError('Expected an SSH host target')
        if not os.path.isabs(control_path) or not os.path.isabs(known_hosts):
            raise ValueError('Task SSH socket and known hosts paths must be absolute')
        self.seconds, self.host = seconds, host
        self.control_path, self.known_hosts = control_path, known_hosts
        self.root = Path(root)
        self.dynamic_mirror = dynamic_mirror
        self.runtime = self.root / '.codex-runs/native-voice'
        self.baseline_path = self.runtime / 'session-defaults.json'
        self.flag = self.root / 'mac/unified-service/private/native-audio.json'
        self.children, self.logs = [], []
        self.baseline = None
        self.restarted = self.flag_written = False
        self.stop_signal = None

    def command(self, args, capture=False, timeout=5):
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('Required command unavailable or timed out') from None
        if result.returncode:
            raise RuntimeError('Required command returned failure')
        return result.stdout

    def defaults(self, direction, uid):
        self.command([str(self.runtime / 'mac_audio_defaults'), 'set', direction, uid])

    def restart(self):
        # launchd enforces the agent's 30-second minimum runtime between spawns.
        self.command(['/bin/launchctl', 'kickstart', '-k', f'gui/{os.getuid()}/{LABEL}'], timeout=40)

    def preflight(self):
        # An abandoned active lease retains its original baseline for explicit recovery.
        if self.baseline_path.exists():
            prior = json.loads(self.baseline_path.read_text())
            if prior.get('active'):
                raise RuntimeError('Prior route lease is active; baseline preserved for recovery')
        if self.flag.exists():
            raise RuntimeError('Existing Native Voice opt-in flag requires explicit recovery')
        data = json.loads(self.command([str(self.runtime / 'mac_audio_defaults'), 'get'], True))
        selected = {}
        for name in ('BlackHole 2ch', 'BlackHole 16ch'):
            matches = [d['uid'] for d in data['devices'] if d['name'] == name]
            if len(matches) != 1 or not isinstance(matches[0], str) or not matches[0]:
                raise RuntimeError('Expected exactly one device named ' + name)
            if sum(d.get('uid') == matches[0] for d in data['devices']) != 1:
                raise RuntimeError('Virtual audio device UID is not unique')
            selected[name] = matches[0]
        if len(set(selected.values())) != 2:
            raise RuntimeError('Virtual audio device identities are not distinct')
        for direction in ('input', 'output'):
            if not isinstance(data.get(direction), str) or not data[direction]:
                raise RuntimeError('Default audio baseline is unavailable')
        self.command(['ssh', '-S', self.control_path, '-o', 'ControlMaster=no',
                      '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                      '-o', 'UserKnownHostsFile=' + self.known_hosts,
                      '-o', 'GlobalKnownHostsFile=/dev/null',
                      '-o', 'ProxyCommand=/usr/bin/false', '-O', 'check', self.host])
        self.baseline = {k: data[k] for k in ('input', 'output')}
        private_json(self.baseline_path, dict(self.baseline, active=True))
        return selected

    def start_children(self):
        python = str(self.root / '.codex-runs/mac-voice-env/bin/python')
        for name in ('uplink', 'downlink'):
            path = self.runtime / ('session-' + name + '.jsonl')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            output = os.fdopen(fd, 'w')
            self.logs.append(output)
            args = [python, str(self.root / f'mac/native-voice/{name}.py'),
                    '--seconds', str(self.seconds), '--mute-port4416']
            if name == 'downlink':
                args += ['--host', self.host, '--control-path', self.control_path,
                         '--known-hosts', self.known_hosts]
            self.children.append(subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.DEVNULL, start_new_session=True))

    def children_alive(self):
        if any(child.poll() is not None for child in self.children):
            raise RuntimeError('Native Voice audio child exited before session expiry')

    def port_ready(self):
        try:
            with socket.create_connection(('127.0.0.1', 4415), timeout=.1):
                return True
        except OSError:
            return False

    def check_signal(self):
        if self.stop_signal is not None:
            raise RuntimeError('Session interrupted by ' + signal.Signals(self.stop_signal).name)

    def route_ready(self, deadline):
        self.check_signal()
        if time.monotonic() >= deadline:
            raise RuntimeError('Session expired before audio route activation')
        self.children_alive()
        if not self.port_ready():
            raise RuntimeError('Uplink port became unavailable before route activation')

    def verify_route(self, selected):
        try:
            actual = json.loads(self.command([str(self.runtime / 'mac_audio_defaults'), 'get'], True))
        except Exception:
            raise RuntimeError('Audio route monitoring failed') from None
        if not isinstance(actual, dict):
            raise RuntimeError('Audio route monitoring returned invalid data')
        for direction, name in (('input', 'BlackHole 2ch'), ('output', 'BlackHole 16ch')):
            if actual.get(direction) != selected[name]:
                # External route changes end the lease; never contend by resetting it.
                raise RuntimeError('Audio route drift detected for ' + direction)

    def wait_ready(self):
        deadline = time.monotonic() + min(5, self.seconds)
        while True:
            self.check_signal()
            self.children_alive()
            if self.port_ready():
                self.children_alive()
                return
            if time.monotonic() >= deadline:
                raise RuntimeError('Uplink port readiness timed out')
            time.sleep(.05)

    def cleanup(self):
        errors = []
        if self.baseline is not None:
            for direction in ('input', 'output'):
                try:
                    self.defaults(direction, self.baseline[direction])
                except Exception:
                    errors.append('restore_' + direction + '_failed')
        if self.flag_written:
            try:
                self.flag.unlink(missing_ok=True)
            except Exception:
                errors.append('remove_opt_in_failed')
        for child in self.children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception:
                errors.append('child_terminate_failed')
        for child in self.children:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=2)
                except Exception:
                    errors.append('child_stop_failed')
            except Exception:
                errors.append('child_wait_failed')
        for output in self.logs:
            output.close()
        if self.restarted and not self.dynamic_mirror:
            try:
                self.restart()
            except Exception:
                errors.append('manager_disable_mirror_failed')
        if self.baseline is not None and not errors:
            private_json(self.baseline_path, dict(self.baseline, active=False))
        return errors

    def run(self):
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.runtime.chmod(0o700)
        fd = os.open(self.runtime / 'session.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another Native Voice session owns the route lease') from None
            old_signals = {}
            error = None
            cleanup_errors = []
            try:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    old_signals[sig] = signal.signal(sig, lambda number, frame: setattr(self, 'stop_signal', number))
                selected = self.preflight()
                self.check_signal()
                if self.port_ready():
                    raise RuntimeError('Uplink port is already occupied')
                started = time.monotonic()
                expires_at = int((time.time() + self.seconds) * 1000)
                self.start_children()
                self.wait_ready()
                private_json(self.flag, {'expires_at': expires_at})
                self.flag_written = True
                if not self.dynamic_mirror:
                    # Even a failed kickstart may have affected the manager.
                    self.restarted = True
                    self.restart()
                self.route_ready(started + self.seconds)
                self.defaults('input', selected['BlackHole 2ch'])
                self.route_ready(started + self.seconds)
                self.defaults('output', selected['BlackHole 16ch'])
                self.verify_route(selected)
                self.route_ready(started + self.seconds)
                print(json.dumps(dict(event='ready', expires_at=expires_at)), flush=True)
                next_route_check = time.monotonic() + 1
                while time.monotonic() < started + self.seconds:
                    self.check_signal()
                    self.children_alive()
                    if time.monotonic() >= next_route_check:
                        self.verify_route(selected)
                        next_route_check = time.monotonic() + 1
                    time.sleep(min(.05, max(0, started + self.seconds - time.monotonic())))
                self.check_signal()
            except Exception as exc:
                error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            finally:
                try:
                    cleanup_errors = self.cleanup()
                except Exception:
                    cleanup_errors.append('cleanup_state_save_failed')
                for sig, handler in old_signals.items():
                    signal.signal(sig, handler)
            result = dict(event='final', status='failed' if error or cleanup_errors else 'expired',
                          seconds=self.seconds, error=error, cleanup_errors=cleanup_errors)
            private_json(self.runtime / 'session-final.json', result)
            if self.dynamic_mirror:
                print(json.dumps(result), flush=True)
            if error or cleanup_errors:
                raise RuntimeError('; '.join(filter(None, [error, *cleanup_errors])))
            return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=240)
    parser.add_argument('--host', required=True)
    parser.add_argument('--control-path', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--dynamic-mirror', action='store_true')
    args = parser.parse_args(argv)
    try:
        validate_seconds(args.seconds)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv=None):
    try:
        args = parse_args(argv)
        result = Session(**vars(args)).run()
        if not args.dynamic_mirror:
            print(json.dumps(result))
    except Exception as exc:
        print(json.dumps(dict(event='error', error_type=type(exc).__name__, message=str(exc))))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
