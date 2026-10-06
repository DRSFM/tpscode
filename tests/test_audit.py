"""Synthetic request/response evidence; never sends inference requests."""
import csv
from contextlib import redirect_stdout
from dataclasses import replace
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_tps import LogParser, Monitor, main, summarize
from reasoning_audit import AuditMonitor, AuditParser, build_audit_rows, export_audit, summarize_audit
from test_core import assistant, event, meta, record, start


def audit_event(kind, second=1, request_id='req-one', attempt_id='1', **values):
    return dict(schema_version=1, source_id='synthetic', request_id=request_id,
                attempt_id=attempt_id, timestamp=f'2026-10-03T12:00:{second:02d}Z',
                protocol='responses', observation_boundary='client_to_provider',
                event_type=kind, **values)


def request(**kwargs):
    return audit_event('request_sent', request={'model': 'test-model', 'stream': True,
                       'reasoning': {'effort': 'xhigh'}, 'input': 'PRIVATE REQUEST'}, **kwargs)


def response(kind='response_completed', effort='low', second=11, **kwargs):
    return audit_event(kind, second, response={'id': 'response-one', 'model': 'test-model',
                       'reasoning': {'effort': effort}, 'usage': {'output_tokens': 100,
                       'output_tokens_details': {'reasoning_tokens': 40}},
                       'output': [{'text': 'PRIVATE RESPONSE'}]}, **kwargs)


class AuditTests(unittest.TestCase):
    def test_profile_metadata_conflicts_and_cross_home_association_are_not_guessed(self):
        from reasoning_audit import select_audit
        parser, row = self.parse(request(profile='anyrouter'), response(profile='anyrouter'))
        self.assertEqual(row.profile, 'anyrouter')
        self.assertEqual(select_audit([row], profile='anyrouter'), [row])
        parser.feed(response(profile='other'))
        self.assertEqual(row.audit_status, 'unknown')
        self.assertIn('profile', row.conflicts)
        _, valid = self.parse(request(profile='anyrouter'), response(profile='anyrouter'))
        first = replace(self.sample(), home=str(Path.home()/'.codex-api'/'profiles'/'other'), uid='other-local')
        second = replace(first, home=str(Path.home()/'.codex-api'/'profiles'/'anyrouter'), uid='router-local')
        valid.session_id = first.session_id
        valid.response_id = first.response_id
        rows = build_audit_rows([first, second], [valid])
        matched = next(r for r in rows if r.outbound_effort)
        self.assertEqual(matched.uid, 'router-local')
        self.assertEqual(matched.profile, 'anyrouter')

    def parse(self, *events):
        parser = AuditParser(Path('synthetic.jsonl'))
        for value in events:
            parser.feed(value)
        return parser, parser.rows()[0]

    def sample(self, *contexts):
        parser = LogParser(Path('session.jsonl'), 'test-home')
        for value in (meta(), start(), *contexts, assistant(), record()):
            parser.feed(value)
        return parser.records[0]

    def test_three_stage_downgrade_and_privacy(self):
        parser, row = self.parse(request(), response('response_created', 'high', 2), response())
        self.assertEqual(row.audit_status, 'lowered')
        self.assertEqual((row.outbound_effort, row.first_effort, row.final_effort), ('xhigh','high','low'))
        self.assertIn('high → low', row.first_final_change)
        self.assertEqual(row.reasoning_tokens, 40)
        self.assertNotIn('PRIVATE', repr(parser.__dict__))
        self.assertNotIn('PRIVATE', json.dumps(row.to_dict()))

    def test_unknown_zero_pending_failure_and_nonstream(self):
        _, row = self.parse(request(), response(effort=None))
        self.assertEqual(row.audit_status, 'unknown')
        _, row = self.parse(request(), response('response_created', 'high', 2))
        self.assertEqual(row.audit_status, 'in_progress')
        for kind, status in [('response_failed','failed'), ('response_incomplete','incomplete')]:
            _, row = self.parse(request(), response(kind))
            self.assertEqual(row.audit_status, status)
        obj = request()
        obj['request']['stream'] = False
        done = response(effort='xhigh')
        done['response']['usage']['output_tokens_details']['reasoning_tokens'] = 0
        _, row = self.parse(obj, done)
        self.assertEqual(row.audit_status, 'match')
        self.assertEqual(row.reasoning_tokens, 0)
        self.assertEqual(row.first_display, '不适用')

    def test_unknown_effort_alias_conflict_and_invalid_usage(self):
        _, row = self.parse(request(), response(effort='custom'))
        self.assertEqual(row.final_effort, 'custom')
        self.assertEqual(row.audit_status, 'unknown')
        done = response()
        done['response']['reasoning_effort'] = 'xhigh'
        _, row = self.parse(request(), done)
        self.assertEqual(row.audit_status, 'unknown')
        self.assertIn('冲突', row.audit_result)
        done = response()
        done['response']['usage']['output_tokens_details']['reasoning_tokens'] = True
        _, row = self.parse(request(), done)
        self.assertIsNone(row.reasoning_tokens)

    def test_configuration_update_does_not_change_echo_baseline(self):
        obj = request()
        obj['request']['reasoning']['effort'] = 'low'
        obj['request']['input'] = [{'type':'configuration_update', 'reasoning':{'effort':'high'}}]
        _, row = self.parse(obj, response(effort='low'))
        self.assertEqual(row.audit_status, 'match')
        self.assertEqual(row.effective_effort, 'high')
        self.assertIn('请求级', row.note)

    def test_out_of_order_duplicate_and_retry_isolation(self):
        parser, row = self.parse(response(), request(), response(), response('response_created','high',2))
        self.assertEqual(len(parser.rows()), 1)
        self.assertEqual(row.audit_status, 'lowered')
        self.assertEqual(row.first_effort, 'high')
        parser.feed(request(attempt_id='2'))
        self.assertEqual(len(parser.rows()), 2)

    def test_only_configuration_can_never_be_echo_match(self):
        sample = self.sample(event(1,'turn_context',{'model':'test-model','effort':'xhigh'}))
        row = build_audit_rows([sample], [])[0]
        self.assertEqual(row.audit_status, 'unknown')
        self.assertIsNone(row.outbound_effort)
        self.assertIsNone(row.final_effort)
        self.assertEqual(row.configured_effort, 'xhigh')

    def test_local_configuration_change_is_not_server_downgrade(self):
        sample = self.sample(event(1,'turn_context',{'model':'test-model','effort':'xhigh','turn_id':'old'}),
                             event(2,'turn_context',{'model':'test-model','effort':'high','turn_id':'new'}))
        row = build_audit_rows([sample], [])[0]
        self.assertEqual(row.audit_status, 'config_lowered')
        self.assertIn('配置', row.audit_result)
        self.assertIn('用户', row.note)

    def test_stable_next_turn_does_not_repeat_previous_configuration_drop(self):
        parser = LogParser(Path('session.jsonl'), 'test-home')
        for value in (meta(), event(1,'turn_context',{'model':'test-model','effort':'xhigh','turn_id':'old'}),
                      event(2,'turn_context',{'model':'test-model','effort':'high','turn_id':'new'}),
                      event(3,'event_msg',{'type':'task_started','turn_id':'next'}),
                      event(3,'turn_context',{'model':'test-model','effort':'high','turn_id':'next'}),
                      assistant(),record()):
            parser.feed(value)
        self.assertEqual(build_audit_rows(parser.records,[])[0].audit_status,'unknown')

    def test_bad_schema_and_malformed_events_are_not_completed_verdicts(self):
        parser = AuditParser(Path('synthetic.jsonl'))
        for obj in (None,{},dict(request(),schema_version=True),dict(request(),attempt_id=''),
                    dict(request(),timestamp='2026-10-03T12:00:00'),dict(request(),request=[])):
            parser.feed(obj)
        self.assertGreaterEqual(parser.warnings,6)
        self.assertTrue(all(r.audit_status != 'match' for r in parser.rows()))

    def test_cross_file_conflicting_evidence_is_not_green(self):
        with tempfile.TemporaryDirectory() as folder:
            for i,effort in enumerate(('low','xhigh')):
                path = Path(folder)/f'{i}.jsonl'
                path.write_text('\n'.join(json.dumps(v) for v in (request(),response(effort=effort)))+'\n',encoding='utf-8')
            rows = AuditMonitor([Path(folder)]).refresh()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].audit_status,'unknown')
            self.assertIn('final_effort',rows[0].conflicts)

    def test_request_and_response_in_separate_files_merge_only_real_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            for name,value in [('request',request(client='Desktop')),('response',response())]:
                (Path(folder)/f'{name}.jsonl').write_text(json.dumps(value)+'\n',encoding='utf-8')
            rows = AuditMonitor([Path(folder)]).refresh()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].audit_status,'lowered')
            self.assertEqual(rows[0].client,'Desktop')

    def test_strict_response_association_and_no_duplicate_tps(self):
        sample = self.sample(event(1,'turn_context',{'model':'test-model','effort':'xhigh'}))
        _, evidence = self.parse(request(session_id='session-one'), response(session_id='session-one'))
        rows = build_audit_rows([sample], [evidence])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].uid, sample.uid)
        self.assertEqual(rows[0].configured_effort, 'xhigh')
        self.assertEqual(rows[0].audit_status, 'lowered')
        foreign = replace(evidence, session_id='different-session')
        self.assertEqual(len(build_audit_rows([sample], [foreign])), 2)
        no_session = replace(evidence, session_id='')
        other = replace(sample, uid='other', session_id='different-session')
        rows = build_audit_rows([sample, other], [no_session])
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(r.audit_status == 'lowered' for r in rows), 1)

    def test_incremental_partial_line_truncation_and_copy_dedup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'audit.jsonl'
            path.write_text(json.dumps(request())+'\n', encoding='utf-8')
            monitor = AuditMonitor([path])
            self.assertEqual(monitor.refresh()[0].audit_status, 'in_progress')
            data = json.dumps(response())
            with path.open('a', encoding='utf-8') as stream:
                stream.write(data[:50])
            self.assertEqual(monitor.refresh()[0].audit_status, 'in_progress')
            with path.open('a', encoding='utf-8') as stream:
                stream.write(data[50:]+'\n')
            self.assertEqual(monitor.refresh()[0].audit_status, 'lowered')
            copy = Path(folder)/'copy.jsonl'
            copy.write_bytes(path.read_bytes())
            monitor.paths.append(copy)
            self.assertEqual(len(monitor.refresh()), 1)
            path.write_text(json.dumps(request())+'\n', encoding='utf-8')
            monitor.paths = [path]
            self.assertEqual(monitor.refresh()[0].audit_status, 'in_progress')

    def test_export_and_coverage_uses_only_comparable_records(self):
        _, done = self.parse(request(), response())
        sample = self.sample()
        rows = [done, build_audit_rows([sample], [])[0]]
        summary = summarize_audit(rows)
        self.assertEqual(summary['comparable_count'], 1)
        self.assertEqual(summary['lowered_count'], 1)
        self.assertEqual(summary['coverage'], .5)
        with tempfile.TemporaryDirectory() as folder:
            js, cs = Path(folder)/'rows.json', Path(folder)/'rows.csv'
            export_audit(rows, js, 'json')
            export_audit(rows, cs, 'csv')
            self.assertEqual(json.loads(js.read_text(encoding='utf-8'))['schema_version'], 1)
            with cs.open(encoding='utf-8-sig', newline='') as stream:
                loaded = list(csv.DictReader(stream))
            self.assertEqual(loaded[0]['audit_status'], 'lowered')
            with self.assertRaises(FileExistsError):
                export_audit(rows, js, 'json')

    def test_monitor_and_cli_associate_without_changing_tps(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            sessions = home/'sessions'
            sessions.mkdir()
            session = sessions/'session.jsonl'
            context = event(1,'turn_context',{'model':'test-model','effort':'xhigh'})
            session.write_text('\n'.join(json.dumps(v) for v in
                               (meta(),start(),context,assistant(),record()))+'\n',encoding='utf-8')
            evidence = home/'audit.jsonl'
            evidence.write_text('\n'.join(json.dumps(v) for v in
                                (request(session_id='session-one'),response(session_id='session-one')))+'\n',encoding='utf-8')
            monitor = Monitor([home],audit_paths=[evidence])
            samples = monitor.refresh()
            self.assertEqual(len(samples),1)
            self.assertEqual(summarize(samples)['output_tokens'],100)
            self.assertEqual(len(monitor.audit_rows),1)
            self.assertEqual(monitor.audit_rows[0].audit_status,'lowered')
            with patch('codex_tps.discover_homes',return_value=[home]), \
                    patch('codex_tps.load_settings',return_value={}), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['audit','--days','0','--audit-log',str(evidence),'--json']),0)
            data = json.loads(output.getvalue())
            self.assertEqual(data['records'][0]['audit_status'],'lowered')
            exported = home/'out.json'
            with patch('codex_tps.discover_homes',return_value=[home]), \
                    patch('codex_tps.load_settings',return_value={}), redirect_stdout(io.StringIO()):
                self.assertEqual(main(['export','--days','0','--audit-log',str(evidence),
                                      '--view','audit','--format','json','--output',str(exported)]),0)
            self.assertEqual(json.loads(exported.read_text(encoding='utf-8'))['summary']['lowered_count'],1)


if __name__ == '__main__':
    unittest.main()
