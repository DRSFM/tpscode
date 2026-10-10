import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from profiles_capture import ProfilesCapture, discover_profiles, restore_profiles, run_profiles_audit, validate_upstream


class ProfilesCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.user = Path(self.temp.name)
        self.state = self.user / 'audits' / 'profiles-state.json'
        self.manager = None
        self.compat = patch('profiles_capture.candidate_config_supported', return_value=True)
        self.compat.start()
        self.login = patch('profiles_capture.has_chatgpt_login', return_value=True)
        self.login.start()

    def tearDown(self):
        if self.manager:
            self.manager.stop()
        self.compat.stop()
        self.login.stop()
        self.temp.cleanup()

    def config(self, name, content=None, kind='profiles'):
        home = self.user / '.codex-api' / kind / name if name else self.user / '.codex'
        home.mkdir(parents=True)
        path = home / 'config.toml'
        original = content or b'model_provider = "apicodex"\nmodel = "m"\n[model_providers.apicodex]\nbase_url = "https://gateway.example/v1" # note\nwire_api = "responses"\nenv_key = "PRIVATE_ENV_NAME"\n'
        path.write_bytes(original)
        return path, original

    def start(self):
        self.manager = ProfilesCapture(self.user, self.state.parent, official_port=0, include_accounts=True)
        self.manager.start()
        return self.manager

    def test_default_capture_leaves_account_login_configs_byte_for_byte_unchanged(self):
        paths = [self.config('', b'model_provider="openai"\nmodel="account-model"\n'),
                 self.config('work', b'model_provider="openai"\n', kind='accounts'),
                 self.config('account-with-stale-api-provider', kind='accounts')]
        self.config('api')
        self.manager = ProfilesCapture(self.user, self.state.parent, official_port=0)
        with patch('profiles_capture.has_chatgpt_login', return_value=False):
            self.manager.start()
        self.assertEqual([target.profile for target in self.manager.active], ['api'])
        for path, original in paths:
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(sum(row['state'] == '只读统计' for row in self.manager.status()), 3)

    def test_discovery_and_start_cover_official_accounts_and_api_profiles_then_restore_bytes(self):
        paths = [self.config('', b'model_provider = "openai"\nmodel = "m"\n'),
                 self.config('work', b'model_provider = "openai"\n', kind='accounts'), self.config('anyrouter')]
        self.assertEqual(len(discover_profiles(self.user)), 3)
        manager = self.start()
        self.assertEqual(len(manager.active), 3)
        self.assertEqual({x.profile for x in manager.active}, {'官方', '账号/work', 'anyrouter'})
        for path, _ in paths:
            self.assertIn('# CODEX TPS STATE ', path.read_text())
            data = tomllib.loads(path.read_text())
            url = data.get('openai_base_url') if data['model_provider'] == 'openai' else data['model_providers']['apicodex']['base_url']
            self.assertTrue(url.startswith('http://127.0.0.1:'))
            self.assertNotIn('profile', data)
        self.assertNotIn('PRIVATE_ENV_NAME', self.state.read_text(encoding='utf-8'))
        manager.stop()
        for path, original in paths:
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn(b'CODEX TPS STATE', path.read_bytes())

    def test_invalid_url_is_skipped_and_never_echoed_or_written(self):
        self.config('good')
        path, original = self.config('bad', b'model_provider="apicodex"\n[model_providers.apicodex]\nwire_api="responses"\nbase_url="sk-NOT_A_REAL_KEY_TEST_ONLY"\n')
        manager = self.start()
        self.assertEqual(len(manager.active), 1)
        self.assertEqual(path.read_bytes(), original)
        self.assertNotIn('sk-', json.dumps(manager.status(), ensure_ascii=False))
        self.assertNotIn('sk-', self.state.read_text(encoding='utf-8'))
        for url in ('sk-NOT_A_REAL_KEY', 'https://user:password@example.com/v1', 'https://example.com/v1?key=secret', 'https://example.com/sk-NOT_A_REAL_KEY'):
            with self.assertRaises(ValueError) as error:
                validate_upstream(url)
            self.assertNotIn(url, str(error.exception))

    def test_default_api_root_is_captured_and_restored_as_default_profile(self):
        home = self.user / '.codex-api'
        home.mkdir()
        path = home / 'config.toml'
        original = b'model_provider="apicodex"\n[model_providers.apicodex]\nbase_url="https://gateway.example/v1"\nwire_api="responses"\n'
        path.write_bytes(original)
        self.manager = manager = ProfilesCapture(self.user, self.state.parent, official_port=0)
        manager.start()
        self.assertEqual([x.profile for x in manager.active], ['default'])
        manager.stop()
        self.assertEqual(path.read_bytes(), original)

    def test_unified_window_loads_historical_tps_and_preserves_audit_and_saved_homes(self):
        import os
        from test_core import assistant, event, meta, record, start
        path, original = self.config('anyrouter')
        sessions = path.parent / 'sessions'
        sessions.mkdir()
        events = [meta(), start(), event(1, 'turn_context', {'model': 'test-model', 'effort': 'high'}),
                  assistant(), record()]
        (sessions / 'rollout.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in events), encoding='utf-8')
        extra = self.user / 'custom-logs'
        (extra / 'sessions').mkdir(parents=True)
        audit = self.user / 'saved-audit.jsonl'
        audit.write_text('', encoding='utf-8')

        def gui(monitor, args):
            samples = monitor.refresh()
            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0].effective_tps, 10)
            self.assertEqual(samples[0].model, 'test-model')
            self.assertEqual(args.view, 'speed')
            self.assertTrue(args.readonly)
            self.assertFalse(args.fixed_homes)
            self.assertEqual(args.user_home, self.user)
            self.assertIn(extra, monitor.homes)
            self.assertIn(audit, monitor.audit_monitor.paths)
            self.assertNotIn(self.state.parent / 'profiles.jsonl', monitor.audit_monitor.paths)
            self.assertEqual(monitor.audit_rows[0].profile, 'anyrouter')
            return 0

        with patch.dict(os.environ, {'CODEX_HOME': ''}), \
                patch('codex_tps.load_settings', return_value={'extra_homes': [str(extra)], 'audit_logs': [str(audit)]}), \
                patch('profiles_capture.start_profiles_service', side_effect=AssertionError('Readonly must not start forwarding')), \
                patch('desktop.run_gui', side_effect=gui):
            self.assertEqual(run_profiles_audit(self.user, self.state.parent, port=0), 0)
        self.assertEqual(path.read_bytes(), original)

    def test_bom_crlf_quoted_table_and_user_edits_are_preserved(self):
        original = b'\xef\xbb\xbfmodel_provider="apicodex"\r\n[model_providers."apicodex"]\r\nbase_url = \'https://gateway.example/v1\' # note\r\nwire_api="responses"\r\n'
        path, _ = self.config('quoted', original)
        manager = self.start()
        self.assertEqual(len(manager.active), 1)
        with path.open('ab') as stream:
            stream.write(b'# user added\r\n')
        manager.stop()
        self.assertEqual(path.read_bytes(), original + b'# user added\r\n')

    def test_crash_recovery_and_changed_address_do_not_overwrite_user_choice(self):
        first, original = self.config('first')
        changed, _ = self.config('changed')
        manager = self.start()
        endpoint = next(x.endpoint for x in manager.active if x.home == changed.parent)
        changed.write_text(changed.read_text().replace(endpoint, 'https://new.example/v1'))
        for target in manager.active:
            target.server.shutdown()
            target.server.server_close()
        result = restore_profiles(self.state)
        self.assertEqual(first.read_bytes(), original)
        self.assertIn('https://new.example/v1', changed.read_text())
        self.assertNotIn('CODEX TPS PROFILES AUDIT', changed.read_text())
        self.assertTrue(any(x['state'] == '用户已修改地址' for x in result))

    def test_commented_or_removed_inserted_url_recovers_marker_and_preserves_user_edit(self):
        path, original = self.config('', b'model_provider="openai"\nmodel="m"\n')
        manager = self.start()
        text = path.read_text()
        generated = next(line for line in text.splitlines(keepends=True) if line.startswith('openai_base_url'))
        for replacement in ('# ' + generated, ''):
            with self.subTest(replacement=replacement):
                path.write_text(text.replace(generated, replacement) + '# user edit\n')
                state = dict(manager.state)
                state['active'] = True
                self.state.write_text(json.dumps(state), encoding='utf-8')
                result = restore_profiles(self.state)
                self.assertEqual(result[0]['state'], '用户已移除或注释地址')
                self.assertEqual(path.read_text(), replacement + original.decode() + '# user edit\n')
                self.assertFalse(json.loads(self.state.read_text(encoding='utf-8'))['active'])

    def test_partial_recovery_keeps_journal_retryable_and_cli_reports_failure(self):
        path, original = self.config('first')
        self.start()
        with patch('profiles_capture._restore_entry', side_effect=OSError('write failure')):
            self.assertEqual(run_profiles_audit(self.user, self.state.parent, restore=True), 1)
        self.assertTrue(json.loads(self.state.read_text(encoding='utf-8'))['active'])
        self.assertNotEqual(path.read_bytes(), original)
        self.assertEqual(run_profiles_audit(self.user, self.state.parent, restore=True), 0)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(json.loads(self.state.read_text(encoding='utf-8'))['active'])

    def test_preflight_failure_and_concurrent_user_edit_do_not_write_candidate(self):
        path, original = self.config('anyrouter')
        with patch('profiles_capture.candidate_config_supported', return_value=False):
            manager = self.start()
        self.assertEqual(manager.active, [])
        self.assertEqual(path.read_bytes(), original)
        manager.stop()
        def edit(candidate):
            path.write_bytes(original + b'# user change\n')
            return True
        with patch('profiles_capture.candidate_config_supported', side_effect=edit):
            manager = self.start()
        self.assertEqual(manager.active, [])
        self.assertEqual(path.read_bytes(), original + b'# user change\n')

    def test_inline_table_is_skipped_without_rewriting_other_semantics(self):
        path, original = self.config('inline', b'model_provider="apicodex"\nmodel_providers.apicodex = {wire_api="responses", base_url="https://example.com/v1"}\n')
        self.start()
        self.assertEqual(path.read_bytes(), original)

    def test_new_profile_is_discovered_and_existing_user_address_edit_is_not_reapplied(self):
        first, _ = self.config('first')
        manager = self.start()
        self.config('later')
        manager.scan()
        self.assertEqual(len(manager.active), 2)
        endpoint = next(x.endpoint for x in manager.active if x.home == first.parent)
        first.write_text(first.read_text().replace(endpoint, 'https://changed.example/v1'))
        manager.scan()
        row = next(x for x in manager.status() if x['profile'] == 'first')
        self.assertEqual(row['state'], '配置已修改')
        self.assertIn('https://changed.example/v1', first.read_text())

    def test_partial_config_write_failure_restores_before_skipping_profile(self):
        path, original = self.config('failure')
        from profiles_capture import _atomic_write
        fired = []
        def fail_after_write(target, content):
            _atomic_write(target, content)
            if target == path and not fired:
                fired.append(True)
                raise OSError('injected write failure')
        with patch('profiles_capture._atomic_write', side_effect=fail_after_write):
            manager = self.start()
        self.assertEqual(manager.active, [])
        self.assertEqual(path.read_bytes(), original)

    def test_two_profiles_share_one_log_and_keep_identical_response_ids_separate(self):
        import socket
        import threading
        from http.server import ThreadingHTTPServer
        from test_websocket_capture import WSUpstream, frame, receive
        from reasoning_audit import AuditMonitor
        server = ThreadingHTTPServer(('127.0.0.1', 0), WSUpstream)
        server.mode, server.frames = 'single', []
        server.created, server.gate = threading.Event(), threading.Event()
        server.gate.set()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        config = (f'model_provider="apicodex"\n[model_providers.apicodex]\nwire_api="responses"\n'
                  f'base_url="http://127.0.0.1:{server.server_port}/backend"\n').encode()
        self.config('anyrouter', config)
        self.config('other', config)
        try:
            manager = self.start()
            for target in manager.active:
                from urllib.parse import urlsplit
                conn = socket.create_connection(('127.0.0.1', urlsplit(target.endpoint).port), timeout=5)
                reader = conn.makefile('rb')
                try:
                    origin = 'codex_desktop' if target.profile == 'anyrouter' else 'codex_cli_rs'
                    conn.sendall(('GET /v1/responses HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                                  'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                                  f'originator: {origin}\r\n\r\n').encode())
                    self.assertIn(b'101', reader.readline())
                    while reader.readline() != b'\r\n':
                        pass
                    conn.sendall(frame(dict(type='response.create', model='m', reasoning={'effort':'xhigh'}, input='PRIVATE'), masked=True))
                    while receive(reader)[0] != 8:
                        pass
                finally:
                    conn.shutdown(socket.SHUT_RDWR)
                    reader.close()
                    conn.close()
            monitor = AuditMonitor([manager.audit_path])
            rows = monitor.refresh()
            self.assertEqual(len(rows), 2)
            self.assertEqual({row.profile for row in rows}, {'anyrouter', 'other'})
            self.assertEqual({row.client for row in rows}, {'Desktop', 'CLI'})
            self.assertEqual(len({row.response_id for row in rows}), 1)
            self.assertEqual(monitor.bad_lines, 0)
            self.assertNotIn('PRIVATE', manager.audit_path.read_text())
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
