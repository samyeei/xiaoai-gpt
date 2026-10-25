import fcntl
import io
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from session import Session, parse_args, validate_seconds


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = Session(.02, 'root@192.168.100.186', '/task/control', '/task/hosts', Path(self.temp.name))
        self.data = dict(input='original-input-secret', output='original-output-secret', devices=[
            dict(name='BlackHole 2ch', uid='virtual2'), dict(name='BlackHole 16ch', uid='virtual16')])
        self.calls = []
        def command(args, capture=False, timeout=5):
            self.calls.append(args)
            if 'set' in args:
                self.data[args[-2]] = args[-1]
            return json.dumps(self.data).encode() if capture else b''
        self.command = patch.object(self.session, 'command', side_effect=command).start()
        self.addCleanup(patch.stopall)
        self.start = patch.object(self.session, 'start_children').start()
        self.alive = patch.object(self.session, 'children_alive').start()
        self.port = patch.object(self.session, 'port_ready', side_effect=[False, True, True, True, True]).start()
        self.stdout = patch('session.sys.stdout', new_callable=io.StringIO).start()

    def restored(self):
        sets = [c[-2:] for c in self.calls if 'set' in c]
        self.assertIn(['input', 'original-input-secret'], sets)
        self.assertIn(['output', 'original-output-secret'], sets)
        self.assertFalse(self.session.flag.exists())

    def final(self):
        return json.loads((self.session.runtime / 'session-final.json').read_text())

    def test_expiry_restores_both_and_safe_final(self):
        result = self.session.run()
        self.assertEqual(result['status'], 'expired')
        self.restored()
        self.assertFalse(json.loads(self.session.baseline_path.read_text())['active'])
        self.assertNotIn('secret', json.dumps(result))
        restarts = [c for c in self.calls if c[0] == '/bin/launchctl']
        self.assertEqual(len(restarts), 2)
        self.assertEqual(self.session.baseline_path.stat().st_mode & 0o777, 0o600)

    def test_second_default_failure_restores_even_if_command_mutated(self):
        original = self.command.side_effect
        def fail(args, capture=False, timeout=5):
            value = original(args, capture, timeout)
            if args[-2:] == ['output', 'virtual16']:
                raise RuntimeError('Required command returned failure')
            return value
        self.command.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'failure'):
            self.session.run()
        self.restored()
        self.assertEqual(self.final()['status'], 'failed')

    def test_first_default_failure_also_restores_both(self):
        original = self.command.side_effect
        def fail(args, capture=False, timeout=5):
            value = original(args, capture, timeout)
            if args[-2:] == ['input', 'virtual2']:
                raise RuntimeError('Required command returned failure')
            return value
        self.command.side_effect = fail
        with self.assertRaises(RuntimeError):
            self.session.run()
        self.restored()

    def test_child_failure_restores_before_mutation(self):
        self.alive.side_effect = RuntimeError('Native Voice audio child exited before session expiry')
        with self.assertRaisesRegex(RuntimeError, 'child exited'):
            self.session.run()
        self.restored()
        self.assertFalse(any(c[0] == '/bin/launchctl' for c in self.calls))

    def test_readiness_timeout_restores(self):
        self.port.side_effect = None
        self.port.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'readiness timed out'):
            self.session.run()
        self.restored()

    def test_sigterm_restores(self):
        self.session.seconds = .2
        self.start.side_effect = lambda: signal.raise_signal(signal.SIGTERM)
        with self.assertRaisesRegex(RuntimeError, 'SIGTERM'):
            self.session.run()
        self.restored()

    def test_lock_refusal_preserves_baseline(self):
        self.session.runtime.mkdir(parents=True)
        self.session.baseline_path.write_text('{"active":true,"input":"keep"}')
        before = self.session.baseline_path.read_bytes()
        with (self.session.runtime / 'session.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'Another Native Voice session'):
                self.session.run()
        self.assertEqual(before, self.session.baseline_path.read_bytes())
        self.command.assert_not_called()

    def test_abandoned_active_lease_refused(self):
        self.session.runtime.mkdir(parents=True)
        self.session.baseline_path.write_text('{"active":true,"input":"keep"}')
        with self.assertRaisesRegex(RuntimeError, 'Prior route lease'):
            self.session.run()
        self.assertEqual(json.loads(self.session.baseline_path.read_text())['input'], 'keep')
        self.command.assert_not_called()

    def test_restore_failure_retains_lease_and_reports_failure(self):
        original = self.command.side_effect
        def fail(args, capture=False, timeout=5):
            value = original(args, capture, timeout)
            if args[-2:] == ['input', 'original-input-secret']:
                raise RuntimeError('Required command returned failure')
            return value
        self.command.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'restore_input_failed'):
            self.session.run()
        self.assertIn(['output', 'original-output-secret'], [c[-2:] for c in self.calls])
        self.assertTrue(json.loads(self.session.baseline_path.read_text())['active'])
        self.assertEqual(self.final()['cleanup_errors'], ['restore_input_failed'])

    def test_group_stop_is_bounded_and_kills(self):
        import subprocess
        child = MagicMock(pid=12345)
        child.wait.side_effect = [subprocess.TimeoutExpired('child', 2), 0]
        self.session.children = [child]
        with patch('session.os.killpg') as kill:
            self.assertEqual(self.session.cleanup(), [])
        self.assertEqual(kill.call_args_list[0].args, (12345, signal.SIGTERM))
        self.assertEqual(kill.call_args_list[1].args, (12345, signal.SIGKILL))

    def test_duplicate_device_blocks_route_change(self):
        self.data['devices'].append(dict(name='BlackHole 2ch', uid='another'))
        with self.assertRaisesRegex(RuntimeError, 'exactly one'):
            self.session.run()
        self.assertFalse(any('set' in c for c in self.calls))

    def test_signal_after_route_mutation_disables_mirror(self):
        original = self.command.side_effect
        def terminate(args, capture=False, timeout=5):
            value = original(args, capture, timeout)
            if args[-2:] == ['output', 'virtual16']:
                signal.raise_signal(signal.SIGTERM)
            return value
        self.command.side_effect = terminate
        with self.assertRaisesRegex(RuntimeError, 'SIGTERM'):
            self.session.run()
        self.restored()
        self.assertEqual(len([c for c in self.calls if c[0] == '/bin/launchctl']), 2)

    def test_child_commands_are_isolated_and_gate_enabled(self):
        self.session.runtime.mkdir(parents=True)
        with patch('session.subprocess.Popen') as popen:
            Session.start_children(self.session)
        self.assertEqual(len(popen.call_args_list), 2)
        for call in popen.call_args_list:
            self.assertTrue(call.kwargs['start_new_session'])
            self.assertIn('--mute-port4416', call.args[0])
        down = popen.call_args_list[1].args[0]
        self.assertIn('/task/control', down)
        self.assertIn('/task/hosts', down)
        for output in self.session.logs:
            output.close()

    def test_route_change_happens_after_mux_and_manager(self):
        self.session.run()
        check = next(i for i, c in enumerate(self.calls) if '-O' in c)
        restart = next(i for i, c in enumerate(self.calls) if c[0] == '/bin/launchctl')
        set_input = next(i for i, c in enumerate(self.calls) if c[-2:] == ['input', 'virtual2'])
        set_output = next(i for i, c in enumerate(self.calls) if c[-2:] == ['output', 'virtual16'])
        self.assertLess(check, restart)
        self.assertLess(restart, set_input)
        self.assertLess(set_input, set_output)
        self.assertIn('ProxyCommand=/usr/bin/false', self.calls[check])

    def test_restart_allows_launchd_delay_exceeding_five_seconds(self):
        import subprocess
        def delayed(args, **kwargs):
            # Simulate an owned kickstart completing after the 30-second throttle.
            required = 31 if args[0] == '/bin/launchctl' else 0
            if kwargs['timeout'] < required:
                raise subprocess.TimeoutExpired(args, kwargs['timeout'])
            return MagicMock(returncode=0, stdout=b'')
        with patch('session.subprocess.run', side_effect=delayed) as run:
            # Exercise the real restart and command dispatch, not mocked command.
            with patch.object(self.session, 'command', wraps=lambda *a, **kw: Session.command(self.session, *a, **kw)):
                self.session.restart()
                self.session.defaults('input', 'original-input-secret')
        self.assertEqual(run.call_args_list[0].kwargs['timeout'], 40)
        self.assertEqual(run.call_args_list[1].kwargs['timeout'], 5)

    def test_expired_lease_after_delayed_restart_never_activates_route(self):
        self.session.seconds = 15
        with patch('session.time.monotonic', return_value=0) as monotonic:
            with patch.object(self.session, 'restart', side_effect=lambda: setattr(monotonic, 'return_value', 31)):
                with self.assertRaisesRegex(RuntimeError, 'expired before audio route'):
                    self.session.run()
        self.restored()
        self.assertFalse(any(c[-1] in ('virtual2', 'virtual16') for c in self.calls))
        self.assertEqual(self.final()['cleanup_errors'], [])

    def test_external_output_drift_after_success_fails_closed_without_retry(self):
        self.session.seconds = 3
        now = [0.0]
        reads = [0]
        original = self.command.side_effect
        def drift(args, capture=False, timeout=5):
            if capture:
                reads[0] += 1
                if reads[0] == 3:
                    self.data['output'] = 'external-output-secret'
            return original(args, capture, timeout)
        self.command.side_effect = drift
        with patch('session.time.monotonic', side_effect=lambda: now[0]):
            with patch('session.time.sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
                with self.assertRaisesRegex(RuntimeError, 'Audio route drift detected for output'):
                    self.session.run()
        self.restored()
        self.assertEqual(reads[0], 3)
        self.assertEqual(len([c for c in self.calls if c[-2:] == ['output', 'virtual16']]), 1)
        self.assertFalse(json.loads(self.session.baseline_path.read_text())['active'])
        self.assertEqual(self.final()['status'], 'failed')
        self.assertNotIn('external-output-secret', json.dumps(self.final()))
        self.assertLess(now[0], 2)

    def test_initial_route_verification_detects_input_reset(self):
        original = self.command.side_effect
        def reset(args, capture=False, timeout=5):
            value = original(args, capture, timeout)
            if args[-2:] == ['output', 'virtual16']:
                self.data['input'] = 'external-input-secret'
            return value
        self.command.side_effect = reset
        with self.assertRaisesRegex(RuntimeError, 'Audio route drift detected for input'):
            self.session.run()
        self.restored()
        self.assertEqual(self.final()['status'], 'failed')

    def test_duration_validation_and_default(self):
        for value in (0, -1, 301, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                validate_seconds(value)
        args = parse_args(['--host', 'root@host', '--control-path', '/task/control', '--known-hosts', '/task/hosts'])
        self.assertEqual(args.seconds, 240)

    def test_dynamic_mirror_skips_restarts_and_cleans_children_and_route(self):
        self.session.dynamic_mirror = True
        child = MagicMock(pid=12345)
        self.start.side_effect = lambda: self.session.children.append(child)
        with patch('session.os.killpg') as kill, patch('session.sys.stdout', new_callable=io.StringIO):
            self.session.run()
        self.restored()
        self.assertFalse(any(c[0] == '/bin/launchctl' for c in self.calls))
        kill.assert_called_once_with(12345, signal.SIGTERM)
        child.wait.assert_called_once_with(timeout=2)
        self.assertFalse(json.loads(self.session.baseline_path.read_text())['active'])

    def test_ready_event_follows_exact_route_verification_and_is_safe(self):
        observed = []
        original = self.session.verify_route
        def verify(selected):
            original(selected)
            observed.append('verified')
        def emit(*args, **kwargs):
            self.assertEqual(observed, ['verified'])
            observed.append('ready')
            self.assertTrue(kwargs.get('flush'))
            event = json.loads(args[0])
            self.assertEqual(event, {'event': 'ready', 'expires_at': 1000020})
        with patch.object(self.session, 'verify_route', side_effect=verify), patch('session.time.time', return_value=1000), patch('builtins.print', side_effect=emit) as output:
            self.session.run()
        output.assert_called_once()

    def test_route_verification_failure_emits_no_ready(self):
        with patch.object(self.session, 'verify_route', side_effect=RuntimeError('Audio route drift detected for input')), patch('session.sys.stdout', new_callable=io.StringIO) as output:
            with self.assertRaisesRegex(RuntimeError, 'drift'):
                self.session.run()
        self.assertEqual(output.getvalue(), '')
        self.restored()

    def test_dynamic_mirror_failure_cleans_route_without_restarts(self):
        self.session.dynamic_mirror = True
        with patch.object(self.session, 'verify_route', side_effect=RuntimeError('Audio route drift detected for output')):
            with self.assertRaisesRegex(RuntimeError, 'drift'):
                self.session.run()
        self.restored()
        self.assertFalse(any(c[0] == '/bin/launchctl' for c in self.calls))
        self.assertEqual([json.loads(line)['event'] for line in self.stdout.getvalue().splitlines()], ['final'])

    def test_ready_refused_for_cancellation_during_final_output_set(self):
        original = self.command.side_effect
        def cancel(args, capture=False, timeout=5):
            value = original(args, capture, timeout)
            if args[-2:] == ['output', 'virtual16']:
                self.session.stop_signal = signal.SIGTERM
            return value
        self.command.side_effect = cancel
        with self.assertRaisesRegex(RuntimeError, 'SIGTERM'):
            self.session.run()
        self.assertEqual(self.stdout.getvalue(), '')
        self.restored()

    def test_ready_refused_when_final_verification_invalidates_lease(self):
        for condition, message in (('cancel', 'SIGTERM'), ('expire', 'expired before'), ('child', 'child exited')):
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as folder:
                self.session.root = Path(folder)
                self.session.runtime = Path(folder) / 'runtime'
                self.session.baseline_path = self.session.runtime / 'defaults.json'
                self.session.flag = Path(folder) / 'flag.json'
                self.session.stop_signal = None
                self.session.seconds = 3
                self.port.side_effect = None
                self.port.return_value = True
                # Initial occupied-port check must still be false.
                self.port.side_effect = [False, True, True, True, True]
                self.alive.side_effect = None
                self.stdout.truncate(0)
                self.stdout.seek(0)
                now = [0]
                original = self.session.verify_route
                def invalidate(selected):
                    original(selected)
                    if condition == 'cancel':
                        self.session.stop_signal = signal.SIGTERM
                    elif condition == 'expire':
                        now[0] = 4
                    else:
                        self.alive.side_effect = RuntimeError('Native Voice audio child exited before session expiry')
                with patch('session.time.monotonic', side_effect=lambda: now[0]), patch.object(self.session, 'verify_route', side_effect=invalidate):
                    with self.assertRaisesRegex(RuntimeError, message):
                        self.session.run()
                self.assertEqual(self.stdout.getvalue(), '')
                self.restored()

    def test_dynamic_mirror_constructor_and_cli_are_opt_in(self):
        base = ['--host', 'root@host', '--control-path', '/task/control', '--known-hosts', '/task/hosts']
        self.assertFalse(parse_args(base).dynamic_mirror)
        self.assertTrue(parse_args(base + ['--dynamic-mirror']).dynamic_mirror)
        self.assertFalse(self.session.dynamic_mirror)
        session = Session(.02, 'root@host', '/task/control', '/task/hosts', Path(self.temp.name), dynamic_mirror=True)
        self.assertTrue(session.dynamic_mirror)

    def test_dynamic_cancel_emits_clean_final_before_raising(self):
        self.session.dynamic_mirror = True
        self.start.side_effect = lambda: setattr(self.session, 'stop_signal', signal.SIGTERM)
        with self.assertRaisesRegex(RuntimeError, 'SIGTERM'):
            self.session.run()
        events = [json.loads(line) for line in self.stdout.getvalue().splitlines()]
        self.assertEqual(events, [self.final()])
        self.assertEqual(events[0]['cleanup_errors'], [])
        self.assertNotIn('secret', json.dumps(events))

    def test_dynamic_success_emits_one_final(self):
        self.session.dynamic_mirror = True
        result = self.session.run()
        events = [json.loads(line) for line in self.stdout.getvalue().splitlines()]
        self.assertEqual([event['event'] for event in events], ['ready', 'final'])
        self.assertEqual(events[-1], result)

    def test_non_dynamic_run_preserves_ready_only_stdout(self):
        self.session.run()
        self.assertEqual([json.loads(line)['event'] for line in self.stdout.getvalue().splitlines()], ['ready'])

    def test_cli_non_dynamic_success_preserves_final(self):
        from session import main
        args = ['--host', 'root@host', '--control-path', '/task/control', '--known-hosts', '/task/hosts']
        with patch('session.Session', return_value=self.session):
            main(args)
        self.assertEqual([json.loads(line)['event'] for line in self.stdout.getvalue().splitlines()], ['ready', 'final'])

    def test_dynamic_lock_refusal_emits_no_final(self):
        self.session.dynamic_mirror = True
        self.session.runtime.mkdir(parents=True)
        with (self.session.runtime / 'session.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'Another Native Voice session'):
                self.session.run()
        self.assertEqual(self.stdout.getvalue(), '')

    def test_cli_dynamic_success_does_not_duplicate_final(self):
        from session import main
        args = ['--host', 'root@host', '--control-path', '/task/control', '--known-hosts', '/task/hosts', '--dynamic-mirror']
        with patch('session.Session', return_value=self.session):
            self.session.dynamic_mirror = True
            main(args)
        self.assertEqual([json.loads(line)['event'] for line in self.stdout.getvalue().splitlines()], ['ready', 'final'])

    def test_cli_dynamic_cancel_final_precedes_error(self):
        from session import main
        self.session.dynamic_mirror = True
        self.start.side_effect = lambda: setattr(self.session, 'stop_signal', signal.SIGTERM)
        args = ['--host', 'root@host', '--control-path', '/task/control', '--known-hosts', '/task/hosts', '--dynamic-mirror']
        with patch('session.Session', return_value=self.session), self.assertRaises(SystemExit):
            main(args)
        self.assertEqual([json.loads(line)['event'] for line in self.stdout.getvalue().splitlines()], ['final', 'error'])


if __name__ == '__main__':
    unittest.main()
