import json
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_tps import LogParser, Monitor, discover_homes, export_samples, main, select_samples, summarize


def event(second, kind, payload):
    return {'timestamp': f'2026-10-03T12:00:{second:06.3f}Z', 'type': kind, 'payload': payload}


def usage(output=100, reasoning=40, input_tokens=300):
    return {'input_tokens': input_tokens, 'output_tokens': output,
            'reasoning_output_tokens': reasoning, 'total_tokens': input_tokens + output}


def meta(origin='Codex Desktop', source='vscode', sid='session-one'):
    return event(0, 'session_meta', {'id': sid, 'originator': origin, 'source': source,
                                    'model_provider': 'openai'})


def start(second=1):
    return event(second, 'event_msg', {'type': 'task_started', 'turn_id': 'turn-one'})


def assistant(second=11):
    return event(second, 'response_item', {'type': 'message', 'role': 'assistant',
                                         'content': [{'text': 'PRIVATE DO NOT RETAIN'}]})


def record(second=11, rid='response-one', tokens=None, total=None):
    return event(second, 'token_usage_record', {'response_id': rid, 'usage': tokens or usage(),
                                               'thread_token_usage': total or tokens or usage()})


class ParserTests(unittest.TestCase):
    def parser(self, *rows):
        parser = LogParser(Path('example.jsonl'), 'test-home')
        for row in rows:
            parser.feed(row)
        return parser

    def test_desktop_new_format_and_reasoning_subset(self):
        p = self.parser(meta(), start(), event(1, 'turn_context', {'model': 'test-model', 'effort': 'high'}),
                        assistant(), record())
        r = p.records[0]
        self.assertEqual(r.client, 'Desktop')
        self.assertEqual(r.model, 'test-model')
        self.assertEqual(r.duration_seconds, 10)
        self.assertEqual(r.effective_tps, 10)
        self.assertEqual(r.visible_tokens, 60)
        self.assertEqual(r.output_tokens, 100)
        self.assertNotIn('PRIVATE', repr(p.__dict__))

    def test_cli_originator_overrides_vscode_source(self):
        for source in ('cli', 'exec', 'vscode'):
            p = self.parser(meta('codex-tui', source), start(), assistant(), record())
            self.assertEqual(p.records[0].client, 'CLI')

    def test_new_usage_and_mirrored_old_event_count_once(self):
        u = usage()
        p = self.parser(meta(), start(), assistant(), record(),
                        event(12, 'event_msg', {'type': 'token_count', 'info': {
                            'last_token_usage': u, 'total_token_usage': u}}), record())
        self.assertEqual(len(p.records), 1)

    def test_legacy_delayed_usage_excludes_tools(self):
        u = usage()
        p = self.parser(meta('codex_cli_rs', 'cli'), start(),
                        event(11, 'response_item', {'type': 'function_call', 'call_id': 'tool-a'}),
                        event(31, 'response_item', {'type': 'function_call_output', 'call_id': 'tool-a'}),
                        event(31, 'event_msg', {'type': 'token_count', 'info': {
                            'last_token_usage': u, 'total_token_usage': u}}),
                        assistant(41), record(41, 'response-two', total=usage(200, 80, 600)))
        self.assertEqual([r.duration_seconds for r in p.records], [10, 10])
        self.assertEqual([r.effective_tps for r in p.records], [10, 10])

    def test_new_usage_before_parallel_tools_excludes_wait(self):
        p = self.parser(meta(), start(),
                        event(10, 'response_item', {'type': 'function_call', 'call_id': 'a'}),
                        event(11, 'response_item', {'type': 'function_call', 'call_id': 'b'}), record(),
                        event(20, 'response_item', {'type': 'function_call_output', 'call_id': 'a'}),
                        event(31, 'response_item', {'type': 'function_call_output', 'call_id': 'b'}),
                        assistant(41), record(41, 'response-two', total=usage(200, 80, 600)))
        self.assertEqual([r.duration_seconds for r in p.records], [10, 10])

    def test_repeated_quota_updates_do_not_create_responses(self):
        u = usage()
        tc = {'type': 'token_count', 'info': {'last_token_usage': u, 'total_token_usage': u}}
        p = self.parser(meta(), start(), assistant(), event(11, 'event_msg', tc),
                        event(12, 'event_msg', tc), event(13, 'event_msg', tc))
        self.assertEqual(len(p.records), 1)

    def test_legacy_cumulative_fallback_uses_delta(self):
        p = self.parser(meta(), start(), assistant(), event(11, 'event_msg', {
            'type': 'token_count', 'info': {'total_token_usage': usage()}}),
            assistant(21), event(21, 'event_msg', {'type': 'token_count', 'info': {
                'total_token_usage': usage(150, 60, 600)}}))
        self.assertEqual([r.output_tokens for r in p.records], [100, 50])

    def test_no_start_is_not_fabricated_tps(self):
        p = self.parser(meta(), assistant(), record())
        self.assertIsNone(p.records[0].effective_tps)
        self.assertIsNone(p.records[0].duration_seconds)

    def test_zero_duration_and_missing_reasoning(self):
        p = self.parser(meta(), start(11), assistant(), record(tokens={'output_tokens': 100}))
        self.assertIsNone(p.records[0].effective_tps)
        self.assertIsNone(p.records[0].reasoning_tokens)
        self.assertIsNone(p.records[0].visible_tokens)

    def test_turn_idle_time_is_excluded(self):
        p = self.parser(meta(), start(), assistant(), record(),
                        event(12, 'event_msg', {'type': 'task_complete'}), start(40),
                        assistant(50), record(50, 'response-two', total=usage(200, 80, 600)))
        self.assertEqual([r.duration_seconds for r in p.records], [10, 10])

    def test_model_change_and_interruption(self):
        p = self.parser(meta(), start(), assistant(), record(),
                        event(12, 'event_msg', {'type': 'turn_aborted'}),
                        event(20, 'turn_context', {'model': 'new-model'}), start(21),
                        assistant(31), record(31, 'response-two', total=usage(200, 80, 600)))
        self.assertEqual(p.records[-1].duration_seconds, 10)
        self.assertEqual(p.records[-1].model, 'new-model')

    def test_impossible_reasoning_and_invalid_token_counts(self):
        p = self.parser(meta(), start(), assistant(), record(tokens={'output_tokens':100,'reasoning_output_tokens':200}),
                        record(12,'invalid',tokens={'output_tokens':-4}))
        self.assertEqual(len(p.records), 1)
        self.assertIsNone(p.records[0].visible_tokens)
        self.assertGreater(p.warnings, 0)

    def test_compaction_does_not_create_a_cumulative_burst(self):
        p = self.parser(meta(), start(), assistant(), record(), event(20,'compacted',{}),
                        event(21,'event_msg',{'type':'token_count','info':{'total_token_usage':usage(500,200,3000)}}))
        self.assertEqual(len(p.records),1)

    def test_client_filter_and_model_filter(self):
        p = self.parser(meta('codex_cli_rs','cli'), start(), event(1,'turn_context',{'model':'my-model'}), assistant(), record())
        self.assertEqual(len(select_samples(p.records,client='cli',model='MY-',session='one')),1)
        self.assertEqual(len(select_samples(p.records,client='desktop')),0)


class MonitorTests(unittest.TestCase):
    def test_incremental_partial_line_and_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            logs = home / 'sessions'
            logs.mkdir()
            p = logs / 'rollout-test.jsonl'
            initial = [meta(), start(), assistant()]
            p.write_text(''.join(json.dumps(r) + '\n' for r in initial), encoding='utf-8')
            m = Monitor([home], include_archived=False)
            self.assertEqual(len(m.refresh()), 0)
            tail = json.dumps(record()).encode()
            with p.open('ab') as f:
                f.write(tail[:len(tail)//2])
            self.assertEqual(len(m.refresh()), 0)
            with p.open('ab') as f:
                f.write(tail[len(tail)//2:] + b'\n')
            self.assertEqual(len(m.refresh()), 1)
            self.assertEqual(len(m.refresh()), 1)
            p.write_text(json.dumps(meta()) + '\n', encoding='utf-8')
            self.assertEqual(len(m.refresh()), 0)

    def test_auto_discovery_custom_and_account_homes(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for root in (base/'.codex', base/'.codex-api/accounts/a', base/'.codex-api/profiles/b'):
                (root/'sessions').mkdir(parents=True)
            with patch.dict(os.environ, {'CODEX_HOME': str(base/'custom')}):
                homes = discover_homes(base)
            self.assertIn(base/'.codex-api/accounts/a', homes)
            self.assertIn(base/'.codex-api/profiles/b', homes)
            self.assertIn(base/'custom', homes)

    def test_duplicate_session_copies_and_bad_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            logs = home/'sessions'
            logs.mkdir()
            content = ''.join(json.dumps(r)+'\n' for r in (meta(), start(), assistant(), record()))
            for name in ('a.jsonl','b.jsonl'):
                (logs/name).write_text(content + '{bad json}\n', encoding='utf-8')
            m = Monitor([home], include_archived=False)
            self.assertEqual(len(m.refresh()), 1)
            self.assertGreater(m.bad_lines, 0)

    def test_weighted_average_excludes_untimed_rows(self):
        p = LogParser(Path('file.jsonl'), 'home')
        for r in (meta(), start(), assistant(), record(),
                  assistant(31), record(31, 'two', tokens=usage(400), total=usage(500)),
                  event(32,'event_msg',{'type':'task_complete'}), record(33,'untimed')):
            p.feed(r)
        summary = summarize(p.records)
        self.assertAlmostEqual(summary['weighted_tps'], 500/30)
        self.assertEqual(summary['timed_count'], 2)

    def test_export_roundtrip_and_prevent_silent_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            p = LogParser(Path('file.jsonl'),'home')
            for row in (meta(),start(),assistant(),record()):
                p.feed(row)
            json_path = Path(folder)/'export.json'
            csv_path = Path(folder)/'export.csv'
            export_samples(p.records,json_path,'json')
            export_samples(p.records,csv_path,'csv')
            self.assertEqual(json.loads(json_path.read_text(encoding='utf-8'))['samples'][0]['effective_tps'],10)
            self.assertTrue(csv_path.read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertNotIn('PRIVATE',json_path.read_text(encoding='utf-8'))
            with self.assertRaises(FileExistsError):
                export_samples(p.records,json_path,'json')

    def test_watch_starts_with_newest_ten_and_never_repeats(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home/'sessions').mkdir()
            rows = [meta(), start()]
            for i in range(12):
                rows.extend([assistant(i+2),record(i+2,str(i),total=usage(100*(i+1),40*(i+1),300*(i+1)))])
            (home/'sessions/a.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
            out = io.StringIO()
            with patch('codex_tps.discover_homes',return_value=[home]),patch('codex_tps.time.sleep'),redirect_stdout(out):
                result = main(['watch','--days','0','--count','2','--json-lines'])
            responses = [json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual(result,0)
            self.assertEqual(len(responses),10)
            self.assertEqual([s['response_id'] for s in responses],[str(i) for i in range(2,12)])

    def test_partial_unicode_line_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home/'sessions').mkdir()
            path = home/'sessions/a.jsonl'
            prefix=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in (meta(),start(),assistant()))
            path.write_text(prefix,encoding='utf-8')
            monitor=Monitor([home])
            monitor.refresh()
            changed = Path(folder)/'replacement'
            changed.write_text(''.join(json.dumps(r)+'\n' for r in (meta(sid='new-id'),start(),assistant(),record(rid='new-response'))),encoding='utf-8')
            changed.replace(path)
            samples=monitor.refresh()
            self.assertEqual(len(samples),1)
            self.assertEqual(samples[0].session_id,'new-id')


if __name__ == '__main__':
    unittest.main()
