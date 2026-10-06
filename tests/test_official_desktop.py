import json
from pathlib import Path
import tempfile
import shutil
import tomllib
import unittest
from unittest.mock import patch

import codex_tps
from official_desktop import OfficialDesktopCapture, restore_official_config


class OfficialDesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / '.codex'
        self.home.mkdir()
        self.config = self.home / 'config.toml'
        self.original = b'model_provider = "openai"\nmodel = "test-model"\n[features]\nenable_request_compression = true\n'
        self.config.write_bytes(self.original)
        self.log = Path(self.temp.name) / 'audit.jsonl'
        self.captures = []
        self.login = patch('official_desktop.has_chatgpt_login', return_value=True)
        self.login.start()
        self.compatibility = patch('official_desktop.candidate_config_supported', return_value=True)
        self.compatibility.start()

    def tearDown(self):
        for capture in self.captures:
            capture.stop()
        self.login.stop()
        self.compatibility.stop()
        self.temp.cleanup()

    def capture(self):
        capture = OfficialDesktopCapture(self.home, self.log, port=0)
        self.captures.append(capture)
        return capture

    def test_base_url_preserves_builtin_provider_and_restores_original_bytes(self):
        capture = self.capture().start()
        current = tomllib.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(current['model_provider'], 'openai')
        self.assertEqual(current['model'], 'test-model')
        self.assertNotIn('profile', current)
        self.assertEqual(current['openai_base_url'], f'http://127.0.0.1:{capture.server.server_port}/v1')
        self.assertTrue(current['features']['enable_request_compression'])
        self.assertEqual(list(self.home.glob('tps-official-audit-*')), [])
        self.assertEqual(self.log.read_text(), '')
        capture.stop()
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_user_edits_and_original_bom_survive_stop(self):
        self.config.write_bytes(b'\xef\xbb\xbf' + self.original)
        capture = self.capture().start()
        with self.config.open('ab') as stream:
            stream.write(b'fast_mode = false\n')
        capture.stop()
        self.assertEqual(self.config.read_bytes(), b'\xef\xbb\xbf' + self.original + b'fast_mode = false\n')

    def test_recovery_after_crash_removes_only_our_prefix(self):
        capture = self.capture().start()
        capture.server.shutdown(); capture.server.server_close(); capture.server = None
        self.assertTrue(restore_official_config(self.home))
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse(restore_official_config(self.home))

    def test_preflight_loads_exact_candidate_before_real_config_write(self):
        def inspect_candidate(content):
            self.assertEqual(self.config.read_bytes(), self.original)
            data = tomllib.loads(content.decode())
            self.assertEqual(data['model_provider'], 'openai')
            self.assertNotIn('profile', data)
            return True
        with patch('official_desktop.candidate_config_supported', side_effect=inspect_candidate) as guard:
            self.capture().start()
        self.assertEqual(guard.call_count, 1)

    def test_concurrent_user_edit_is_not_overwritten(self):
        edited = self.original + b'# user change\n'
        def inspect_candidate(content):
            self.config.write_bytes(edited)
            return True
        capture = self.capture()
        with patch('official_desktop.candidate_config_supported', side_effect=inspect_candidate):
            with self.assertRaisesRegex(ValueError, '变化'):
                capture.start()
        self.assertEqual(self.config.read_bytes(), edited)
        self.assertIsNone(capture.server)

    def test_existing_profile_or_custom_connection_is_untouched(self):
        cases = (b'profile = "other"\n', b'model_provider = "custom"\n',
                 b'openai_base_url = "https://provider.example/v1"\n')
        for original in cases:
            self.config.write_bytes(original)
            with self.assertRaises(ValueError):
                self.capture().start()
            self.assertEqual(self.config.read_bytes(), original)
            self.assertEqual(list(self.home.glob('tps-official-audit-*')), [])

    def test_no_official_login_makes_no_configuration_change(self):
        with patch('official_desktop.has_chatgpt_login', return_value=False):
            with self.assertRaises(ValueError):
                self.capture().start()
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse(self.log.exists())

    def test_unsupported_candidate_never_changes_real_configuration(self):
        with patch('official_desktop.candidate_config_supported', return_value=False):
            with self.assertRaisesRegex(ValueError, '兼容性'):
                self.capture().start()
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(list(self.home.glob('tps-official-audit-*')), [])
        self.assertEqual(self.log.read_text(), '')

    def test_config_write_failure_stops_service_and_preserves_config(self):
        capture = self.capture()
        with patch('official_desktop._atomic_write', side_effect=OSError('test disk failure')):
            with self.assertRaises(OSError):
                capture.start()
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertIsNone(capture.server)
        self.assertEqual(list(self.home.glob('tps-official-audit-*')), [])

    def test_legacy_crash_marker_still_recovers_and_preserves_user_modified_profile(self):
        from hashlib import sha256
        token = 'a' * 32
        profile = self.home / f'tps-official-audit-{token}.config.toml'
        generated = b'openai_base_url = "http://127.0.0.1:8766/v1"\n'
        digest = sha256(generated).hexdigest()
        profile.write_bytes(generated + b'# user edit\n')
        self.config.write_bytes((f'# CODEX TPS OFFICIAL AUDIT {token} bom=0 sha={digest}\n'
                                 f'profile = "tps-official-audit-{token}"\n# END CODEX TPS OFFICIAL AUDIT\n').encode() + self.original)
        self.assertTrue(restore_official_config(self.home))
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertTrue(profile.exists())

    def test_second_instance_cannot_replace_first_owner(self):
        first = self.capture().start()
        before = self.config.read_bytes()
        with self.assertRaises(ValueError):
            self.capture().start()
        self.assertEqual(self.config.read_bytes(), before)
        first.stop()
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_cli_restore_dispatches_without_reading_session_logs(self):
        with patch('official_desktop.run_official_audit', return_value=0) as runner, \
                patch('codex_tps.discover_homes', side_effect=AssertionError('unnecessary session scan')):
            code = codex_tps.main(['official-audit', '--codex-home', str(self.home), '--restore'])
        self.assertEqual(code, 0)
        self.assertEqual(runner.call_args.args[0], self.home)
        self.assertTrue(runner.call_args.kwargs['restore'])


@unittest.skipUnless(shutil.which('codex'), 'Installed Codex config loader is unavailable')
class InstalledClientCompatibilityTests(unittest.TestCase):
    def test_actual_client_accepts_base_url_and_rejects_legacy_profile(self):
        from official_desktop import candidate_config_supported
        self.assertTrue(candidate_config_supported(b'openai_base_url = "http://127.0.0.1:1/v1"\nmodel_provider = "openai"\n'))
        self.assertFalse(candidate_config_supported(b'profile = "tps_legacy"\nmodel_provider = "openai"\n'))


if __name__ == '__main__':
    unittest.main()
