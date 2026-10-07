"""Discover Codex homes and temporarily capture every valid Responses provider.

Recovery stores only the original URL literal, never full configs or credentials.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import threading
import tomllib
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
import uuid

from audit_capture import create_capture_server
from official_desktop import OFFICIAL_UPSTREAM, _atomic_write, candidate_config_supported, has_chatgpt_login
from reasoning_audit import profile_from_home


MARKER = re.compile(r'\A# CODEX TPS PROFILES AUDIT ([a-f0-9]{32})\r?\n(?:# CODEX TPS STATE [^\r\n]*\r?\n)?')
LITERAL = r'(?:"(?:[^"\\\r\n]|\\.)*"|\x27[^\x27\r\n]*\x27)'


def validate_upstream(value):
    """Errors deliberately exclude the rejected value, including malformed keys."""
    try:
        if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
            raise ValueError
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or not 0 < (parsed.port if parsed.port is not None else 443) < 65536
                or re.search(r'(?i)(sk-[a-z0-9_-]{8,}|bearer|api[_-]?key|access[_-]?token)', unquote(parsed.netloc + parsed.path))):
            raise ValueError
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('连接地址无效或包含凭据信息；未显示地址原文。') from None
    return value


@dataclass
class Target:
    home: Path
    profile: str
    endpoint: str = ''
    server: object = None


def discover_profiles(user_home: Path):
    user_home = user_home.expanduser().resolve()
    homes = [user_home / '.codex', user_home / '.codex-api']
    for kind in ('accounts', 'profiles'):
        root = user_home / '.codex-api' / kind
        if root.is_dir() and not root.is_symlink():
            homes.extend(sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and p.resolve().parent == root.resolve()))
    targets = []
    for home in homes:
        path = home / 'config.toml'
        if home.is_symlink() or path.is_symlink() or not path.is_file():
            continue
        label = profile_from_home(home)
        if not label or re.search(r'(?i)sk-[a-z0-9_-]{8,}', label) or len(label) > 128:
            label = '未命名 Profile'
        targets.append(Target(home.resolve(), label))
    return targets


def _header_path(line):
    if not re.fullmatch(r'\s*\[(?!\[)[^\]\r\n]+\]\s*(?:#.*)?', line):
        return None
    try:
        data = tomllib.loads(line + '\n__tps_probe__ = true\n')
        keys = []
        while '__tps_probe__' not in data:
            key, data = next(iter(data.items()))
            keys.append(key)
        return keys
    except (ValueError, StopIteration, TypeError):
        return None


def _literal_location(text, key_path):
    section, offset, found = [], 0, []
    expression = re.compile(r'\s*' + re.escape(key_path[-1]) + r'\s*=\s*(' + LITERAL + r')\s*(?:#.*)?$')
    for line in text.splitlines(keepends=True):
        header = _header_path(line.rstrip('\r\n'))
        if header is not None:
            section = header
        elif section == key_path[:-1]:
            match = expression.fullmatch(line.rstrip('\r\n'))
            if match:
                found.append((offset + match.start(1), offset + match.end(1), match.group(1), offset, offset + len(line)))
        offset += len(line)
    if len(found) != 1:
        raise ValueError('连接配置写法无法安全定位；保留原配置。')
    return found[0]


def _plan(original, key_path, upstream, endpoint, token, state_path=None):
    bom = original.startswith(b'\xef\xbb\xbf')
    text = original.decode('utf-8-sig')
    data = tomllib.loads(text)
    expected = copy.deepcopy(data)
    node = expected
    for key in key_path[:-1]:
        node = node[key]
    inserted = key_path[-1] not in node
    literal = json.dumps(endpoint)
    old_literal = None
    if inserted:
        if key_path != ['openai_base_url']:
            raise ValueError('提供商未配置明确连接地址。')
        modified = f'openai_base_url = {literal}\n' + text
    else:
        start, end, old_literal, _, _ = _literal_location(text, key_path)
        if tomllib.loads('value=' + old_literal)['value'] != upstream:
            raise ValueError('连接字段与解析结果不一致；保留原配置。')
        modified = text[:start] + literal + text[end:]
    node[key_path[-1]] = endpoint
    prefix = f'# CODEX TPS PROFILES AUDIT {token}\n'
    if state_path is not None:
        prefix += '# CODEX TPS STATE ' + json.dumps(str(Path(state_path).resolve())) + '\n'
    _literal_location(modified, key_path)  # Recovery must be able to find this exact key.
    proposed = prefix + modified
    # A lexer match inside a multiline prompt or another key cannot change semantics.
    if tomllib.loads(proposed) != expected:
        raise ValueError('候选配置改变了其他字段；保留原配置。')
    entry = dict(key_path=key_path, old_literal=old_literal, inserted=inserted, endpoint=endpoint, upstream=upstream)
    return (b'\xef\xbb\xbf' if bom else b'') + proposed.encode('utf-8'), entry


def _restore_entry(entry, token):
    keys = entry['key_path']
    if keys != ['openai_base_url'] and not (len(keys) == 3 and keys[0] == 'model_providers' and keys[-1] == 'base_url'):
        raise ValueError('恢复记录包含其他配置字段。')
    validate_upstream(entry['endpoint'])
    if not entry['inserted']:
        if not re.fullmatch(LITERAL, entry['old_literal']):
            raise ValueError('恢复地址不是单个 TOML 字符串。')
        validate_upstream(tomllib.loads('value=' + entry['old_literal'])['value'])
    path = Path(entry['home']) / 'config.toml'
    if not path.is_file() or path.is_symlink():
        return '配置文件不存在或已替换'
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig')
    marker = MARKER.match(text)
    if not marker or marker.group(1) != token:
        return '标记已移除，未改配置'
    tail = text[marker.end():]
    try:
        start, end, literal, line_start, line_end = _literal_location(tail, entry['key_path'])
        current = tomllib.loads('value=' + literal)['value']
    except (ValueError, TypeError):
        return '配置格式已变化，需要手动恢复'
    state = '已恢复'
    if current == entry['endpoint']:
        if entry['inserted']:
            # Keep a comment added to our generated line, if any.
            suffix = tail[end:line_end]
            comment = suffix[suffix.find('#'):] if '#' in suffix else ''
            tail = tail[:line_start] + comment + tail[line_end:]
        else:
            tail = tail[:start] + entry['old_literal'] + tail[end:]
    else:
        state = '用户已修改地址'
    restored = (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + tail.encode('utf-8')
    if path.read_bytes() != raw:
        return '恢复期间配置发生变化，未覆盖'
    _atomic_write(path, restored)
    return state


def restore_profiles(state_path: Path):
    if not state_path.is_file() or state_path.is_symlink():
        return []
    state = json.loads(state_path.read_text(encoding='utf-8'))
    token = state.get('token', '')
    if state.get('schema_version') != 1 or not re.fullmatch('[a-f0-9]{32}', token):
        raise ValueError('恢复记录格式不受支持；配置未改。')
    if not state.get('active'):
        return state.get('restoration', [])
    result = []
    for entry in state.get('entries', []):
        try:
            status = _restore_entry(entry, token)
        except (OSError, ValueError, KeyError, UnicodeError):
            status = '恢复失败，需要检查配置'
        result.append(dict(profile=entry.get('profile', '未记录'), state=status))
    state['active'] = False
    state['restoration'] = result
    _atomic_write(state_path, json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8'))
    return result


class ProfilesCapture:
    def __init__(self, user_home: Path, state_dir: Path, *, official_port=8766, include_official=False):
        self.user_home = user_home.expanduser().resolve()
        self.state_dir = state_dir.expanduser().resolve()
        self.state_path = self.state_dir / 'profiles-state.json'
        self.audit_path = self.state_dir / 'profiles.jsonl'
        self.official_port = official_port
        self.include_official = include_official
        self.token = uuid.uuid4().hex
        self.active: list[Target] = []
        self.skipped = {}
        self.fingerprints = {}
        self.log_lock = threading.Lock()
        self.lock = threading.RLock()
        self.scan_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.watcher = None
        self.state = dict(schema_version=1, token=self.token, pid=os.getpid(), active=True, entries=[],
                          include_official=include_official, started_at=datetime.now(timezone.utc).isoformat())

    def _save(self):
        _atomic_write(self.state_path, json.dumps(self.state, ensure_ascii=False, indent=2).encode('utf-8'))

    def start(self, *, watch=False):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            previous = json.loads(self.state_path.read_text(encoding='utf-8'))
            if previous.get('active'):
                raise ValueError('已有统一采集记录；若原窗口已退出，请先运行 profiles-audit --restore。')
        self._save()
        try:
            self.scan()
            if watch:
                def observe():
                    while not self.stop_event.wait(3):
                        try:
                            saved = json.loads(self.state_path.read_text(encoding='utf-8'))
                            if saved.get('token') != self.token or not saved.get('active'):
                                self.stop_event.set()
                                break
                            self.scan()
                        except (OSError, ValueError):
                            with self.lock:
                                self.skipped['scan'] = dict(profile='目录扫描', state='未接入', reason='无法更新采集状态，请重新启动。')
                self.watcher = threading.Thread(target=observe, daemon=True)
                self.watcher.start()
        except BaseException:
            self.stop()
            raise
        return self

    def scan(self):
        with self.scan_lock:
            for target in discover_profiles(self.user_home):
                if self.stop_event.is_set():
                    return
                key = str(target.home)
                official_home = (target.home == self.user_home / '.codex' or
                                 target.home.parent == self.user_home / '.codex-api' / 'accounts')
                if official_home and not self.include_official:
                    with self.lock:
                        self.skipped[key] = dict(profile=target.profile, state='未启用',
                                                 reason='官方账号默认不采集；需要时使用 --include-official。')
                    continue
                with self.lock:
                    if any(x.home == target.home for x in self.active):
                        continue
                config = target.home / 'config.toml'
                reason = '配置无法读取或解析；未显示原文。'
                try:
                    if config.stat().st_size > 2 * 1024 * 1024:
                        raise ValueError('配置文件超过安全读取上限。')
                    original = config.read_bytes()
                    fingerprint = sha256(original).hexdigest()
                    if self.fingerprints.get(key) == fingerprint:
                        continue
                    self.fingerprints[key] = fingerprint
                    if b'CODEX TPS OFFICIAL AUDIT' in original[:220] or b'CODEX TPS PROFILES AUDIT' in original[:220]:
                        reason = '已有采集标记，请先停止对应旧采集窗口。'
                        raise ValueError('已有采集标记，请先停止对应旧采集窗口。')
                    try:
                        data = tomllib.loads(original.decode('utf-8-sig'))
                    except (ValueError, UnicodeError):
                        raise ValueError('配置格式不受支持；未显示原文。') from None
                    if data.get('forced_login_method') == 'chatgpt' and not self.include_official:
                        with self.lock:
                            self.skipped[key] = dict(profile=target.profile, state='未启用',
                                                     reason='官方账号默认不采集；需要时使用 --include-official。')
                        continue
                    if data.get('profile'):
                        raise ValueError('包含旧式 profile 选择，保留原配置。')
                    provider = data.get('model_provider', 'openai')
                    if not isinstance(provider, str) or not isinstance(data.get('model_providers', {}), dict):
                        raise ValueError('提供商结构无效。')
                    if provider == 'openai':
                        key_path = ['openai_base_url']
                        upstream = data.get('openai_base_url')
                        if upstream is None:
                            upstream = (OFFICIAL_UPSTREAM if data.get('forced_login_method') == 'chatgpt'
                                        or has_chatgpt_login(target.home) else 'https://api.openai.com/v1')
                    else:
                        info = data.get('model_providers', {}).get(provider, {})
                        if not isinstance(info, dict):
                            raise ValueError('提供商结构无效。')
                        if info.get('wire_api', 'responses') != 'responses':
                            raise ValueError('当前协议不是 Responses，未接入。')
                        key_path = ['model_providers', provider, 'base_url']
                        upstream = info.get('base_url')
                    reason = '地址无效或包含凭据信息；未显示地址原文。'
                    validate_upstream(upstream)
                    reason = '无法创建本机采集入口。'
                    server = create_capture_server(upstream, self.audit_path,
                                                   port=self.official_port if target.home == self.user_home / '.codex' else 0,
                                                   client='Auto', profile=target.profile, log_lock=self.log_lock)
                    threading.Thread(target=server.serve_forever, daemon=True).start()
                    target.endpoint = f'http://127.0.0.1:{server.server_port}/v1'
                    target.server = server
                    journaled = False
                    try:
                        reason = '连接配置无法安全定位，保留原配置。'
                        proposed, entry = _plan(original, key_path, upstream, target.endpoint, self.token, self.state_path)
                        reason = '实际客户端未通过候选配置检查，未接入。'
                        if not candidate_config_supported(proposed):
                            raise ValueError('实际客户端未通过候选配置检查，未接入。')
                        if config.read_bytes() != original:
                            reason = '检查期间用户配置发生变化，未覆盖。'
                            raise ValueError('检查期间用户配置发生变化，未覆盖。')
                        with self.lock:
                            if self.stop_event.is_set():
                                raise ValueError('采集正在停止。')
                            entry.update(home=key, profile=target.profile)
                            self.state['entries'].append(entry)
                            reason = '恢复记录或配置写入失败，已尝试撤销接入。'
                            self._save()  # Durable recovery must exist before config mutation.
                            journaled = True
                            _atomic_write(config, proposed)
                            self.active.append(target)
                            self.skipped.pop(key, None)
                    except BaseException:
                        try:
                            if journaled:
                                _restore_entry(entry, self.token)
                        finally:
                            server.shutdown()
                            server.server_close()
                        raise
                except (OSError, ValueError, KeyError, TypeError):
                    # All detailed reasons above are fixed messages; never echo parser
                    # exceptions, bad URL values, config content, or credentials.
                    with self.lock:
                        self.skipped[key] = dict(profile=target.profile, state='未接入', reason=reason)

    def status(self):
        with self.lock:
            rows = []
            for target in self.active:
                state = '采集中'
                try:
                    raw = (target.home / 'config.toml').read_bytes()
                    if self.token.encode() not in raw[:120]:
                        state = '配置已修改'
                    else:
                        data = tomllib.loads(raw.decode('utf-8-sig'))
                        entry = next(x for x in self.state['entries'] if x['home'] == str(target.home))
                        node = data
                        for key in entry['key_path']:
                            node = node[key]
                        if node != target.endpoint:
                            state = '配置已修改'
                except (OSError, ValueError, KeyError):
                    state = '配置已修改'
                rows.append(dict(profile=target.profile, state=state, reason='' if state == '采集中' else '未自动覆盖用户修改；请停止后重新接入。'))
            return rows + list(self.skipped.values())

    def stop(self):
        self.stop_event.set()
        if self.watcher and self.watcher is not threading.current_thread():
            self.watcher.join(35)
        with self.lock:
            try:
                if self.state_path.is_file():
                    existing = json.loads(self.state_path.read_text(encoding='utf-8'))
                    if existing.get('token') == self.token:
                        restore_profiles(self.state_path)
            finally:
                for target in self.active:
                    target.server.shutdown()
                    target.server.server_close()


def run_profiles_audit(user_home: Path, state_dir: Path, *, port=8766, restore=False, no_gui=False,
                       include_official=False):
    state_path = state_dir.expanduser().resolve() / 'profiles-state.json'
    if restore:
        results = restore_profiles(state_path)
        print('\n'.join(f'{x["profile"]}：{x["state"]}' for x in results) or '没有本工具的统一采集恢复记录。')
        return 0
    capture = ProfilesCapture(user_home, state_dir, official_port=port, include_official=include_official)
    try:
        capture.start(watch=True)
        scope = 'API 与官方账号' if include_official else 'API Profiles（官方账号未启用）'
        print(f'{scope}审计已启动；各客户端需要重启后加载采集入口。关闭窗口会恢复原连接。', flush=True)
        if no_gui:
            while not capture.stop_event.wait(1):
                if not json.loads(state_path.read_text(encoding='utf-8')).get('active'):
                    break
            return 0
        from codex_tps import Monitor, discover_homes, load_settings
        from desktop import run_gui
        legacy = state_dir / 'official-desktop.jsonl'
        paths = [capture.audit_path] + ([legacy] if legacy.exists() else [])
        settings = load_settings()
        extra = [Path(p).expanduser() for p in settings.get('extra_homes', [])]
        saved_audit = settings.get('audit_logs', [])
        if isinstance(saved_audit, list):
            paths += [Path(p).expanduser() for p in saved_audit if isinstance(p, str)]
        monitor = Monitor(discover_homes(user_home=capture.user_home, extra=extra), audit_paths=paths)
        monitor.audit_monitor.profile_labels[str(legacy.resolve())] = '官方'
        args = SimpleNamespace(view='audit', audit_status='all', archived=False, client='all', model='',
                               session='', profile='', days=7, smoke_report=None, screenshot=None, fixed_homes=False, user_home=capture.user_home,
                               profiles_audit=True, include_official=include_official,
                               profile_names=[x['profile'] for x in capture.status()], capture_status=capture.status)
        args.capture_stopped = capture.stop_event.is_set
        return run_gui(monitor, args)
    except KeyboardInterrupt:
        return 0
    finally:
        capture.stop()
