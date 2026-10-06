"""Passive reasoning-effort audit. Only allowlisted metadata is retained.

Echo differences describe protocol fields, never hidden compute or model weights.
See README.md for the versioned JSONL evidence contract.
"""
from __future__ import annotations

from collections import Counter
import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')


def profile_from_home(home: str | Path) -> str:
    path = Path(home)
    if path.name == '.codex':
        return '官方'
    if path.name == '.codex-api':
        return 'default'
    if path.parent.name in ('profiles', 'accounts') and path.parent.parent.name == '.codex-api':
        return ('账号/' if path.parent.name == 'accounts' else '') + path.name
    return ''
AUDIT_FILTERS = {
    '全部审计结果': 'all', '回显等级降低': 'lowered', '回显等级提高': 'raised',
    '出站 / 最终一致': 'match', '首末回显变化': 'changed', '配置等级降低': 'config_lowered',
    '配置变化': 'config_changed', '无法审计': 'unknown', '进行中': 'in_progress',
    '请求失败': 'failed', '未完整结束': 'incomplete',
}
TERMINALS = {'response_completed': 'completed', 'response_failed': 'failed',
             'response_incomplete': 'incomplete'}


def _text(value: Any) -> str:
    return value if isinstance(value, str) and len(value) <= 512 else ''


def _time(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError('审计事件缺少时间')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('审计事件时间必须带时区')
    return parsed.astimezone(timezone.utc).isoformat()


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _effort(obj: dict) -> tuple[str | None, bool]:
    reasoning = obj.get('reasoning')
    nested = reasoning.get('effort') if isinstance(reasoning, dict) else None
    flat = obj.get('reasoning_effort')
    values = [v for v in (nested, flat) if v is not None]
    invalid = any(not isinstance(v, str) or not _text(v) for v in values)
    conflict = invalid or len(set(v for v in values if isinstance(v, str))) > 1
    return next((_text(v) for v in values if _text(v)), None), conflict


@dataclass(slots=True)
class AuditRecord:
    uid: str
    source_id: str = ''
    source_path: str = ''
    request_id: str = ''
    attempt_id: str = ''
    session_id: str = ''
    response_id: str = ''
    turn_id: str = ''
    completed_at: str = ''
    started_at: str = ''
    client: str = 'Other'
    profile: str = ''
    model: str = '未记录'
    model_origin: str = 'request'
    returned_model: str = ''
    configured_effort: str | None = None
    previous_effort: str | None = None
    previous_model: str = ''
    outbound_effort: str | None = None
    first_effort: str | None = None
    final_effort: str | None = None
    effective_effort: str | None = None
    reasoning_tokens: int | None = None
    protocol: str = ''
    observation_boundary: str = ''
    request_state: str = 'not_collected'
    stream: bool | None = None
    has_created: bool = False
    conflicts: str = ''
    note: str = ''
    home: str = ''

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.source_id, self.request_id, self.attempt_id

    @property
    def first_display(self) -> str:
        if self.stream is False:
            return '不适用'
        return self.first_effort or ('未返回' if self.has_created else '未采集')

    @property
    def first_final_change(self) -> str:
        if self.first_effort and self.final_effort and self.first_effort != self.final_effort:
            return f'{self.first_effort} → {self.final_effort}'
        return ''

    @property
    def audit_status(self) -> str:
        if self.conflicts:
            return 'unknown'
        if self.request_state in ('failed', 'incomplete', 'in_progress'):
            return self.request_state
        if self.request_state == 'not_collected':
            if self.previous_model and self.previous_model != self.model:
                return 'config_changed'
            if self.previous_effort in EFFORTS and self.configured_effort in EFFORTS:
                if EFFORTS.index(self.configured_effort) < EFFORTS.index(self.previous_effort):
                    return 'config_lowered'
                if self.configured_effort != self.previous_effort:
                    return 'config_changed'
            return 'unknown'
        if (self.protocol != 'responses' or self.observation_boundary not in
                ('client_to_provider', 'proxy_to_upstream') or self.request_state != 'completed'):
            return 'unknown'
        if self.outbound_effort not in EFFORTS or self.final_effort not in EFFORTS:
            return 'unknown'
        difference = EFFORTS.index(self.final_effort) - EFFORTS.index(self.outbound_effort)
        return 'lowered' if difference < 0 else 'raised' if difference > 0 else 'match'

    @property
    def audit_result(self) -> str:
        status = self.audit_status
        if self.conflicts:
            return f'无法审计：字段冲突（{self.conflicts}）'
        if status == 'lowered':
            return f'回显等级降低：{self.outbound_effort} → {self.final_effort}'
        if status == 'raised':
            return f'回显等级提高：{self.outbound_effort} → {self.final_effort}'
        if status == 'match':
            return '出站 / 最终回显一致' + ('；首末回显变化' if self.first_final_change else '')
        if status == 'config_lowered':
            return f'配置等级降低：{self.previous_effort} → {self.configured_effort}（回显未采集）'
        if status == 'config_changed':
            return '配置模型变化（回显未采集）' if self.previous_model != self.model and self.previous_model else (
                f'配置等级变化：{self.previous_effort} → {self.configured_effort}（回显未采集）')
        if status == 'in_progress':
            return '进行中：等待最终响应'
        if status == 'failed':
            return '请求失败'
        if status == 'incomplete':
            return '未完整结束'
        if self.request_state == 'not_collected':
            return '无法审计：出站与回显未采集'
        if self.protocol != 'responses':
            return '无法审计：协议未支持或未记录'
        if self.observation_boundary not in ('client_to_provider', 'proxy_to_upstream'):
            return '无法审计：观测边界未记录'
        if self.outbound_effort is None or self.final_effort is None:
            return '无法审计：出站或最终等级未返回'
        return '无法审计：未知等级'

    def to_dict(self) -> dict:
        return dict(asdict(self), audit_status=self.audit_status, audit_result=self.audit_result,
                    first_final_change=self.first_final_change)


def _assign(row: AuditRecord, field: str, value: Any) -> None:
    if value is None or value == '' or (field == 'model' and value == '未记录'):
        return
    current = getattr(row, field)
    empty = current is None or current == '' or (field == 'model' and current == '未记录')
    if empty:
        setattr(row, field, value)
    elif current != value:
        _conflict(row, field)


def _conflict(row: AuditRecord, field: str) -> None:
    fields = set(row.conflicts.split(', ')) - {''}
    fields.add(field)
    row.conflicts = ', '.join(sorted(fields))


class AuditParser:
    def __init__(self, path: Path):
        self.path = path
        self.records: dict[tuple, AuditRecord] = {}
        self.warnings = 0

    def feed(self, obj: Any) -> None:
        if not isinstance(obj, dict) or obj.get('schema_version') != 1 or isinstance(obj.get('schema_version'), bool):
            self.warnings += 1
            return
        kind = _text(obj.get('event_type')).replace('.', '_')
        if kind not in ('request_sent', 'response_created', *TERMINALS):
            self.warnings += 1
            return
        request_id, attempt = _text(obj.get('request_id')), _text(obj.get('attempt_id'))
        if not request_id or not attempt:
            self.warnings += 1
            return
        try:
            t = _time(obj.get('timestamp'))
        except (ValueError, TypeError):
            self.warnings += 1
            return
        source = _text(obj.get('source_id')) or str(self.path.resolve())
        identity = source, request_id, attempt
        if identity not in self.records:
            uid = 'audit-' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
            self.records[identity] = AuditRecord(uid=uid, source_id=source, source_path=str(self.path),
                                                request_id=request_id, attempt_id=attempt,
                                                request_state='in_progress', home=str(self.path))
        row = self.records[identity]
        row.completed_at = max(t, row.completed_at)
        for field in ('session_id', 'turn_id', 'protocol', 'observation_boundary', 'profile'):
            _assign(row, field, _text(obj.get(field)))
        client = _text(obj.get('client'))
        if client:
            if row.client == 'Other':
                row.client = client
            elif row.client != client:
                _conflict(row, 'client')
        if kind == 'request_sent':
            payload = obj.get('request')
            if not isinstance(payload, dict):
                self.warnings += 1
                return
            row.started_at = min(t, row.started_at) if row.started_at else t
            _assign(row, 'model', _text(payload.get('model')))
            effort, conflict = _effort(payload)
            _assign(row, 'outbound_effort', effort)
            if conflict:
                _conflict(row, 'outbound_effort')
            if isinstance(payload.get('stream'), bool):
                _assign(row, 'stream', payload['stream'])
            items = payload.get('input')
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and item.get('type') == 'configuration_update':
                        effective, invalid = _effort(item)
                        row.effective_effort = effective
                        if invalid:
                            _conflict(row, 'effective_effort')
                        row.note = 'configuration_update 的有效等级单列；回显比对使用请求级等级。'
        else:
            payload = obj.get('response')
            if not isinstance(payload, dict):
                self.warnings += 1
                return
            _assign(row, 'response_id', _text(payload.get('id')))
            _assign(row, 'returned_model', _text(payload.get('model')))
            effort, conflict = _effort(payload)
            field = 'first_effort' if kind == 'response_created' else 'final_effort'
            _assign(row, field, effort)
            if conflict:
                _conflict(row, field)
            if kind == 'response_created':
                row.has_created = True
            else:
                terminal = TERMINALS[kind]
                if row.request_state not in ('in_progress', terminal):
                    _conflict(row, 'request_state')
                row.request_state = terminal
                usage = payload.get('usage')
                if isinstance(usage, dict):
                    details = usage.get('output_tokens_details')
                    reasoning = _count(details.get('reasoning_tokens')) if isinstance(details, dict) else None
                    output = _count(usage.get('output_tokens'))
                    if reasoning is not None and (output is None or reasoning <= output):
                        _assign(row, 'reasoning_tokens', reasoning)
                    elif reasoning is not None:
                        self.warnings += 1

    def rows(self) -> list[AuditRecord]:
        return list(self.records.values())


@dataclass
class _File:
    parser: AuditParser
    position: int = 0
    identity: tuple = ()
    prefix: bytes = b''
    bad_lines: int = 0


class AuditMonitor:
    def __init__(self, paths: list[Path] | None = None):
        self.paths = list(paths or [])
        self.files: dict[str, _File] = {}
        self.errors: list[str] = []
        self.bad_lines = 0
        self.profile_labels: dict[str, str] = {}

    def refresh(self, since: datetime | None = None) -> list[AuditRecord]:
        self.errors = []
        present = set()
        for configured in self.paths:
            paths = configured.rglob('*.jsonl') if configured.is_dir() else [configured]
            for path in paths:
                try:
                    path = path.expanduser().resolve()
                    key = os.path.normcase(str(path))
                    if key in present:
                        continue
                    stat = path.stat()
                    present.add(key)
                    state = self.files.get(key)
                    with path.open('rb') as stream:
                        prefix = stream.read(min(128, stat.st_size))
                        identity = stat.st_dev, stat.st_ino
                        if (state is None or stat.st_size < state.position or state.identity != identity or
                                (state.prefix and not prefix.startswith(state.prefix))):
                            state = _File(AuditParser(path), identity=identity, prefix=prefix)
                            self.files[key] = state
                        stream.seek(state.position)
                        while True:
                            pos = stream.tell()
                            line = stream.readline()
                            if not line or not line.endswith(b'\n'):
                                state.position = pos
                                break
                            state.position = stream.tell()
                            try:
                                state.parser.feed(json.loads(line))
                            except (ValueError, UnicodeError):
                                state.bad_lines += 1
                except OSError as exc:
                    self.errors.append(f'{path}: {exc.strerror or type(exc).__name__}')
        self.files = {key: state for key, state in self.files.items() if key in present}
        self.bad_lines = sum(s.bad_lines + s.parser.warnings for s in self.files.values())
        unique: dict[tuple, AuditRecord] = {}
        for state in self.files.values():
            for row in state.parser.rows():
                if row.identity not in unique:
                    unique[row.identity] = replace(row)
                    continue
                target = unique[row.identity]
                for field in ('profile', 'session_id', 'response_id', 'turn_id', 'outbound_effort', 'first_effort',
                              'final_effort', 'effective_effort', 'model', 'returned_model', 'reasoning_tokens',
                              'protocol', 'observation_boundary', 'stream'):
                    _assign(target, field, getattr(row, field))
                target.has_created |= row.has_created
                if row.client != 'Other':
                    if target.client == 'Other':
                        target.client = row.client
                    elif target.client != row.client:
                        _conflict(target, 'client')
                target.completed_at = max(target.completed_at, row.completed_at)
                if row.started_at:
                    target.started_at = min(target.started_at, row.started_at) if target.started_at else row.started_at
                for field in row.conflicts.split(', '):
                    if field:
                        _conflict(target, field)
                if target.request_state == 'in_progress':
                    target.request_state = row.request_state
                elif row.request_state not in ('in_progress', target.request_state):
                    _conflict(target, 'request_state')
                target.note = target.note or row.note
        rows = [r for r in unique.values() if since is None or datetime.fromisoformat(r.completed_at) >= since]
        for row in rows:
            if not row.profile:
                row.profile = self.profile_labels.get(str(Path(row.source_path).resolve()), '')
        return sorted(rows, key=lambda r: (r.completed_at, r.uid), reverse=True)


def build_audit_rows(samples: list, evidence: list[AuditRecord]) -> list[AuditRecord]:
    counts = Counter(s.response_id for s in samples if s.response_id)
    sessions = Counter((s.response_id, s.session_id) for s in samples if s.response_id)
    indexed: dict[str, list[AuditRecord]] = {}
    for row in evidence:
        if row.response_id:
            indexed.setdefault(row.response_id, []).append(row)
    used = set()
    rows = []
    for sample in samples:
        local = AuditRecord(uid=sample.uid, session_id=sample.session_id, response_id=sample.response_id,
                            turn_id=sample.turn_id, completed_at=sample.completed_at, client=sample.client,
                            profile=profile_from_home(sample.home),
                            model=sample.model, model_origin='configuration',
                            configured_effort=sample.effort if sample.effort != '—' else None,
                            previous_effort=getattr(sample, 'previous_effort', '') or None,
                            previous_model=getattr(sample, 'previous_model', ''),
                            reasoning_tokens=sample.reasoning_tokens, source_path=sample.log_path,
                            source_id='session_log', home=sample.home,
                            note='配置变化无法区分用户手动调整与客户端自动调整；不代表服务端降级。')
        candidates = [r for r in indexed.get(sample.response_id, []) if
                      (not r.profile or not local.profile or r.profile == local.profile) and
                      (r.session_id == sample.session_id and (sessions[(sample.response_id, sample.session_id)] == 1
                        or bool(r.profile and local.profile)) or (not r.session_id and counts[sample.response_id] == 1))]
        if len(candidates) == 1 and candidates[0].uid not in used:
            source = candidates[0]
            local = replace(source, uid=sample.uid, session_id=sample.session_id, turn_id=sample.turn_id,
                            profile=source.profile or local.profile,
                            configured_effort=local.configured_effort, previous_effort=local.previous_effort,
                            previous_model=local.previous_model, home=sample.home,
                            client=sample.client if source.client == 'Other' else source.client)
            if local.model == '未记录':
                local.model, local.model_origin = sample.model, 'configuration'
            if local.reasoning_tokens is None:
                local.reasoning_tokens = sample.reasoning_tokens
            elif sample.reasoning_tokens is not None and local.reasoning_tokens != sample.reasoning_tokens:
                _conflict(local, 'reasoning_tokens')
            used.add(source.uid)
        elif len(candidates) > 1:
            local.note += ' 多条审计尝试对应同一响应，无法唯一关联。'
        rows.append(local)
    rows.extend(replace(r, note=r.note + ' 独立审计记录，未关联 TPS。') for r in evidence if r.uid not in used)
    return sorted(rows, key=lambda r: (r.completed_at, r.uid), reverse=True)


def select_audit(rows: list[AuditRecord], client='all', model='', session='', home='', status='all', profile='') -> list[AuditRecord]:
    return [r for r in rows if (client == 'all' or r.client.lower() == client.lower() or
            (client == 'other' and r.client not in ('Desktop', 'CLI'))) and model.lower() in r.model.lower() and
            session.lower() in r.session_id.lower() and (not home or r.home == home) and
            (not profile or (r.profile or '未记录') == profile) and
            (status == 'all' or r.audit_status == status or (status == 'changed' and r.first_final_change))]


def summarize_audit(rows: list[AuditRecord]) -> dict:
    comparable = sum(r.audit_status in ('match', 'lowered', 'raised') for r in rows)
    return dict(record_count=len(rows), comparable_count=comparable,
                lowered_count=sum(r.audit_status == 'lowered' for r in rows),
                changed_count=sum(bool(r.first_final_change) for r in rows),
                config_lowered_count=sum(r.audit_status == 'config_lowered' for r in rows),
                unknown_count=sum(r.audit_status == 'unknown' for r in rows),
                coverage=comparable / len(rows) if rows else None)


def export_audit(rows: list[AuditRecord], path: Path, fmt: str, *, overwrite=False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError('输出文件已存在；请换文件名或使用 --overwrite。')
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [r.to_dict() for r in rows]
    if fmt == 'json':
        with path.open('w' if overwrite else 'x', encoding='utf-8') as stream:
            json.dump(dict(schema_version=1, metric='reasoning_effort_audit', summary=summarize_audit(rows),
                           records=data), stream, ensure_ascii=False, indent=2, allow_nan=False)
    else:
        fields = list(AuditRecord.__dataclass_fields__) + ['audit_status', 'audit_result', 'first_final_change']
        with path.open('w' if overwrite else 'x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)
