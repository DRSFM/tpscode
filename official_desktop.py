"""Temporary, reversible capture setup for the default official Desktop home."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import uuid

from audit_capture import create_capture_server


OFFICIAL_UPSTREAM = 'https://chatgpt.com/backend-api/codex'
HEADER = re.compile(
    rb'\A# CODEX TPS OFFICIAL AUDIT ([a-f0-9]{32}) bom=([01]) sha=([a-f0-9]{64})\n'
    rb'profile = "tps-official-audit-\1"\n# END CODEX TPS OFFICIAL AUDIT\n')
HEADER_V2 = re.compile(
    rb'\A# CODEX TPS OFFICIAL AUDIT V2 ([a-f0-9]{32}) bom=([01])\n'
    rb'openai_base_url = "http://127\.0\.0\.1:([0-9]{1,5})/v1"\n# END CODEX TPS OFFICIAL AUDIT\n')


def _atomic_write(path: Path, content: bytes):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.codex-tps-', delete=False) as stream:
        temp = Path(stream.name)
        stream.write(content)
    try:
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()  # Only the temporary file created above.


def has_chatgpt_login(home: Path) -> bool:
    executable = shutil.which('codex')
    if not executable:
        raise ValueError('没有找到已安装的 Codex 命令；不会下载或安装客户端。')
    env = os.environ.copy()
    env['CODEX_HOME'] = str(home)
    try:
        result = subprocess.run([executable, 'login', 'status'], env=env, capture_output=True,
                                timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired as exc:
        raise ValueError('官方登录状态检查超时；连接配置未修改。') from exc
    # The client reads its own credentials. Never print or persist its output.
    return result.returncode == 0 and b'logged in using chatgpt' in (result.stdout + result.stderr).lower()


def candidate_config_supported(content: bytes) -> bool:
    """Ask the installed client to load a candidate in an isolated test home."""
    executable = shutil.which('codex')
    if not executable:
        return False
    with tempfile.TemporaryDirectory(prefix='codex-tps-compat-') as folder:
        home = Path(folder)
        (home / 'config.toml').write_bytes(content)
        env = os.environ.copy()
        env['CODEX_HOME'] = folder
        try:
            result = subprocess.run([executable, 'features', 'list'], env=env, cwd=folder,
                                    capture_output=True, timeout=30,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0


def _remove_owned_profile(path: Path, digest: str):
    if (path.is_file() and not path.is_symlink() and path.resolve().parent == path.parent.resolve()
            and sha256(path.read_bytes()).hexdigest() == digest):
        path.unlink()  # A byte-for-byte verified Codex-generated intermediate file.


def restore_official_config(home: Path) -> bool:
    """Remove only our exact prefix, preserving user edits in the original tail."""
    path = home / 'config.toml'
    if not path.is_file() or path.is_symlink():
        return False
    current = path.read_bytes()
    marker = HEADER_V2.match(current) or HEADER.match(current)
    if not marker:
        return False
    token, bom, extra = (part.decode('ascii') for part in marker.groups())
    original = current[marker.end():]
    if bom == '1':
        original = b'\xef\xbb\xbf' + original
    _atomic_write(path, original)
    if HEADER.match(current):
        _remove_owned_profile(home / f'tps-official-audit-{token}.config.toml', extra)
    return True


class OfficialDesktopCapture:
    def __init__(self, home: Path, audit_path: Path, *, port=8766):
        self.home, self.audit_path, self.port = home.expanduser().resolve(), audit_path.resolve(), port
        self.server = self.thread = None
        self.token = ''

    def start(self):
        try:
            import tomllib
        except ImportError as exc:
            raise ValueError('官方桌面自动接入需要 Python 3.11+；其他监控功能仍支持 Python 3.10。') from exc
        config = self.home / 'config.toml'
        if not config.is_file() or config.is_symlink():
            raise ValueError('官方 Codex home 必须已有普通 config.toml 文件。')
        original = config.read_bytes()
        if HEADER_V2.match(original) or HEADER.match(original):
            raise ValueError('此目录已接入审计；若采集器已退出，请先运行 official-audit --restore。')
        data = tomllib.loads(original.decode('utf-8-sig'))
        if data.get('profile'):
            raise ValueError('此入口需要默认官方配置；当前已选择其他 profile，未修改该配置。')
        if data.get('model_provider', 'openai') != 'openai' or data.get('openai_base_url'):
            raise ValueError('此入口仅用于默认官方 OpenAI 连接；其他连接请使用 capture。')
        if not has_chatgpt_login(self.home):
            raise ValueError('此 Codex home 没有官方 ChatGPT 登录；请先在官方客户端登录。')
        self.server = create_capture_server(OFFICIAL_UPSTREAM, self.audit_path, port=self.port, client='Desktop', profile='官方')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.token = uuid.uuid4().hex
        base = f'http://127.0.0.1:{self.server.server_port}/v1'
        bom = original.startswith(b'\xef\xbb\xbf')
        prefix = (f'# CODEX TPS OFFICIAL AUDIT V2 {self.token} bom={int(bom)}\n'
                  f'openai_base_url = {json.dumps(base)}\n# END CODEX TPS OFFICIAL AUDIT\n').encode()
        proposed = prefix + (original[3:] if bom else original)
        tomllib.loads(proposed.decode('utf-8'))
        try:
            if not candidate_config_supported(proposed):
                raise ValueError('当前客户端未通过候选配置的兼容性检查；官方配置未修改。')
            if config.read_bytes() != original:
                raise ValueError('检查期间官方配置发生变化，已停止接入并保留用户修改。')
            _atomic_write(config, proposed)
        except BaseException:
            self.stop()
            raise
        return self

    def stop(self):
        try:
            if self.token:
                current = self.home / 'config.toml'
                # Restore only the prefix belonging to this running capture.
                if current.is_file() and not current.is_symlink():
                    marker = HEADER_V2.match(current.read_bytes())
                    if marker and marker.group(1).decode() == self.token:
                        restore_official_config(self.home)
        finally:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
                self.server = None


def run_official_audit(home: Path, audit_path: Path, port: int, *, restore=False, no_gui=False) -> int:
    if restore:
        print('官方配置已恢复；请重启官方桌面。' if restore_official_config(home.expanduser().resolve())
              else '没有找到本工具写入的临时接入标记；配置未修改。')
        return 0
    capture = OfficialDesktopCapture(home, audit_path, port=port)
    try:
        capture.start()
        print(f'官方桌面审计已就绪：{capture.home}\n'
              f'日志：{capture.audit_path}\n请重启官方账号的桌面客户端，再发送测试消息。\n'
              'WebSocket 与 HTTP/SSE 均已接入。\n'
              '点击“停止并恢复配置”、关闭本窗口或 Ctrl+C 后恢复配置，之后请再次重启官方桌面。', flush=True)
        if no_gui:
            while HEADER_V2.match((capture.home / 'config.toml').read_bytes()):
                threading.Event().wait(1)
            return 0
        from codex_tps import Monitor
        from desktop import run_gui
        args = SimpleNamespace(view='audit', audit_status='all', archived=False, client='all', model='',
                               session='', days=7, smoke_report=None, screenshot=None, fixed_homes=True,
                               official_audit=True)
        monitor = Monitor([], audit_paths=[capture.audit_path])
        monitor.audit_monitor.profile_labels[str(capture.audit_path.resolve())] = '官方'
        return run_gui(monitor, args)
    except KeyboardInterrupt:
        return 0
    finally:
        capture.stop()
