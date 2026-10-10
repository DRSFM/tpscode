"""Keep API forwarding independent of the statistics window."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
import tomllib

from capture_guard import process_alive, recover_stale_profiles
from capture_lock import CaptureLock

_WORKERS = {}  # Keep detached child handles until they exit; the viewer does not own their lifetime.


class ServiceStopped:
    def __init__(self, state_path):
        self.state_path = state_path

    def is_set(self):
        try:
            state = json.loads(self.state_path.read_bytes())
            return not state.get('active') or not process_alive(state.get('pid'))
        except (OSError, ValueError):
            return True


class ProfilesService:
    def __init__(self, user_home, state_dir):
        self.user_home, self.state_dir = user_home.expanduser().resolve(), state_dir.expanduser().resolve()
        self.state_path = self.state_dir / 'profiles-state.json'
        self.audit_path = self.state_dir / 'profiles.jsonl'
        self.stop_event = ServiceStopped(self.state_path)

    def status(self):
        state = json.loads(self.state_path.read_bytes())
        rows = []
        for entry in state.get('entries', []):
            status = '配置已修改'
            try:
                text = (Path(entry['home']) / 'config.toml').read_text(encoding='utf-8-sig')
                node = tomllib.loads(text)
                for key in entry['key_path']:
                    node = node[key]
                if state['token'] in text[:120] and node == entry['endpoint']:
                    status = '采集中'
            except (OSError, ValueError, KeyError):
                pass
            rows.append(dict(profile=entry['profile'], state=status, reason=''))
        labels = {row['profile'] for row in rows}
        return rows + [row for row in state.get('status', []) if row['profile'] not in labels]


def start_profiles_service(user_home: Path, state_dir: Path, *, port=8766):
    with CaptureLock(state_dir.expanduser().resolve() / '.profiles-service.lock', timeout=45):
        return _start_service(user_home, state_dir, port=port)


def _start_service(user_home: Path, state_dir: Path, *, port):
    for pid, worker in list(_WORKERS.items()):
        if worker.poll() is not None:
            _WORKERS.pop(pid)
    service = ProfilesService(user_home, state_dir)
    recover_stale_profiles(service.state_path)
    if service.state_path.exists():
        saved = json.loads(service.state_path.read_bytes())
        if saved.get('active'):
            if saved.get('scope') == 'api' and saved.get('ready') and process_alive(saved.get('pid')):
                return service
            raise ValueError('已有其他采集正在运行，请先停止并恢复旧采集。')
        # A restored worker may still be releasing its sockets and owner lock.
        with CaptureLock(service.state_dir / '.profiles-capture.lock', timeout=35):
            pass
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve().with_name('codex_tps.py')), 'profiles-audit',
         '--user-home', str(service.user_home), '--state-dir', str(service.state_dir),
         '--port', str(port), '--no-gui'], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    _WORKERS[process.pid] = process
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError('API 采集服务启动失败，已尝试恢复连接配置。')
        try:
            state = json.loads(service.state_path.read_bytes())
            if state.get('pid') == process.pid and state.get('active') and state.get('ready'):
                return service
        except (OSError, ValueError):
            pass
        time.sleep(.1)
    # Only this helper's own worker is stopped; its independent guard restores URLs.
    process.terminate()
    process.wait(timeout=5)
    raise ValueError('API 采集服务启动超时，已触发异常退出恢复。')
