import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_tps import main
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
