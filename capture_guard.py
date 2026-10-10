"""Restore a capture's configuration when its owning process exits unexpectedly."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return True  # An unknown owner must never be treated as a dead process.
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied is not proof of death.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def recover_stale_profiles(state_path: Path):
    if not state_path.is_file() or state_path.is_symlink():
        return []
    saved = json.loads(state_path.read_bytes())
    if not saved.get('active') or process_alive(saved.get('pid')):
        return []
    from profiles_capture import RESTORED_STATES, restore_profiles
    results = restore_profiles(state_path)
    if any(x['state'] not in RESTORED_STATES for x in results):
        raise ValueError('旧采集配置尚未完全恢复，请检查恢复记录。')
    return results


class CaptureGuard:
    """The pipe identifies this exact owner even if Windows reuses its PID."""
    def __init__(self, mode, resource: Path, token: str):
        self.mode, self.resource, self.token = mode, resource, token
        self.process = None

    def start(self):
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), self.mode, str(self.resource), self.token],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(self.process.stdout.readline()), daemon=True).start()
        try:
            if ready.get(timeout=5).strip() != b'ready' or self.process.poll() is not None:
                raise ValueError('无法启动异常退出恢复保护，连接配置未接入。')
        except queue.Empty:
            self.process.terminate()
            self.process.wait(timeout=5)
            raise ValueError('异常退出恢复保护启动超时，连接配置未接入。') from None
        finally:
            self.process.stdout.close()
        return self

    def finish(self):
        if self.process is None:
            return
        if self.process.stdin is not None:
            self.process.stdin.close()
            self.process.stdin = None
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # Let restoration finish; never terminate the recovery worker.


def _recover(mode, resource, token):
    if mode == 'profiles':
        from profiles_capture import RESTORED_STATES, restore_profiles
        if not resource.exists():
            return True
        state = json.loads(resource.read_bytes())
        if state.get('token') != token or not state.get('active'):
            return True
        return all(row['state'] in RESTORED_STATES for row in restore_profiles(resource))
    from official_desktop import HEADER_V2, restore_official_config
    marker = HEADER_V2.match((resource / 'config.toml').read_bytes())
    if marker and marker.group(1).decode() == token:
        return restore_official_config(resource)
    return True


def main():
    mode, resource, token = sys.argv[1:]
    if mode not in ('profiles', 'official') or len(token) != 32:
        return 1
    # Import the recovery implementation before reporting ready.
    if mode == 'profiles':
        import profiles_capture
    else:
        import official_desktop
    print('ready', flush=True)
    sys.stdin.buffer.read()  # EOF on a normal close, a forced exit, or a crash.
    for attempt in range(3):
        try:
            if _recover(mode, Path(resource), token):
                return 0
        except (OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(.25)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
