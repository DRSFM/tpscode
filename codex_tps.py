"""Local, read-only Codex Desktop/CLI effective output TPS monitor.

Only the Python standard library is required. Conversation text and credentials
are never stored in the monitor state or exports. Rollout logs are internal to
Codex; missing timing produces an unavailable TPS rather than a guessed value.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any

from reasoning_audit import (AUDIT_FILTERS, AuditMonitor, build_audit_rows, export_audit,
                             profile_from_home, select_audit, summarize_audit)

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / 'settings.json'
DISPLAY_TZ = timezone(timedelta(hours=8), 'Asia/Hong_Kong')
TOKEN_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens')


def timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


def token_number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def fingerprint(usage: Any) -> tuple | None:
    if not isinstance(usage, dict) or token_number(usage.get('output_tokens')) is None:
        return None
    return tuple(token_number(usage.get(k)) for k in TOKEN_FIELDS)


def client_name(meta: dict) -> str:
    origin = str(meta.get('originator', '')).lower()
    source = meta.get('source', '')
    if isinstance(source, dict):
        return 'Subagent'
    if 'desktop' in origin:
        return 'Desktop'
    if any(word in origin for word in ('cli', 'tui', 'exec')) or source in ('cli', 'exec'):
        return 'CLI'
    if source == 'vscode':
        return 'IDE / Desktop'
    return 'Other'


@dataclass(slots=True)
class Sample:
    uid: str
    session_id: str
    response_id: str
    turn_id: str
    completed_at: str
    client: str
    model: str
    effort: str
    provider: str
    home: str
    log_path: str
    output_tokens: int
    reasoning_tokens: int | None
    visible_tokens: int | None
    input_tokens: int | None
    duration_seconds: float | None
    effective_tps: float | None
    visible_tps: float | None
    timing_note: str
    previous_effort: str = ''
    previous_model: str = ''

    @property
    def end_time(self) -> datetime:
        return datetime.fromisoformat(self.completed_at)


class LogParser:
    def __init__(self, path: Path, home: str):
        self.path = path
        self.home = home
        self.session_id = path.stem
        self.client = 'Other'
        self.model = '未记录'
        self.effort = '—'
        self.previous_effort = ''
        self.previous_model = ''
        self.context_turn_id = ''
        self.provider = '未记录'
        self.turn_id = ''
        self.start: datetime | None = None
        self.model_end: datetime | None = None
        self.next_input: datetime | None = None
        self.pending_tools: set[str] = set()
        self.last_total: dict | None = None
        self.last_fingerprint: tuple | None = None
        self.response_ids: set[str] = set()
        self.records: list[Sample] = []
        self.warnings = 0

    def feed(self, obj: Any) -> None:
        if not isinstance(obj, dict):
            self.warnings += 1
            return
        kind = obj.get('type')
        p = obj.get('payload')
        if not isinstance(p, dict):
            return
        t = timestamp(obj.get('timestamp'))
        if kind == 'session_meta':
            self.session_id = str(p.get('id') or p.get('session_id') or self.session_id)
            self.client = client_name(p)
            self.provider = str(p.get('model_provider') or '未记录')
        elif kind == 'turn_context':
            model = str(p.get('model') or self.model)
            effort = str(p.get('effort') or p.get('reasoning_effort') or '—')
            context_turn = str(p.get('turn_id') or self.turn_id)
            if (context_turn != self.context_turn_id or
                    model != self.model or effort != self.effort):
                self.previous_effort = self.effort if self.effort != '—' and model == self.model else ''
                self.previous_model = self.model if self.model != '未记录' else ''
            self.model, self.effort = model, effort
            self.context_turn_id = context_turn
            self.turn_id = str(p.get('turn_id') or self.turn_id)
        elif kind == 'response_item' and t:
            self._item(p, t)
        elif kind == 'token_usage_record' and t:
            rid = str(p.get('response_id') or '')
            if rid and rid in self.response_ids:
                return
            tokens = p.get('usage')
            if not isinstance(tokens, dict) or token_number(tokens.get('output_tokens')) is None:
                self.warnings += 1
                return
            self._emit(tokens, t, rid, str(p.get('turn_id') or self.turn_id), modern=True,
                       total=p.get('thread_token_usage'))
            if rid:
                self.response_ids.add(rid)
        elif kind == 'event_msg':
            event = p.get('type')
            if event == 'task_started' and t:
                self.start = t
                self.model_end = self.next_input = None
                self.pending_tools.clear()
                self.turn_id = str(p.get('turn_id') or self.turn_id)
            elif event in ('task_complete', 'task_completed', 'turn_aborted', 'task_aborted'):
                self.start = self.model_end = self.next_input = None
                self.pending_tools.clear()
            elif event == 'user_message' and t and self.model_end is None:
                self.start = t
            elif event == 'token_count' and t:
                self._legacy(p.get('info'), t)
        elif kind == 'compacted':
            # Compaction can replace the cumulative counter. Do not divide a
            # resumed response by the time spent on imported historical items.
            self.start = self.model_end = self.next_input = None
            self.pending_tools.clear()

    def _item(self, p: dict, t: datetime) -> None:
        typ = p.get('type')
        if typ == 'message' and p.get('role') == 'user':
            if self.model_end is None and self.start is None:
                self.start = t
        elif typ in ('function_call_output', 'custom_tool_call_output', 'tool_result'):
            call_id = str(p.get('call_id') or p.get('id') or '')
            self.pending_tools.discard(call_id)
            self.next_input = t if self.next_input is None else max(self.next_input, t)
            if self.model_end is None:
                self.start = self.next_input if not self.pending_tools else None
        elif (typ == 'message' and p.get('role') == 'assistant') or typ in (
                'reasoning', 'function_call', 'custom_tool_call', 'web_search_call',
                'local_shell_call', 'computer_call', 'image_generation_call'):
            if self.start is None and self.next_input is not None and not self.pending_tools:
                self.start = self.next_input
            self.model_end = t
            if typ in ('function_call', 'custom_tool_call', 'local_shell_call'):
                self.pending_tools.add(str(p.get('call_id') or p.get('id') or 'unknown-tool'))

    def _legacy(self, info: Any, t: datetime) -> None:
        if not isinstance(info, dict):
            return  # A quota-only update, without token usage.
        total = info.get('total_token_usage')
        fp = fingerprint(total)
        if fp is not None and fp == self.last_fingerprint:
            return  # Mirrors a modern usage record, or repeats a quota update.
        tokens = info.get('last_token_usage')
        if not isinstance(tokens, dict) or token_number(tokens.get('output_tokens')) is None:
            if fp is None:
                return
            if self.last_total is None:
                # A cumulative first observation is only a per-response count
                # when there is an observed active response in this rollout.
                if self.start is None or self.model_end is None:
                    self.last_total, self.last_fingerprint = dict(total), fp
                    return
                tokens = total
            else:
                tokens = {}
                for key in TOKEN_FIELDS:
                    now, prev = token_number(total.get(key)), token_number(self.last_total.get(key))
                    if now is not None and prev is not None and now >= prev:
                        tokens[key] = now - prev
                if token_number(tokens.get('output_tokens')) is None:
                    self.last_total, self.last_fingerprint = dict(total), fp
                    self.start = self.model_end = None
                    self.warnings += 1
                    return
        # Old token_count events can follow tool completion. The response_item
        # boundary supplies the model end, so tool latency does not enter TPS.
        if self.model_end is None:
            if fp:
                self.last_total, self.last_fingerprint = dict(total), fp
            return
        self._emit(tokens, t, '', self.turn_id, modern=False, total=total)

    def _emit(self, tokens: dict, t: datetime, rid: str, turn_id: str, *, modern: bool, total: Any) -> None:
        output = token_number(tokens.get('output_tokens'))
        if output is None:
            self.warnings += 1
            return
        reasoning = token_number(tokens.get('reasoning_output_tokens'))
        if reasoning is not None and reasoning > output:
            reasoning = None
            self.warnings += 1
        visible = output - reasoning if reasoning is not None else None
        end = self.model_end if self.model_end is not None else t
        seconds = (end - self.start).total_seconds() if self.start else None
        if seconds is not None and (seconds <= 0 or end > t):
            seconds = None
        note = '按日志边界推算；包含首字等待，排除已记录的工具执行'
        if seconds is None:
            note = '缺少有效响应时间边界，TPS 不可用'
        raw_key = rid or '|'.join((self.session_id, turn_id, str(fingerprint(total)), t.isoformat()))
        uid = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:24]
        self.records.append(Sample(
            uid=uid, session_id=self.session_id, response_id=rid, turn_id=turn_id,
            completed_at=t.isoformat(), client=self.client, model=self.model, effort=self.effort,
            provider=self.provider, home=self.home, log_path=str(self.path), output_tokens=output,
            reasoning_tokens=reasoning, visible_tokens=visible, input_tokens=token_number(tokens.get('input_tokens')),
            duration_seconds=seconds, effective_tps=output / seconds if seconds else None,
            visible_tps=visible / seconds if visible is not None and seconds else None, timing_note=note,
            previous_effort=self.previous_effort, previous_model=self.previous_model))
        fp = fingerprint(total)
        if fp:
            self.last_total, self.last_fingerprint = dict(total), fp
        # After legacy usage, a tool may already have finished. After modern
        # usage, we wait for the outstanding tool results before starting again.
        if self.pending_tools:
            self.start = None
        elif self.next_input is not None and self.next_input >= end:
            self.start = self.next_input
        else:
            self.start = t
        self.model_end = self.next_input = None


def load_settings() -> dict:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            return {}
        value['extra_homes'] = [p for p in value.get('extra_homes', []) if isinstance(p, str)] if isinstance(value.get('extra_homes', []), list) else []
        return value
    except (OSError, ValueError):
        return {}


def discover_homes(user_home: Path | None = None, extra: list[Path] | None = None) -> list[Path]:
    base = user_home or Path.home()
    candidates = [base / '.codex', base / '.codex-api']
    if os.environ.get('CODEX_HOME'):
        candidates.append(Path(os.environ['CODEX_HOME']).expanduser())
    for group in ('accounts', 'profiles'):
        parent = base / '.codex-api' / group
        try:
            candidates.extend(p for p in parent.iterdir() if p.is_dir())
        except OSError:
            pass
    candidates.extend(extra or [])
    unique: dict[str, Path] = {}
    for path in candidates:
        path = path.expanduser().resolve()
        unique.setdefault(os.path.normcase(str(path)), path)
    return list(unique.values())


@dataclass
class FileState:
    parser: LogParser
    position: int = 0
    identity: tuple = ()
    prefix: bytes = b''
    bad_lines: int = 0


class Monitor:
    def __init__(self, homes: list[Path], include_archived: bool = False, audit_paths: list[Path] | None = None):
        self.homes = homes
        self.include_archived = include_archived
        self.files: dict[str, FileState] = {}
        self.errors: list[str] = []
        self.bad_lines = 0
        self.file_count = 0
        self.audit_monitor = AuditMonitor(audit_paths)
        self.audit_rows = []

    def _paths(self, since: datetime | None):
        seen = set()
        for home in self.homes:
            if home.is_file() and home.suffix.lower() == '.jsonl':
                bases = [home]
            elif home.name in ('sessions', 'archived_sessions'):
                bases = [home]
            else:
                bases = [home / 'sessions']
                if self.include_archived:
                    bases.append(home / 'archived_sessions')
            for base in bases:
                if not base.exists():
                    continue
                paths = (base,) if base.is_file() else base.rglob('*.jsonl')
                for path in paths:
                    try:
                        path = path.resolve()
                        key = os.path.normcase(str(path))
                        if key in seen:
                            continue
                        seen.add(key)
                        stat = path.stat()
                        if since and stat.st_mtime < since.timestamp():
                            continue
                        yield key, path, stat, str(home)
                    except OSError as exc:
                        self.errors.append(f'{path}: {exc.strerror or type(exc).__name__}')

    def refresh(self, since: datetime | None = None) -> list[Sample]:
        self.errors = []
        present = set()
        for key, path, stat, home in self._paths(since):
            present.add(key)
            state = self.files.get(key)
            try:
                with path.open('rb') as stream:
                    prefix = stream.read(min(128, stat.st_size))
                    identity = (stat.st_dev, stat.st_ino)
                    if state is None or stat.st_size < state.position or state.identity != identity or (
                            state.prefix and not prefix.startswith(state.prefix)):
                        state = FileState(LogParser(path, home), identity=identity, prefix=prefix)
                        self.files[key] = state
                    stream.seek(state.position)
                    while True:
                        pos = stream.tell()
                        line = stream.readline()
                        if not line or not line.endswith(b'\n'):
                            # The writer may still be completing this line.
                            state.position = pos
                            break
                        state.position = stream.tell()
                        try:
                            state.parser.feed(json.loads(line))
                        except (ValueError, UnicodeError):
                            state.bad_lines += 1
            except OSError as exc:
                self.errors.append(f'{path}: {exc.strerror or type(exc).__name__}')
        for key in list(self.files):
            if key not in present:
                del self.files[key]
        self.file_count = len(present)
        self.bad_lines = sum(s.bad_lines + s.parser.warnings for s in self.files.values())
        unique: dict[str, Sample] = {}
        for state in self.files.values():
            for sample in state.parser.records:
                if since is None or sample.end_time >= since:
                    unique.setdefault(sample.uid, sample)
        samples = sorted(unique.values(), key=lambda s: (s.completed_at, s.uid), reverse=True)
        self.audit_rows = build_audit_rows(samples, self.audit_monitor.refresh(since))
        self.errors.extend(self.audit_monitor.errors)
        self.bad_lines += self.audit_monitor.bad_lines
        return samples


def select_samples(samples: list[Sample], client: str = 'all', model: str = '', session: str = '',
                   home: str = '') -> list[Sample]:
    return [s for s in samples if
            (client == 'all' or s.client.lower() == client.lower() or
             (client == 'other' and s.client not in ('Desktop', 'CLI'))) and
            model.lower() in s.model.lower() and session.lower() in s.session_id.lower() and
            (not home or s.home == home)]


def summarize(samples: list[Sample]) -> dict:
    timed = [s for s in samples if s.effective_tps is not None and s.duration_seconds]
    latest = max(samples, key=lambda s: s.completed_at) if samples else None
    seconds = sum(s.duration_seconds for s in timed)
    return {
        'sample_count': len(samples), 'timed_count': len(timed),
        'session_count': len({s.session_id for s in samples}),
        'output_tokens': sum(s.output_tokens for s in samples),
        'weighted_tps': sum(s.output_tokens for s in timed) / seconds if seconds else None,
        'median_tps': statistics.median(s.effective_tps for s in timed) if timed else None,
        'latest_tps': latest.effective_tps if latest else None,
        'latest_model': latest.model if latest else None,
        'latest_at': latest.completed_at if latest else None,
    }


def cutoff(days: float) -> datetime | None:
    return datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None


def export_samples(samples: list[Sample], path: Path, fmt: str, *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError('输出文件已存在；请换一个文件名，或明确使用 --overwrite。')
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [asdict(s) for s in samples]
    if fmt == 'json':
        with path.open('w' if overwrite else 'x', encoding='utf-8') as stream:
            json.dump({'metric': 'effective_output_tps', 'summary': summarize(samples), 'samples': records},
                      stream, ensure_ascii=False, indent=2, allow_nan=False)
    else:
        with path.open('w' if overwrite else 'x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(Sample.__dataclass_fields__))
            writer.writeheader()
            writer.writerows(records)


def local_time(value: str, full: bool = False) -> str:
    dt = timestamp(value)
    return dt.astimezone(DISPLAY_TZ).strftime('%Y-%m-%d %H:%M:%S' if full else '%m-%d %H:%M:%S') if dt else '—'


def number(value: float | int | None, digits: int = 1) -> str:
    return '—' if value is None else f'{value:,.{digits}f}'


def print_table(samples: list[Sample], limit: int) -> None:
    from unicodedata import east_asian_width

    def pad(value, width):
        text, size = '', 0
        for char in str(value):
            weight = 2 if east_asian_width(char) in 'WF' else 1
            if size + weight > width:
                break
            text += char
            size += weight
        return text + ' ' * (width - size)

    columns = [('完成时间 (UTC+8)', 17), ('客户端', 9), ('模型', 28), ('模式', 8),
               ('TPS', 9), ('输出', 9), ('思考', 9), ('耗时(s)', 10), ('会话', 12)]
    print('  '.join(pad(v, n) for v, n in columns))
    print('─' * 127)
    for s in samples[:limit] if limit else samples:
        values = [local_time(s.completed_at), s.client, s.model, s.effort, number(s.effective_tps),
                  str(s.output_tokens), str(s.reasoning_tokens) if s.reasoning_tokens is not None else '—',
                  number(s.duration_seconds), s.session_id[:12]]
        print('  '.join(pad(v, n) for v, (_, n) in zip(values, columns)))


def positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('必须是大于零的有限数值')
    return result


def nonnegative_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError('必须是大于等于零的有限数值')
    return result


def nonnegative_int(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError('必须是大于等于零的整数')
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Codex Desktop / CLI 本地有效 TPS 监控，无需 API Key。')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--home', action='append', default=[], help='额外 Codex home 或 sessions 目录，可重复')
    common.add_argument('--client', choices=('all', 'desktop', 'cli', 'other'), default='all')
    common.add_argument('--model', default='', help='按模型名筛选（部分匹配）')
    common.add_argument('--session', default='', help='按会话 ID 筛选（部分匹配）')
    common.add_argument('--days', type=nonnegative_float, default=7, help='最近天数，0 表示全部；默认 7')
    common.add_argument('--archived', action='store_true', help='包含 archived_sessions')
    common.add_argument('--audit-log', action='append', default=[], help='审计 JSONL 文件或目录，可重复')
    common.add_argument('--audit-status', choices=tuple(AUDIT_FILTERS.values()), default='all', help='筛选审计结果')
    common.add_argument('--profile', default='', help='按完整 Profile 名称筛选审计或速度记录')
    sub = parser.add_subparsers(dest='command')
    gui = sub.add_parser('gui', parents=[common], help='打开原生桌面窗口（默认）')
    gui.add_argument('--smoke-report', type=Path, help=argparse.SUPPRESS)
    gui.add_argument('--screenshot', type=Path, help=argparse.SUPPRESS)
    gui.add_argument('--view', choices=('speed', 'audit'), default='speed', help='桌面初始视图')
    auditing = sub.add_parser('audit', parents=[common], help='查看思考等级审计与配置变化')
    auditing.add_argument('--limit', type=nonnegative_int, default=25)
    auditing.add_argument('--json', action='store_true')
    capture = sub.add_parser('capture', help='手动启动仅监听本机的 HTTP/SSE/WebSocket 审计采集入口')
    capture.add_argument('--upstream', required=True, help='实际提供商 API base URL，例如 https://provider.example/v1')
    capture.add_argument('--audit-log', type=Path, required=True, help='写入脱敏审计 JSONL 文件')
    capture.add_argument('--port', type=nonnegative_int, default=8766)
    capture.add_argument('--client', choices=('desktop', 'cli', 'other'), default='other', help='手动标注来源客户端')
    capture.add_argument('--timeout', type=positive_float, default=1800, help='上游读取超时 / 秒')
    capture.add_argument('--profile-name', default='', help='手动采集入口的 Profile 标签')
    official = sub.add_parser('official-audit', help='临时接入默认官方账号桌面的真实请求，关闭后恢复配置')
    official.add_argument('--codex-home', type=Path, default=Path.home() / '.codex', help='官方登录目录，默认 ~/.codex')
    official.add_argument('--audit-log', type=Path, default=APP_DIR / 'audits' / 'official-desktop.jsonl')
    official.add_argument('--port', type=nonnegative_int, default=8766)
    official.add_argument('--restore', action='store_true', help='恢复本工具写入的临时配置，用于异常退出后恢复')
    official.add_argument('--no-gui', action='store_true', help='仅启动采集服务；Ctrl+C 恢复配置')
    profiles = sub.add_parser('profiles-audit', help='默认采集 API Profiles；可显式包含官方账号，关闭后恢复配置')
    profiles.add_argument('--include-official', action='store_true', help='本次同时采集默认官方及具名订阅账号；默认关闭')
    profiles.add_argument('--user-home', type=Path, default=Path.home(), help='发现 .codex / .codex-api 的用户目录')
    profiles.add_argument('--state-dir', type=Path, default=APP_DIR / 'audits', help='脱敏日志与 URL 恢复记录目录')
    profiles.add_argument('--port', type=nonnegative_int, default=8766, help='默认官方入口端口；其他入口自动分配')
    profiles.add_argument('--restore', action='store_true', help='异常退出后恢复所有本工具接入的配置')
    profiles.add_argument('--no-gui', action='store_true')
    listing = sub.add_parser('list', parents=[common], help='查看最近的模型响应')
    listing.add_argument('--limit', type=nonnegative_int, default=25, help='显示条数，0 为全部')
    listing.add_argument('--json', action='store_true', help='输出 JSON')
    watch = sub.add_parser('watch', parents=[common], help='持续监控新响应；Ctrl+C 退出')
    watch.add_argument('--interval', type=positive_float, default=2)
    watch.add_argument('--count', type=nonnegative_int, default=0, help='轮询次数，0 表示持续运行')
    watch.add_argument('--json-lines', action='store_true', help='每个新响应输出一行 JSON')
    export = sub.add_parser('export', parents=[common], help='导出全部筛选结果')
    export.add_argument('--format', choices=('json', 'csv'), default='csv')
    export.add_argument('--output', type=Path, required=True)
    export.add_argument('--overwrite', action='store_true')
    export.add_argument('--view', choices=('speed', 'audit'), default='speed', help='导出速度统计或审计记录')
    sub.add_parser('diagnose', parents=[common], help='检查会话来源和格式识别情况')
    requested = argv if argv is not None else sys.argv[1:]
    args = parser.parse_args(requested or ['gui'])
    if args.command == 'profiles-audit':
        from profiles_capture import run_profiles_audit
        try:
            return run_profiles_audit(args.user_home, args.state_dir, port=args.port, restore=args.restore,
                                      no_gui=args.no_gui, include_official=args.include_official)
        except (OSError, ValueError, OverflowError):
            print('统一采集无法启动：请检查采集状态或先运行 profiles-audit --restore；未输出配置原文。', file=sys.stderr)
            return 1
    if args.command == 'official-audit':
        from official_desktop import run_official_audit
        try:
            return run_official_audit(args.codex_home, args.audit_log, args.port,
                                      restore=args.restore, no_gui=args.no_gui)
        except (OSError, ValueError, OverflowError) as exc:
            print(f'官方桌面审计无法启动：{exc}', file=sys.stderr)
            return 1
    if args.command == 'capture':
        from audit_capture import run_capture
        try:
            return run_capture(args.upstream, args.audit_log, args.port,
                               {'desktop':'Desktop', 'cli':'CLI', 'other':'Other'}[args.client], args.timeout, args.profile_name)
        except (OSError, ValueError, OverflowError) as exc:
            print(f'采集入口无法启动：{exc}', file=sys.stderr)
            return 1
    settings = load_settings()
    extra = [Path(p) for p in args.home + settings.get('extra_homes', []) if isinstance(p, str)]
    homes = discover_homes(extra=extra)
    saved_audit = settings.get('audit_logs', [])
    saved_audit = saved_audit if isinstance(saved_audit, list) else []
    audit_paths = [Path(p).expanduser() for p in args.audit_log + saved_audit if isinstance(p, str)]
    monitor = Monitor(homes, args.archived, audit_paths)
    if args.command == 'gui':
        from desktop import run_gui
        return run_gui(monitor, args)
    seen: set[str] = set()
    iteration = 0
    try:
        while True:
            if args.command == 'watch':
                monitor.homes = discover_homes(extra=homes)
            samples = select_samples(monitor.refresh(cutoff(args.days)), args.client, args.model, args.session)
            if args.profile:
                samples = [s for s in samples if (profile_from_home(s.home) or '未记录') == args.profile]
            summary = summarize(samples)
            audit_rows = select_audit(monitor.audit_rows, args.client, args.model, args.session, status=args.audit_status, profile=args.profile)
            if args.command == 'audit':
                rows = audit_rows[:args.limit] if args.limit else audit_rows
                if args.json:
                    print(json.dumps(dict(schema_version=1, metric='reasoning_effort_audit',
                                          summary=summarize_audit(audit_rows), records=[r.to_dict() for r in rows],
                                          warnings=monitor.errors, bad_records=monitor.bad_lines),
                                     ensure_ascii=False, allow_nan=False))
                else:
                    print('Codex TPS · 思考等级审计（回显差异与配置变化）\n')
                    for r in rows:
                        print(f'{local_time(r.completed_at)}  {r.client:7}  [{r.profile or "未记录"}]  {r.model:25}  '
                              f'出站 {r.outbound_effort or "未采集"}  首包 {r.first_display}  '
                              f'最终 {r.final_effort or "未返回"}  思考 {number(r.reasoning_tokens, 0)}  {r.audit_result}')
                    count = summarize_audit(audit_rows)
                    print(f'\n{len(audit_rows)} 条记录 / {count["comparable_count"]} 条可比 / '
                          f'{count["lowered_count"]} 条回显降低 / {count["config_lowered_count"]} 条配置降低')
                break
            if args.command == 'list':
                if args.json:
                    rows = samples[:args.limit] if args.limit else samples
                    print(json.dumps({'metric': 'effective_output_tps', 'summary': summary,
                                      'samples': [asdict(s) for s in rows], 'warnings': monitor.errors,
                                      'bad_records': monitor.bad_lines}, ensure_ascii=False, allow_nan=False))
                else:
                    print('Codex TPS  ·  有效输出速度（包含思考与首字等待）\n')
                    print_table(samples, args.limit)
                    print(f'\n{len(samples)} 次响应 / {summary["session_count"]} 个会话  ·  '
                          f'加权平均 {number(summary["weighted_tps"])} tokens/s')
                    if not samples:
                        print('没有匹配的响应。可尝试 --days 0 或 --home 你的Codex目录。')
                break
            if args.command == 'export':
                if args.view == 'audit':
                    export_audit(audit_rows, args.output, args.format, overwrite=args.overwrite)
                else:
                    export_samples(samples, args.output, args.format, overwrite=args.overwrite)
                print(f'已导出 {len(audit_rows) if args.view == "audit" else len(samples)} 条 → {args.output.resolve()}')
                break
            if args.command == 'diagnose':
                print(json.dumps({'homes': [str(p) for p in homes], 'scanned_files': monitor.file_count,
                                  'summary': summary, 'clients': sorted({s.client for s in samples}),
                                  'audit_logs': [str(p) for p in audit_paths], 'audit_summary': summarize_audit(audit_rows),
                                  'bad_records': monitor.bad_lines, 'warnings': monitor.errors},
                                 ensure_ascii=False, indent=2))
                break
            if args.command == 'watch':
                fresh = [s for s in samples if s.uid not in seen]
                if not iteration and not args.json_lines:
                    print('持续监控 Codex Desktop / CLI；模型响应完成后更新，Ctrl+C 退出。')
                for s in reversed(fresh[:10] if not iteration else fresh):
                    if args.json_lines:
                        print(json.dumps(asdict(s), ensure_ascii=False, allow_nan=False), flush=True)
                    else:
                        print(f'{local_time(s.completed_at)}  {s.client:7}  {s.model:25}  '
                              f'{number(s.effective_tps):>8} TPS  {s.output_tokens:>6} tokens  '
                              f'{number(s.duration_seconds):>6}s  {s.session_id[:12]}', flush=True)
                seen.update(s.uid for s in samples)
                iteration += 1
                if args.count and iteration >= args.count:
                    break
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        print(f'错误：{exc}', file=sys.stderr)
        return 1
    if monitor.bad_lines and not getattr(args, 'json', False) and not getattr(args, 'json_lines', False):
        print(f'提示：{monitor.bad_lines} 条损坏或不完整统计已跳过。', file=sys.stderr)
    if monitor.errors:
        for error in monitor.errors[:5]:
            print(f'读取提示：{error}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
