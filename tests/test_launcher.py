import json
import os
import runpy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

LAUNCHER = Path(__file__).resolve().parents[1] / 'tpscode.cmd'
GLOBAL_LAUNCHER = LAUNCHER.with_name('global-launch.cmd')
GLOBAL_SCRIPT = LAUNCHER.with_name('global-launch.ps1')


class WindowedLauncherTests(unittest.TestCase):
    def setUp(self):
        focus = patch('window_instance.focus_profiles_window', return_value=False)
        self.focus = focus.start()
        self.addCleanup(focus.stop)

    def test_no_arguments_start_all_profiles_capture(self):
        entry = LAUNCHER.with_name('launch.pyw')
        with patch('sys.argv', [str(entry)]), patch('codex_tps.main', return_value=0) as main:
            runpy.run_path(str(entry), run_name='__main__')
        main.assert_called_once_with(['profiles-audit'])

    def test_running_capture_window_is_reused_without_starting_another_manager(self):
        entry = LAUNCHER.with_name('launch.pyw')
        self.focus.return_value = True
        with patch('sys.argv', [str(entry)]), patch('codex_tps.main', return_value=0) as main:
            runpy.run_path(str(entry), run_name='__main__')
        self.focus.assert_called_once()
        main.assert_not_called()

    def test_explicit_readonly_gui_does_not_reuse_capture_window(self):
        entry = LAUNCHER.with_name('launch.pyw')
        with patch('sys.argv', [str(entry), 'gui']), patch('codex_tps.main', return_value=0) as main:
            runpy.run_path(str(entry), run_name='__main__')
        main.assert_called_once_with(['gui'])
        self.focus.assert_not_called()

    def test_official_audit_arguments_reach_application_instead_of_default_readonly_gui(self):
        entry = LAUNCHER.with_name('launch.pyw')
        with patch('sys.argv', [str(entry), 'official-audit']), patch('codex_tps.main', return_value=0) as main:
            runpy.run_path(str(entry), run_name='__main__')
        main.assert_called_once_with(['official-audit'])

    def test_profiles_audit_arguments_reach_unified_capture(self):
        entry = LAUNCHER.with_name('launch.pyw')
        with patch('sys.argv', [str(entry), 'profiles-audit']), patch('codex_tps.main', return_value=0) as main:
            runpy.run_path(str(entry), run_name='__main__')
        main.assert_called_once_with(['profiles-audit'])


@unittest.skipUnless(os.name == 'nt', 'Windows command launcher')
class LauncherTests(unittest.TestCase):
    def launch(self, path, args='', env=None):
        command = f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /s /c ""{path}" {args}"'
        return subprocess.run(command, env=env, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=20)

    def fake_app(self, path):
        path.mkdir(parents=True, exist_ok=True)
        (path/'codex_tps.py').write_text('# Application marker\n', encoding='ascii')
        (path/'tps.cmd').write_text('@echo off\necho CLI:%*\nexit /b 0\n', encoding='ascii')
        (path/'Start-Codex-TPS.cmd').write_text('@echo off\necho DESKTOP\nexit /b 0\n', encoding='ascii')

    def configured_launcher(self, profile, source):
        base = profile/'.local/bin'
        base.mkdir(parents=True)
        path = base/'tpscode.cmd'
        path.write_bytes(GLOBAL_LAUNCHER.read_bytes())
        (base/'tpscode-launch.ps1').write_bytes(GLOBAL_SCRIPT.read_bytes())
        (base/'tpscode-install.json').write_text(json.dumps({
            'managedBy': 'codex-tps-local-installer', 'source': str(source)
        }), encoding='utf-8')
        return path

    def test_global_launcher_runs_recorded_source_without_appdata(self):
        with tempfile.TemporaryDirectory(prefix='TPS launch ') as folder:
            profile = Path(folder)/'用户 空格'
            source = profile/'Documents/工具 目录'
            self.fake_app(source)
            path = self.configured_launcher(profile, source)
            env = dict(os.environ, LOCALAPPDATA=str(profile/'missing'))
            result = self.launch(path, 'list --model "sample model" --limit 1', env)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('CLI:list --model "sample model" --limit 1', result.stdout)

    def test_global_launcher_opens_recorded_desktop_without_appdata(self):
        with tempfile.TemporaryDirectory(prefix='TPS launch ') as folder:
            profile = Path(folder)
            source = profile/'Documents/tool'
            self.fake_app(source)
            path = self.configured_launcher(profile, source)
            result = self.launch(path, env=dict(os.environ, LOCALAPPDATA=str(profile/'missing')))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('DESKTOP', result.stdout)

    def test_global_launcher_reports_missing_recorded_source(self):
        with tempfile.TemporaryDirectory(prefix='TPS launch ') as folder:
            profile = Path(folder)
            source = profile/'Documents/moved-tool'
            path = self.configured_launcher(profile, source)
            result = self.launch(path, 'list', env=dict(os.environ, LOCALAPPDATA=str(profile/'missing')))
            self.assertEqual(result.returncode, 1)
            self.assertIn('Could not locate Codex TPS at:', result.stderr)
            self.assertIn(str(source), result.stderr)

    def test_portable_launcher_runs_next_to_app_with_bad_environment(self):
        with tempfile.TemporaryDirectory(prefix='TPS launch ') as folder:
            base = Path(folder)/'用户 空格'
            self.fake_app(base)
            path = base/'tpscode.cmd'
            path.write_bytes(LAUNCHER.read_bytes())
            env = dict(os.environ, LOCALAPPDATA=str(base/'missing'))
            result = self.launch(path, 'watch --count 1', env)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('CLI:watch --count 1', result.stdout)

    def test_global_launcher_uses_its_location_when_environment_is_wrong(self):
        with tempfile.TemporaryDirectory(prefix='TPS launch ') as folder:
            profile = Path(folder)/'用户 空格'
            base = profile/'.local/bin'
            base.mkdir(parents=True)
            path = base/'tpscode.cmd'
            path.write_bytes(LAUNCHER.read_bytes())
            self.fake_app(profile/'AppData/Local/CodexTPS/app')
            for mode in ('wrong', 'missing'):
                with self.subTest(environment=mode):
                    env = dict(os.environ, LOCALAPPDATA=str(profile/'missing'))
                    if mode == 'missing':
                        env.pop('LOCALAPPDATA', None)
                        env.pop('USERPROFILE', None)
                    result = self.launch(path, 'list --model "sample model"', env)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertIn('CLI:list --model "sample model"', result.stdout)

    def test_no_arguments_opens_desktop_in_portable_folder(self):
        with tempfile.TemporaryDirectory(prefix='TPS launch ') as folder:
            base = Path(folder)
            self.fake_app(base)
            path = base/'tpscode.cmd'
            path.write_bytes(LAUNCHER.read_bytes())
            result = self.launch(path, env=dict(os.environ, LOCALAPPDATA=str(base/'missing')))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('DESKTOP', result.stdout)

    def test_console_fallback_also_starts_all_profiles_capture(self):
        with tempfile.TemporaryDirectory(prefix='TPS launch ') as folder:
            base = Path(folder)
            bin_dir = base / 'bin'
            bin_dir.mkdir()
            (bin_dir / 'python.cmd').write_text('@echo off\necho PYTHON:%*\nexit /b 0\n', encoding='ascii')
            path = base / 'Start-Codex-TPS.cmd'
            path.write_bytes(LAUNCHER.with_name('Start-Codex-TPS.cmd').read_bytes())
            env = dict(os.environ, PATH=str(bin_dir) + ';' + str(Path(os.environ['SystemRoot']) / 'System32'))
            result = self.launch(path, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('profiles-audit', result.stdout)

    def test_missing_app_reports_the_paths_it_checked(self):
        with tempfile.TemporaryDirectory(prefix='TPS launch ') as folder:
            base = Path(folder)
            path = base/'tpscode.cmd'
            path.write_bytes(LAUNCHER.read_bytes())
            env = dict(os.environ, LOCALAPPDATA=str(base/'missing'))
            result = self.launch(path, 'watch', env)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Checked:', result.stdout)


if __name__ == '__main__':
    unittest.main()
