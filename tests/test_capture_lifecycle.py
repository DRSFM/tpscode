import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from capture_guard import CaptureGuard, process_alive, recover_stale_profiles
from capture_lock import CaptureLock
from capture_service import start_profiles_service
from profiles_capture import _plan, restore_profiles, run_profiles_audit


ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError('Lifecycle check timed out')


class CaptureLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'audits' / 'profiles-state.json'
        self.state.parent.mkdir()
        self.home = self.root / '.codex-api' / 'profiles' / 'api'
        self.home.mkdir(parents=True)
        self.config = self.home / 'config.toml'
        self.original = b'model_provider="apicodex"\nmodel="test-model"\n[model_providers.apicodex]\nbase_url="https://example.test/v1"\nwire_api="responses"\n'
        self.config.write_bytes(self.original)
        self.token = 'a' * 32

    def journal(self, pid, token=None):
        token = token or self.token
        candidate, entry = _plan(self.original, ['model_providers', 'apicodex', 'base_url'],
                                 'https://example.test/v1', 'http://127.0.0.1:19876/v1', token, self.state)
        entry.update(home=str(self.home), profile='api')
        self.config.write_bytes(candidate)
        self.state.write_text(json.dumps(dict(schema_version=1, token=token, pid=pid, active=True, entries=[entry])))

    def test_capture_lock_contention_times_out_cleanly_and_can_be_reacquired(self):
        lock_path = self.state.parent / '.test-capture.lock'
        with CaptureLock(lock_path):
            with self.assertRaisesRegex(ValueError, '已有采集实例'):
                with CaptureLock(lock_path, timeout=.15):
                    self.fail('Contender acquired a held lock')
        with CaptureLock(lock_path):
            self.assertEqual(lock_path.stat().st_size, 0)

    def test_stale_owner_recovers_but_live_owner_is_never_rewritten(self):
        self.journal(os.getpid())
        before = self.config.read_bytes()
        self.assertEqual(recover_stale_profiles(self.state), [])
        self.assertEqual(self.config.read_bytes(), before)
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        child.terminate()
        child.wait(timeout=5)
        self.assertFalse(process_alive(child.pid))
        self.journal(child.pid)
        self.assertTrue(recover_stale_profiles(self.state))
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_guard_does_not_restore_a_newer_capture_token(self):
        self.journal(os.getpid(), 'b' * 32)
        before = self.config.read_bytes()
        guard = CaptureGuard('profiles', self.state, self.token).start()
        guard.finish()
        self.assertEqual(self.config.read_bytes(), before)
        self.assertTrue(json.loads(self.state.read_bytes())['active'])

    def test_forced_capture_process_exit_restores_urls_without_gui_cleanup(self):
        script = '''
import sys,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from profiles_capture import ProfilesCapture
with patch('profiles_capture.candidate_config_supported',return_value=True):
    capture=ProfilesCapture(Path(sys.argv[2]),Path(sys.argv[2])/'audits',official_port=0)
    capture.start()
    time.sleep(60)
'''
        child = subprocess.Popen([sys.executable, '-c', script, str(ROOT), str(self.root)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            def ready():
                if child.poll() is not None:
                    self.fail('Capture worker exited before readiness')
                return self.state.exists() and json.loads(self.state.read_bytes()).get('ready')
            wait_for(ready)
            self.assertNotEqual(self.config.read_bytes(), self.original)
            child.terminate()
            child.wait(timeout=5)
            wait_for(lambda: not json.loads(self.state.read_bytes())['active'])
            self.assertEqual(self.config.read_bytes(), self.original)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
                wait_for(lambda: self.config.read_bytes() == self.original)

    def test_readonly_legacy_entry_ignores_capture_state_and_keeps_all_configs(self):
        official = self.root / '.codex' / 'config.toml'
        official.parent.mkdir()
        official.write_bytes(b'model="official-test"\nmodel_provider="openai"\n')
        original_official = official.read_bytes()
        self.state.write_bytes(b'broken legacy capture state')
        with patch('codex_tps.load_settings', return_value={}), \
                patch('profiles_capture.start_profiles_service', side_effect=AssertionError('No relay')), \
                patch('desktop.run_gui', return_value=0) as gui:
            self.assertEqual(run_profiles_audit(self.root, self.state.parent, port=0), 0)
        self.assertTrue(gui.call_args.args[1].readonly)
        self.assertFalse(hasattr(gui.call_args.args[1], 'capture_stopped'))
        self.assertEqual(official.read_bytes(), original_official)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(self.state.read_bytes(), b'broken legacy capture state')


if __name__ == '__main__':
    unittest.main()
