import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_tps import Monitor, main
from test_core import assistant, event, meta, record, start, usage


class ReadonlyMonitorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.user = Path(temp.name)
        self.homes = [self.user / '.codex', self.user / '.codex-api/profiles/api']
        self.configs = {}
        self.logs = []
        for i, home in enumerate(self.homes):
            (home / 'sessions').mkdir(parents=True)
            config = home / 'config.toml'
            config.write_bytes(b'model_provider="openai"\n' if i == 0 else
                              b'model_provider="apicodex"\n[model_providers.apicodex]\nbase_url="https://example.test/v1"\n')
            self.configs[config] = config.read_bytes()
            log = home / 'sessions/rollout.jsonl'
            rows = [meta(sid=f'session-{i}'), start(),
                    event(1, 'turn_context', {'model': 'test-model', 'effort': 'high'}),
                    assistant(), record(rid=f'response-{i}')]
            log.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            self.logs.append(log)

    def test_default_gui_refreshes_tps_and_effort_without_network_or_config_writes(self):
        def gui(monitor, args):
            self.assertTrue(args.readonly)
            first = monitor.refresh()
            self.assertEqual(len(first), 2)
            self.assertEqual({s.effort for s in first}, {'high'})
            self.assertEqual({s.effective_tps for s in first}, {10})
            rows = [event(21, 'event_msg', {'type': 'task_started', 'turn_id': 'turn-two'}),
                    event(21, 'turn_context', {'model': 'test-model', 'effort': 'xhigh', 'turn_id': 'turn-two'}),
                    assistant(26), record(26, 'response-two', usage(150, 60), usage(250, 100))]
            with self.logs[1].open('a', encoding='utf-8') as stream:
                stream.write(''.join(json.dumps(r) + '\n' for r in rows))
            refreshed = monitor.refresh()
            new = [s for s in refreshed if s.response_id == 'response-two']
            self.assertEqual(len(new), 1)
            self.assertEqual((new[0].effort, new[0].effective_tps), ('xhigh', 30))
            self.assertFalse(hasattr(args, 'capture_stopped'))
            return 0

        with patch('codex_tps.load_settings', return_value={}), \
                patch('codex_tps.discover_homes', return_value=self.homes), \
                patch('capture_guard.recover_stale_profiles', side_effect=AssertionError('No recovery writes')), \
                patch('profiles_capture.start_profiles_service', side_effect=AssertionError('No relay')), \
                patch('subprocess.Popen', side_effect=AssertionError('No subprocess')), \
                patch('socket.socket', side_effect=AssertionError('No network socket')), \
                patch('desktop.run_gui', side_effect=gui):
            self.assertEqual(main([]), 0)
        for config, original in self.configs.items():
            self.assertEqual(config.read_bytes(), original)

    def test_capture_commands_are_disabled_without_starting_listeners(self):
        with patch('audit_capture.run_capture', side_effect=AssertionError('No relay')), \
                patch('profiles_capture.ProfilesCapture.start', side_effect=AssertionError('No relay')), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['capture', '--upstream', 'https://example.test/v1',
                                   '--audit-log', str(self.user / 'audit.jsonl')]), 1)
            self.assertEqual(main(['profiles-audit', '--no-gui', '--user-home', str(self.user),
                                   '--state-dir', str(self.user / 'audits')]), 1)
            self.assertEqual(main(['official-audit', '--no-gui']), 1)

    def test_native_metadata_discovered_after_start_and_reopen_without_config_changes(self):
        monitor = Monitor(self.homes)
        monitor.refresh()
        self.assertFalse(monitor.errors)
        for i, home in enumerate(self.homes):
            path = home / 'audits/native-reasoning.jsonl'
            path.parent.mkdir()
            base = dict(schema_version=1, source_id=f'client-{i}', request_id=f'request-{i}',
                        attempt_id='1', timestamp='2026-10-03T12:00:10Z',
                        protocol='responses', observation_boundary='client_to_provider',
                        session_id=f'session-{i}', client='Desktop',
                        profile='官方' if i == 0 else 'api')
            events = [dict(base, event_type='request_sent', request={'reasoning': {'effort': 'low'}, 'stream': True}),
                      dict(base, event_type='response_completed', response={'id': f'response-{i}', 'reasoning': {'effort': 'high'}})]
            path.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
        with patch('subprocess.Popen', side_effect=AssertionError('No collector launch')), \
                patch('socket.socket', side_effect=AssertionError('No network')):
            for reader in (monitor, Monitor(self.homes)):
                reader.refresh()
                self.assertFalse(reader.errors)
                rows = [r for r in reader.audit_rows if r.outbound_effort]
                self.assertEqual(len(rows), 2)
                self.assertEqual({(r.outbound_effort, r.final_effort) for r in rows}, {('low', 'high')})
                self.assertEqual({r.profile for r in rows}, {'官方', 'api'})
                self.assertEqual(len({r.home for r in rows}), 2)
        for config, original in self.configs.items():
            self.assertEqual(config.read_bytes(), original)

    def test_native_discovery_and_explicit_path_do_not_duplicate_records(self):
        path = self.homes[0] / 'audits/native-reasoning.jsonl'
        path.parent.mkdir()
        path.write_text(json.dumps(dict(schema_version=1, source_id='client', request_id='request',
            attempt_id='1', timestamp='2026-10-03T12:00:10Z', protocol='responses',
            observation_boundary='client_to_provider', event_type='response_completed',
            response={'id': 'response-0', 'reasoning': {'effort': 'high'}})) + '\n', encoding='utf-8')
        monitor = Monitor(self.homes, audit_paths=[path])
        monitor.refresh()
        self.assertEqual(len(monitor.audit_monitor.files), 1)
        self.assertEqual(len(monitor.audit_monitor.refresh()), 1)

    def test_legacy_gui_commands_use_readonly_mode_without_recovery_or_forwarding(self):
        with patch('codex_tps.load_settings', return_value={}), \
                patch('codex_tps.discover_homes', return_value=self.homes), \
                patch('capture_guard.recover_stale_profiles', side_effect=AssertionError('No recovery writes')), \
                patch('profiles_capture.start_profiles_service', side_effect=AssertionError('No relay')), \
                patch('desktop.run_gui', return_value=0) as gui:
            self.assertEqual(main(['profiles-audit', '--user-home', str(self.user),
                                   '--state-dir', str(self.user / 'audits')]), 0)
            self.assertTrue(gui.call_args.args[1].readonly)
            self.assertEqual(main(['profiles-audit', '--include-official', '--user-home', str(self.user),
                                   '--state-dir', str(self.user / 'audits')]), 0)
            self.assertTrue(gui.call_args.args[1].readonly)
            self.assertEqual(main(['official-audit', '--codex-home', str(self.homes[0])]), 0)
            self.assertTrue(gui.call_args.args[1].readonly)
        for config, original in self.configs.items():
            self.assertEqual(config.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
