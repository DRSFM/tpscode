"""Reuse this tool's existing Windows capture window without changing its state."""
import json
import os
from pathlib import Path


def focus_profiles_window(state_path: Path, *, include_official=False) -> bool:
    if os.name != 'nt':
        return False
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('schema_version') != 1 or state.get('active') is not True:
            return False
        # Legacy collectors include official accounts. Never reuse a different scope silently.
        if state.get('include_official', True) is not include_official:
            return False
        pid = state.get('pid')
        if type(pid) is not int or pid <= 0:
            return False
    except (OSError, ValueError, AttributeError):
        return False

    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    found = []

    @callback_type
    def inspect(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            if title.value in ('Codex TPS · 全部 Profiles 审计', 'Codex TPS · API Profiles 审计',
                               'Codex TPS · API 与官方账号审计'):
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(inspect, 0)
    if not found:
        return False
    user32.ShowWindow(found[0], 9)  # SW_RESTORE
    user32.SetForegroundWindow(found[0])
    return True
