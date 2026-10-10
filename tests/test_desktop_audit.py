from dataclasses import replace
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

from codex_tps import Monitor
from desktop import Desktop
from reasoning_audit import build_audit_rows
import test_audit as audit_helpers
from test_core import event


class DesktopAuditTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk unavailable: {exc}')
        self.root.withdraw()
        args = SimpleNamespace(view='audit',audit_status='all',archived=False,client='all',
                               model='',session='',days=7,smoke_report=None,screenshot=None)
        self.monitor = Monitor([])
        helper = audit_helpers.AuditTests()
        self.sample = helper.sample(event(1,'turn_context',{'model':'test-model','effort':'xhigh'}))
        with patch.object(Desktop,'request_refresh'):
            self.app = Desktop(self.root,self.monitor,args)
        self.app.samples = [self.sample]
        self.app.audit_rows = build_audit_rows([self.sample],[])
        self.app.update_choices()
        self.app.apply_filters()

    def tearDown(self):
        if hasattr(self,'root'):
            self.app.close()

    def test_late_evidence_refreshes_existing_uid_and_selected_details(self):
        uid = self.sample.uid
        self.app.table.selection_set(uid)
        _, evidence = audit_helpers.AuditTests().parse(audit_helpers.request(session_id='session-one'),
                                                      audit_helpers.response(session_id='session-one'))
        self.app.audit_rows = build_audit_rows([self.sample],[evidence])
        self.app.apply_filters()
        self.assertIn('回显等级降低',self.app.table.set(uid,'audit'))
        self.assertIn('xhigh',self.app.detail.cget('text'))
        self.assertIn('low',self.app.detail.cget('text'))
        self.assertIn('lowered',self.app.table.item(uid,'tags'))

    def test_view_switch_and_filters_share_export_selection(self):
        self.app.view.set('速度统计')
        self.app.apply_filters()
        self.assertEqual(tuple(self.app.table['displaycolumns']),self.app.speed_columns)
        self.assertEqual(self.app.table.set(self.sample.uid,'effort'),'xhigh')
        self.app.view.set('思考审计')
        self.app.audit_status.set('回显等级降低')
        self.app.apply_filters()
        self.assertEqual(self.app.table.get_children(),())
        self.assertEqual(self.app.audit_filtered,[])
        self.app.audit_status.set('无法审计')
        self.app.apply_filters()
        self.assertEqual(len(self.app.audit_filtered),1)
        with patch('desktop.filedialog.asksaveasfilename',return_value='test-output.json'), \
                patch('desktop.export_audit') as writer:
            self.app.export()
        self.assertEqual(writer.call_args.args[0],self.app.audit_filtered)
        self.assertEqual(writer.call_args.args[2],'json')

    def test_readonly_effort_is_visible_in_both_views_without_request_capture(self):
        self.assertIn('effort', self.app.table['displaycolumns'])
        self.assertEqual(self.app.table.set(self.sample.uid, 'effort'), 'xhigh')
        self.assertEqual(self.app.table.heading('effort')['text'], '思考等级（配置）')
        self.assertEqual(self.app.table.set(self.sample.uid, 'outbound'), '未采集')
        self.app.view.set('速度统计')
        self.app.apply_filters()
        self.assertEqual(self.app.table.set(self.sample.uid, 'effort'), 'xhigh')
        self.assertEqual(float(self.app.table.set(self.sample.uid, 'tps')), 10)

    def test_external_only_audit_records_are_visible_and_model_choice_exists(self):
        _, evidence = audit_helpers.AuditTests().parse(audit_helpers.request(),audit_helpers.response())
        self.app.samples = []
        self.app.audit_rows = [replace(evidence,model='external-model')]
        self.app.update_choices()
        self.app.apply_filters()
        self.assertIn('external-model',self.app.model_box['values'])
        self.assertEqual(len(self.app.table.get_children()),1)
        self.assertEqual(self.app.metric_vars[0].get(),'1')

    def test_profile_column_filter_and_export_keep_same_model_profiles_separate(self):
        _, evidence = audit_helpers.AuditTests().parse(audit_helpers.request(),audit_helpers.response())
        self.app.samples = []
        self.app.audit_rows = [replace(evidence, uid='one', profile='anyrouter'),
                               replace(evidence, uid='two', profile='官方')]
        self.app.update_choices()
        self.app.profile.set('anyrouter')
        self.app.apply_filters()
        self.assertIn('profile', self.app.table['displaycolumns'])
        self.assertEqual(self.app.table.get_children(), ('one',))
        self.assertEqual(self.app.table.set('one', 'profile'), 'anyrouter')
        with patch('desktop.filedialog.asksaveasfilename',return_value='test-output.json'), patch('desktop.export_audit') as writer:
            self.app.export()
        self.assertEqual([row.profile for row in writer.call_args.args[0]], ['anyrouter'])

    def test_official_capture_view_does_not_discover_api_account_homes(self):
        self.app.args.fixed_homes = True
        with patch('desktop.discover_homes', side_effect=AssertionError('must not scan API profiles')) as discover, \
                patch.object(self.monitor,'refresh',return_value=[]):
            self.app.request_refresh()
            kind,_,_ = self.app.mailbox.get(timeout=3)
        self.assertEqual(kind,'data')
        discover.assert_not_called()
        self.assertEqual(self.monitor.homes,[])

    def test_all_profiles_refresh_keeps_requested_user_home_and_discovers_new_logs(self):
        from pathlib import Path
        self.app.args.fixed_homes = False
        self.app.args.user_home = Path('test-user-root')
        with patch('desktop.discover_homes', return_value=[Path('new-log-home')]) as discover, \
                patch.object(self.monitor, 'refresh', return_value=[]):
            self.app.request_refresh()
            kind, _, _ = self.app.mailbox.get(timeout=3)
        self.assertEqual(kind, 'data')
        self.assertEqual(discover.call_args.kwargs['user_home'], Path('test-user-root'))
        self.assertEqual(self.monitor.homes, [Path('new-log-home')])


if __name__ == '__main__':
    unittest.main()
