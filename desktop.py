"""Native desktop view. Tk is included with normal Windows Python installs."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from codex_tps import (APP_DIR, CONFIG_PATH, DISPLAY_TZ, Monitor, Sample, cutoff, discover_homes, export_samples,
                       load_settings, local_time, number, select_samples, summarize)
from reasoning_audit import (AUDIT_FILTERS, AuditRecord, export_audit, profile_from_home, select_audit, summarize_audit)

BG = '#10151f'
PANEL = '#19212e'
FIELD = '#121a26'
TEXT = '#ecf1f8'
MUTED = '#a4b1c3'
FAINT = '#2e3a4d'
GREEN = '#78dfb7'
BLUE = '#8cbcff'
YELLOW = '#f4cc80'
FONT = 'Microsoft YaHei UI'


def home_label(path: str) -> str:
    parts = Path(path).parts
    if 'accounts' in parts or 'profiles' in parts:
        return '/'.join(parts[-2:])
    return Path(path).name or path


class Desktop:
    def __init__(self, root: tk.Tk, monitor: Monitor, args):
        self.root, self.monitor, self.args = root, monitor, args
        self.ui_scale = max(1.0, root.winfo_fpixels('1i') / 96)
        self.samples: list[Sample] = []
        self.filtered: list[Sample] = []
        self.audit_rows: list[AuditRecord] = []
        self.audit_filtered: list[AuditRecord] = []
        self.mailbox = queue.Queue()
        self.busy = False
        self.closed = False
        self.smoked = False
        self.chart_points = []
        self.home_values = {'全部来源': ''}
        self.current_model = ''
        self.selected_uid = ''
        self.refresh_revision = 0
        self.loaded_revision = -1
        self.delay_id = None
        self.failure = ''
        self.view = tk.StringVar(value='思考审计' if args.view == 'audit' else '速度统计')
        self.audit_status = tk.StringVar(value=next(k for k, v in AUDIT_FILTERS.items() if v == args.audit_status))
        self.auto = tk.BooleanVar(value=True)
        self.archived = tk.BooleanVar(value=args.archived)
        self.client = tk.StringVar(value={'all': '全部客户端', 'desktop': 'Desktop', 'cli': 'CLI', 'other': '其他'}[args.client])
        self.model = tk.StringVar(value='全部模型')
        self.source = tk.StringVar(value='全部来源')
        self.profile = tk.StringVar(value=getattr(args, 'profile', '') or '全部 Profile')
        self.session = tk.StringVar(value=args.session)
        self.periods = {'最近24小时': 1, '最近7天': 7, '最近30天': 30, '全部历史': 0}
        if args.days not in self.periods.values():
            self.periods[f'最近{args.days:g}天'] = args.days
        self.period = tk.StringVar(value=next(k for k, v in self.periods.items() if v == args.days))
        root.title('Codex TPS · 日志只读' if getattr(args, 'readonly', False) else
                   'Codex TPS · 全部 Profiles 审计' if getattr(args, 'profiles_audit', False) else
                   'Codex TPS · 官方账号真实审计' if getattr(args, 'official_audit', False) else 'Codex TPS · Desktop / CLI')
        width = min(round(1240 * self.ui_scale), root.winfo_screenwidth() - 80)
        height = min(round(860 * self.ui_scale), root.winfo_screenheight() - 100)
        root.geometry(f'{width}x{height}+40+40')
        root.minsize(min(round(960 * self.ui_scale), width), min(round(700 * self.ui_scale), height))
        root.configure(background=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self._styles()
        self._build()
        self.request_refresh()
        root.after(100, self.poll)
        root.after(2000, self.tick)

    def _styles(self):
        self.root.option_add('*Font', (FONT, 10))
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=TEXT, font=(FONT, 10))
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=TEXT)
        style.configure('TButton', background=PANEL, foreground=TEXT, borderwidth=1,
                        bordercolor=FAINT, padding=(12, 8), focuscolor=GREEN)
        style.map('TButton', background=[('active', FAINT), ('pressed', FIELD)],
                  foreground=[('disabled', MUTED)])
        style.configure('Accent.TButton', background=GREEN, foreground=BG, bordercolor=GREEN)
        style.map('Accent.TButton', background=[('active', '#a2ebce')])
        style.configure('TCombobox', fieldbackground=FIELD, background=PANEL, foreground=TEXT,
                        arrowcolor=MUTED, bordercolor=FAINT, padding=(8, 7))
        style.map('TCombobox', fieldbackground=[('readonly', FIELD)],
                  foreground=[('readonly', TEXT)], selectbackground=[('readonly', FIELD)],
                  selectforeground=[('readonly', TEXT)])
        style.configure('TEntry', fieldbackground=FIELD, foreground=TEXT, bordercolor=FAINT,
                        insertcolor=TEXT, padding=(8, 7))
        style.configure('TCheckbutton', background=BG, foreground=MUTED,
                        indicatorbackground=FIELD, indicatorforeground=GREEN)
        style.map('TCheckbutton', background=[('active', BG)], foreground=[('active', TEXT)])
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=round(34*self.ui_scale), borderwidth=0, font=(FONT, 10))
        style.configure('Treeview.Heading', background=FIELD, foreground=MUTED,
                        padding=(8, 10), relief='flat', font=(FONT, 9))
        style.map('Treeview', background=[('selected', '#2a4053')], foreground=[('selected', TEXT)])
        style.map('Treeview.Heading', background=[('active', FAINT)])
        style.configure('Vertical.TScrollbar', background=FAINT, troughcolor=PANEL,
                        bordercolor=PANEL, arrowcolor=MUTED)
        self.root.option_add('*TCombobox*Listbox.background', FIELD)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT)
        self.root.option_add('*TCombobox*Listbox.selectBackground', FAINT)

    def label(self, parent, text, *, color=TEXT, size=10, bold=False, background=BG, **kwargs):
        return tk.Label(parent, text=text, background=background, foreground=color,
                        font=(FONT, size, 'bold' if bold else 'normal'), anchor='w', **kwargs)

    def _build(self):
        shell = ttk.Frame(self.root, padding=(24, 20, 24, 12))
        shell.pack(fill='both', expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(5, weight=1)
        top = ttk.Frame(shell)
        top.grid(row=0, column=0, sticky='ew', pady=(0, 20))
        top.columnconfigure(0, weight=1)
        self.label(top, 'Codex TPS', size=25, bold=True).grid(row=0, column=0, sticky='w')
        caption = ('账号与 API 日志只读 · 不改请求地址 · 每 2 秒刷新'
                   if getattr(self.args, 'readonly', False) else
                   '账号只读 / API 实时 · 关闭统计窗口不会停止 API 采集'
                   if getattr(self.args, 'profiles_audit', False) else
                   '官方账号审计 · 重启官方桌面后发送消息；关闭本窗口会恢复连接配置'
                   if getattr(self.args, 'official_audit', False) else '本地会话监控  /  Desktop + CLI')
        self.label(top, caption, color=MUTED).grid(row=1, column=0, sticky='w', pady=(4, 0))
        actions = ttk.Frame(top)
        actions.grid(row=0, column=1, rowspan=2)
        ttk.Checkbutton(actions, text='自动刷新 · 2 秒', variable=self.auto,
                        command=self.apply_filters).pack(side='left', padx=(0, 16))
        self.refresh_button = ttk.Button(actions, text='刷新', command=self.request_refresh)
        self.refresh_button.pack(side='left', padx=(0, 8))
        ttk.Button(actions, text='导出 CSV', command=self.export, style='Accent.TButton').pack(side='left')
        if getattr(self.args, 'official_audit', False) or getattr(self.args, 'profiles_audit', False):
            ttk.Button(actions, text='停止并恢复配置', command=getattr(self.args, 'stop_capture', self.close)).pack(side='left', padx=(8, 0))
        if getattr(self.args, 'profiles_audit', False):
            ttk.Button(actions, text='采集状态', command=self.show_capture_status).pack(side='left', padx=(8, 0))

        metrics = ttk.Frame(shell)
        metrics.grid(row=1, column=0, sticky='ew', pady=(0, 18))
        self.metric_vars = []
        self.metric_subs = []
        self.metric_labels = []
        self.metric_value_labels = []
        labels = ['最近一次有效 TPS', '加权平均有效 TPS', '已统计模型响应', '已识别会话']
        for col, text in enumerate(labels):
            metrics.columnconfigure(col, weight=1, uniform='metrics')
            panel = tk.Frame(metrics, background=PANEL, highlightbackground=FAINT, highlightthickness=1)
            panel.grid(row=0, column=col, sticky='nsew', padx=(0 if col == 0 else 6, 0 if col == 3 else 6))
            caption = self.label(panel, text, color=MUTED, size=10, background=PANEL)
            caption.pack(anchor='w', padx=16, pady=(14, 4))
            self.metric_labels.append(caption)
            value = tk.StringVar(value='—')
            self.metric_vars.append(value)
            value_label = tk.Label(panel, textvariable=value, background=PANEL, foreground=GREEN if col < 2 else TEXT,
                                   font=('Consolas', 34, 'bold'), anchor='w')
            value_label.pack(fill='x', padx=16)
            self.metric_value_labels.append(value_label)
            sub = tk.StringVar(value='正在读取会话…')
            self.metric_subs.append(sub)
            tk.Label(panel, textvariable=sub, background=PANEL, foreground=MUTED,
                     font=(FONT, 9), anchor='w').pack(fill='x', padx=16, pady=(2, 14))

        filters = ttk.Frame(shell)
        filters.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        self.client_box = ttk.Combobox(filters, textvariable=self.client,
                                      values=('全部客户端', 'Desktop', 'CLI', '其他'), state='readonly', width=12)
        self.client_box.pack(side='left', padx=(0, 8))
        self.profile_box = ttk.Combobox(filters, textvariable=self.profile, values=('全部 Profile',), state='readonly', width=17)
        self.profile_box.pack(side='left', padx=(0, 8))
        self.model_box = ttk.Combobox(filters, textvariable=self.model, values=('全部模型',), state='readonly', width=24)
        self.model_box.pack(side='left', padx=(0, 8))
        self.source_box = ttk.Combobox(filters, textvariable=self.source, values=('全部来源',), state='readonly', width=17)
        self.source_box.pack(side='left', padx=(0, 8))
        self.period_box = ttk.Combobox(filters, textvariable=self.period, values=tuple(self.periods), state='readonly', width=11)
        self.period_box.pack(side='left', padx=(0, 8))
        for box in (self.client_box, self.profile_box, self.model_box, self.source_box):
            box.bind('<<ComboboxSelected>>', lambda _: self.apply_filters())
        self.period_box.bind('<<ComboboxSelected>>', self.scope_changed)
        ttk.Button(filters, text='+ 日志目录', command=self.add_home).pack(side='right')

        options = ttk.Frame(shell)
        options.grid(row=3, column=0, sticky='ew', pady=(0, 12))
        self.label(options, '会话 ID', color=MUTED, size=9).pack(side='left', padx=(0, 8))
        ttk.Entry(options, textvariable=self.session, width=24).pack(side='left')
        self.session.trace_add('write', self.filter_changed)
        ttk.Checkbutton(options, text='包含已归档会话', variable=self.archived,
                        command=self.scope_changed).pack(side='left', padx=16)
        self.view_box = ttk.Combobox(options, textvariable=self.view, values=('速度统计', '思考审计'),
                                     state='readonly', width=10)
        self.view_box.pack(side='left', padx=(0, 8))
        self.view_box.bind('<<ComboboxSelected>>', lambda _: self.apply_filters())
        self.audit_status_box = ttk.Combobox(options, textvariable=self.audit_status,
                                             values=tuple(AUDIT_FILTERS), state='readonly', width=17)
        self.audit_status_box.pack(side='left', padx=(0, 8))
        self.audit_status_box.bind('<<ComboboxSelected>>', lambda _: self.apply_filters())
        ttk.Button(options, text='+ 审计日志', command=self.add_audit_log).pack(side='right')

        plot_panel = tk.Frame(shell, background=PANEL, highlightbackground=FAINT, highlightthickness=1)
        self.plot_panel = plot_panel
        plot_panel.grid(row=4, column=0, sticky='ew', pady=(0, 14))
        plot_header = tk.Frame(plot_panel, background=PANEL)
        plot_header.pack(fill='x', padx=16, pady=(12, 0))
        self.label(plot_header, '最近响应的速度变化', background=PANEL, bold=True).pack(side='left')
        self.label(plot_header, '总输出 TPS', color=GREEN, size=9, background=PANEL).pack(side='right', padx=(12, 0))
        self.label(plot_header, '可见输出 TPS', color=BLUE, size=9, background=PANEL).pack(side='right')
        self.canvas = tk.Canvas(plot_panel, height=round(156*self.ui_scale), background=PANEL, highlightthickness=0)
        self.canvas.pack(fill='x', padx=8, pady=(4, 6))
        self.canvas.bind('<Configure>', lambda _: self.draw_chart())
        self.canvas.bind('<Motion>', self.chart_hover)
        self.canvas.bind('<Leave>', lambda _: self.chart_hint.configure(text='包含思考与首字等待；工具耗时按日志边界剔除。'))
        self.canvas.bind('<Button-1>', self.chart_click)
        self.chart_hint = self.label(plot_panel, '包含思考与首字等待；工具耗时按日志边界剔除。',
                                     color=MUTED, size=9, background=PANEL)
        self.chart_hint.pack(fill='x', padx=16, pady=(0, 12))

        table_frame = ttk.Frame(shell)
        table_frame.grid(row=5, column=0, sticky='nsew')
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.speed_columns = ('time', 'client', 'profile', 'model', 'effort', 'tps', 'visible', 'output', 'reasoning', 'duration', 'session')
        self.audit_columns = ('time', 'client', 'profile', 'model', 'effort', 'outbound', 'first', 'final', 'reasoning', 'audit')
        columns = self.speed_columns + ('outbound', 'first', 'final', 'audit')
        self.table = ttk.Treeview(table_frame, columns=columns, show='headings', selectmode='browse', height=7)
        titles = ('完成时间', '客户端', 'Profile', '模型', '思考等级（配置）', '有效 TPS', '可见 TPS', '输出 token', '思考 token', '耗时 / 秒', '会话 ID')
        widths = (122, 88, 110, 195, 130, 86, 86, 85, 85, 86, 126)
        for column, title, width in zip(self.speed_columns, titles, widths):
            self.table.heading(column, text=title)
            self.table.column(column, width=round(width*self.ui_scale), minwidth=round(58*self.ui_scale), anchor='w' if column in ('time', 'client', 'profile', 'model', 'session') else 'e',
                              stretch=column == 'model')
        self.table.tag_configure('even', background=PANEL)
        self.table.tag_configure('odd', background='#1d2735')
        for column, title, width in (('outbound','出站等级',95), ('first','首包回显',95),
                                      ('final','最终回显',95), ('audit','审计结果',320)):
            self.table.heading(column, text=title)
            self.table.column(column, width=round(width*self.ui_scale), minwidth=round(70*self.ui_scale),
                              anchor='w', stretch=column == 'audit')
        for tag, color in (('lowered','#ffc3c3'), ('config_lowered',YELLOW), ('raised',BLUE),
                           ('match',GREEN), ('changed',YELLOW), ('unknown',MUTED),
                           ('failed','#ffc3c3'), ('incomplete',YELLOW), ('in_progress',BLUE)):
            self.table.tag_configure(tag, foreground=color)
        self.table.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.table.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.table.bind('<<TreeviewSelect>>', self.select_row)
        self.empty_label = self.label(table_frame, '正在读取本地日志…', color=MUTED, background=PANEL)
        self.empty_label.place(relx=.5, rely=.35, anchor='center')

        bottom = ttk.Frame(shell)
        bottom.grid(row=6, column=0, sticky='ew', pady=(12, 0))
        self.status = self.label(bottom, '正在扫描会话目录…', color=MUTED, size=9)
        self.status.pack(side='left')
        self.label(bottom, '只读日志 · 配置变化与回显分开判断', color=MUTED, size=9).pack(side='right')
        self.detail = self.label(shell, '选择一条响应，可查看完整会话 ID 和来源目录。', color=MUTED, size=9,
                                 wraplength=round(1150*self.ui_scale), justify='left')
        self.detail.grid(row=7, column=0, sticky='ew', pady=(8, 0))

    def scope_changed(self, _=None):
        self.refresh_revision += 1
        self.request_refresh()

    def filter_changed(self, *_):
        if self.delay_id:
            self.root.after_cancel(self.delay_id)
        self.delay_id = self.root.after(200, self.apply_filters)

    def request_refresh(self):
        if self.busy or self.closed:
            return
        self.busy = True
        self.refresh_button.configure(state='disabled')
        period = self.periods[self.period.get()]
        archive = self.archived.get()
        revision = self.refresh_revision

        def worker():
            try:
                self.monitor.include_archived = archive
                if not getattr(self.args, 'fixed_homes', False):
                    self.monitor.homes = discover_homes(user_home=getattr(self.args, 'user_home', None), extra=self.monitor.homes)
                data = self.monitor.refresh(cutoff(period))
                self.mailbox.put(('data', (data, self.monitor.audit_rows), revision))
            except Exception as exc:
                self.mailbox.put(('error', f'{type(exc).__name__}: {exc}', revision))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            kind, payload, revision = self.mailbox.get_nowait()
            self.busy = False
            self.refresh_button.configure(state='normal')
            self.loaded_revision = revision
            if kind == 'data' and revision == self.refresh_revision:
                self.failure = ''
                self.samples, self.audit_rows = payload
                self.update_choices()
                self.apply_filters()
                if self.args.smoke_report and not self.smoked:
                    self.smoked = True
                    self.root.after(500, self.smoke)
            elif kind == 'error':
                self.failure = payload
                self.status.configure(text=f'读取失败，可点击刷新重试：{payload}', foreground=YELLOW)
                self.empty_label.configure(text='读取失败。请检查日志目录后点击刷新。')
            if revision != self.refresh_revision:
                self.request_refresh()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def tick(self):
        if self.closed:
            return
        if getattr(self.args, 'capture_stopped', None) and self.args.capture_stopped():
            self.close()
            return
        if self.auto.get():
            self.request_refresh()
        self.root.after(2000, self.tick)

    def update_choices(self):
        names = {r.profile or '未记录' for r in self.audit_rows} | {profile_from_home(s.home) or '未记录' for s in self.samples}
        names.update(getattr(self.args, 'profile_names', []))
        self.profile_box.configure(values=['全部 Profile'] + sorted(names))
        if self.profile.get() not in ['全部 Profile'] + sorted(names):
            self.profile.set('全部 Profile')
        models = sorted({s.model for s in self.samples} | {r.model for r in self.audit_rows})
        self.model_box.configure(values=['全部模型'] + models)
        if self.args.model and self.model.get() == '全部模型':
            match = next((m for m in models if self.args.model.lower() in m.lower()), None)
            if match:
                self.model.set(match)
            self.args.model = ''
        if self.model.get() not in ['全部模型'] + models:
            self.model.set('全部模型')
        self.home_values = {'全部来源': ''}
        for home in sorted({s.home for s in self.samples} | {r.home for r in self.audit_rows}):
            label = home_label(home)
            if label in self.home_values:
                label = home
            self.home_values[label] = home
        self.source_box.configure(values=list(self.home_values))
        if self.source.get() not in self.home_values:
            self.source.set('全部来源')

    def apply_filters(self):
        self.delay_id = None
        client = {'全部客户端': 'all', 'Desktop': 'desktop', 'CLI': 'cli', '其他': 'other'}[self.client.get()]
        model = '' if self.model.get() == '全部模型' else self.model.get()
        profile = '' if self.profile.get() == '全部 Profile' else self.profile.get()
        candidates = [s for s in self.samples if not profile or (profile_from_home(s.home) or '未记录') == profile]
        self.filtered = select_samples(candidates, client, model, self.session.get().strip(),
                                       self.home_values.get(self.source.get(), ''))
        self.audit_filtered = select_audit(self.audit_rows, client, model, self.session.get().strip(),
                                           self.home_values.get(self.source.get(), ''),
                                           AUDIT_FILTERS[self.audit_status.get()], profile)
        auditing = self.view.get() == '思考审计'
        self.audit_status_box.configure(state='readonly' if auditing else 'disabled')
        self.table.configure(displaycolumns=self.audit_columns if auditing else self.speed_columns)
        self.table.heading('model', text='请求 / 配置模型' if auditing else '模型')
        if auditing:
            self.plot_panel.grid_remove()
        else:
            self.plot_panel.grid()
        summary = summarize(self.filtered)
        latest = self.filtered[0] if self.filtered else None
        values = [number(summary['latest_tps']), number(summary['weighted_tps']),
                  f'{summary["sample_count"]:,}', str(summary['session_count'])]
        subtitles = [f'{latest.client} · {local_time(latest.completed_at)}' if latest else '等待模型响应完成',
                     f'{summary["timed_count"]:,} 次有有效时间边界 · tokens/s',
                     f'共 {summary["output_tokens"]:,} 个输出 token',
                     f'已扫描 {self.monitor.file_count} 个日志文件']
        titles = ['最近一次有效 TPS', '加权平均有效 TPS', '已统计模型响应', '已识别会话']
        if auditing:
            audit_summary = summarize_audit(self.audit_filtered)
            values = [f'{audit_summary["comparable_count"]:,}', f'{audit_summary["lowered_count"]:,}',
                      f'{audit_summary["config_lowered_count"]:,}', f'{audit_summary["unknown_count"]:,}']
            coverage = audit_summary['coverage']
            titles = ['可比审计记录', '回显等级降低', '配置等级降低', '无法审计']
            subtitles = [f'共 {len(self.audit_filtered):,} 条 · 覆盖率 {coverage:.0%}' if coverage is not None else '等待日志',
                         '实际出站与最终回显的字段差异', '本地配置变化 · 原因无法判断',
                         f'{audit_summary["changed_count"]:,} 条首末回显变化']
        for label, title in zip(self.metric_labels, titles):
            label.configure(text=title)
        colors = (GREEN, '#ffb4b4', YELLOW, MUTED) if auditing else (GREEN, GREEN, TEXT, TEXT)
        for label, color in zip(self.metric_value_labels, colors):
            label.configure(foreground=color)
        for var, value, sub, text in zip(self.metric_vars, values, self.metric_subs, subtitles):
            var.set(value)
            sub.set(text)
        displayed = self.audit_filtered if auditing else self.filtered
        signature = (auditing, tuple(json.dumps(s.to_dict() if auditing else asdict(s), sort_keys=True,
                                                ensure_ascii=False) for s in displayed[:300]))
        if signature != getattr(self, 'table_signature', None):
            selected = self.table.selection()
            y = self.table.yview()[0]
            self.table.delete(*self.table.get_children())
            for i, s in enumerate(displayed[:300]):
                tags = ['even' if i % 2 == 0 else 'odd']
                if auditing:
                    data = dict(time=local_time(s.completed_at), client=s.client, profile=s.profile or '未记录', model=s.model,
                                effort=s.configured_effort or '未记录',
                                outbound=s.outbound_effort or '未采集', first=s.first_display,
                                final=s.final_effort or '未返回', reasoning=number(s.reasoning_tokens, 0),
                                audit='  ' + s.audit_result)
                    row = tuple(data.get(column, '') for column in self.table['columns'])
                    tags.append('changed' if s.audit_status == 'match' and s.first_final_change else s.audit_status)
                else:
                    row = (local_time(s.completed_at), s.client, profile_from_home(s.home) or '未记录', s.model, s.effort, number(s.effective_tps),
                       number(s.visible_tps), f'{s.output_tokens:,}',
                       f'{s.reasoning_tokens:,}' if s.reasoning_tokens is not None else '—',
                       number(s.duration_seconds), s.session_id[:12]) + ('', '', '', '')
                self.table.insert('', 'end', iid=s.uid, values=row, tags=tuple(tags))
            self.table_signature = signature
            if selected and self.table.exists(selected[0]):
                self.table.selection_set(selected[0])
            self.table.yview_moveto(y)
        if displayed:
            self.empty_label.place_forget()
        else:
            self.empty_label.configure(text='没有匹配的记录。可调整筛选，或添加会话 / 审计日志。')
            self.empty_label.place(relx=.5, rely=.35, anchor='center')
        warnings = len(self.monitor.errors) + self.monitor.bad_lines
        status = f'监控中 · 每 2 秒刷新' if self.auto.get() else '自动刷新已暂停'
        status += f'  |  展示最近 {min(300, len(displayed))} 条，导出包含全部'
        if getattr(self.args, 'capture_status', None):
            targets = self.args.capture_status()
            self.args.profile_names = [item['profile'] for item in targets]
            status += f'  |  {sum(item["state"] == "采集中" for item in targets)} 个 Profile 采集中'
        if warnings:
            status += f'  |  {warnings} 条读取提示（详见 CLI diagnose）'
        self.status.configure(text=status, foreground=MUTED if not warnings else YELLOW)
        self.draw_chart()
        if self.table.selection():
            self.select_row()
        elif auditing:
            self.detail.configure(text='配置等级来自会话日志；出站、首包和最终回显需要审计日志。回显差异不证明实际计算量或模型身份。')
        else:
            self.detail.configure(text='选择一条响应，可查看完整会话 ID 和来源目录。')

    def draw_chart(self):
        c = self.canvas
        c.delete('all')
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 150)
        points = list(reversed([s for s in self.filtered if s.effective_tps is not None][:30]))
        self.chart_points = []
        if not points:
            c.create_text(w/2, h/2, text='有时间边界的模型响应完成后，速度曲线会显示在这里。', fill=MUTED, font=(FONT, 10))
            return
        left, right, top, bottom = 54, w-24, 14, h-30
        peak = max(s.effective_tps for s in points)
        ymax = max(10, math.ceil(peak/10)*10)
        for fraction in (0, .5, 1):
            y = bottom-(bottom-top)*fraction
            c.create_line(left, y, right, y, fill=FAINT, dash=(3, 5))
            c.create_text(left-10, y, text=f'{ymax*fraction:g}', fill=MUTED, anchor='e', font=('Consolas', 9))
        c.create_text(left-10, top-8, text='t/s', fill=MUTED, anchor='e', font=('Consolas', 8))
        total_coords = []
        visible_coords = []
        for i, s in enumerate(points):
            x = (left+right)/2 if len(points) == 1 else left+(right-left)*i/(len(points)-1)
            y = bottom-(bottom-top)*s.effective_tps/ymax
            total_coords.extend((x, y))
            if s.visible_tps is not None:
                visible_coords.append((x, bottom-(bottom-top)*s.visible_tps/ymax))
            self.chart_points.append((x, y, s))
        if len(points) > 1:
            c.create_polygon(left, bottom, *total_coords, right, bottom, fill='#213d36', outline='')
            c.create_line(*total_coords, fill=GREEN, width=2)
        for x, y in visible_coords:
            c.create_line(x, bottom, x, y, fill='#344e6a', width=3)
            c.create_oval(x-2, y-2, x+2, y+2, fill=BLUE, outline=BLUE)
        for x, y, s in self.chart_points:
            radius = 4 if s.uid == self.selected_uid else 2.5
            c.create_oval(x-radius, y-radius, x+radius, y+radius, fill=GREEN, outline=GREEN)
        c.create_text(left, h-12, text=local_time(points[0].completed_at), fill=MUTED, anchor='w', font=(FONT, 8))
        c.create_text(right, h-12, text=local_time(points[-1].completed_at), fill=MUTED, anchor='e', font=(FONT, 8))

    def nearest_point(self, x):
        return min(self.chart_points, key=lambda p: abs(p[0]-x)) if self.chart_points else None

    def chart_hover(self, event):
        point = self.nearest_point(event.x)
        if point:
            s = point[2]
            self.chart_hint.configure(text=f'{local_time(s.completed_at)}  ·  {s.client}  ·  {s.model}  ·  '
                                      f'{number(s.effective_tps)} TPS  ·  {s.output_tokens:,} 输出 token  ·  点击查看')

    def chart_click(self, event):
        point = self.nearest_point(event.x)
        if point and self.table.exists(point[2].uid):
            self.table.selection_set(point[2].uid)
            self.table.see(point[2].uid)

    def select_row(self, _=None):
        selection = self.table.selection()
        if not selection:
            return
        self.selected_uid = selection[0]
        if self.view.get() == '思考审计':
            r = next((r for r in self.audit_filtered if r.uid == selection[0]), None)
            if r:
                self.detail.configure(text=f'会话 {r.session_id or "未关联"}  ·  请求 {r.request_id or "未采集"} / 尝试 {r.attempt_id or "—"}  ·  响应 {r.response_id or "未采集"}\n'
                    f'Profile {r.profile or "未记录"}  ·  配置 {r.configured_effort or "未记录"}  ·  出站 {r.outbound_effort or "未采集"}  ·  首包 {r.first_display}  ·  最终 {r.final_effort or "未返回"}  ·  有效配置更新 {r.effective_effort or "未记录"}\n'
                    f'模型依据 {"实际请求" if r.model_origin == "request" else "会话配置"}  ·  观测边界 {r.observation_boundary or "未采集"}  ·  首末变化 {r.first_final_change or "无已知变化"}  ·  {r.audit_result}\n'
                    f'{r.note}\n来源：{r.source_path}')
            return
        s = next((s for s in self.filtered if s.uid == selection[0]), None)
        if s:
            self.detail.configure(text=f'会话 {s.session_id}  ·  提供商 ID: {s.provider}  ·  '
                                  f'来源: {s.home}\n{s.timing_note}')
            self.draw_chart()

    def show_capture_status(self):
        rows = self.args.capture_status()
        text = '\n'.join(f'{row["profile"]}：{row["state"]}' + (f' · {row["reason"]}' if row.get('reason') else '') for row in rows)
        messagebox.showinfo('Profiles 采集状态', text or '没有发现可接入的 Profile。', parent=self.root)

    def add_home(self):
        selected = filedialog.askdirectory(parent=self.root, title='选择 Codex home 或 sessions 日志目录')
        if not selected:
            return
        path = Path(selected).resolve()
        if not (path/'sessions').is_dir() and path.name not in ('sessions', 'archived_sessions'):
            messagebox.showinfo('未找到日志', '请选择含 sessions 子目录的 Codex home，或 sessions 目录本身。', parent=self.root)
            return
        settings = load_settings()
        extra = settings.get('extra_homes', [])
        if str(path) not in extra:
            extra.append(str(path))
        settings['extra_homes'] = extra
        try:
            temp = CONFIG_PATH.with_suffix('.tmp')
            temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(CONFIG_PATH)
        except OSError as exc:
            messagebox.showerror('保存失败', str(exc), parent=self.root)
            return
        self.monitor.homes = discover_homes(extra=self.monitor.homes+[path])
        self.scope_changed()

    def export(self):
        auditing = self.view.get() == '思考审计'
        path = filedialog.asksaveasfilename(parent=self.root, title='导出筛选后的全部响应',
            initialdir=str(APP_DIR), initialfile=f'codex-{"audit" if auditing else "tps"}-{datetime.now(DISPLAY_TZ).strftime("%Y%m%d-%H%M%S")}.csv',
            defaultextension='.csv', filetypes=[('CSV 表格', '*.csv'), ('JSON 数据', '*.json')])
        if not path:
            return
        try:
            rows = self.audit_filtered if auditing else self.filtered
            writer = export_audit if auditing else export_samples
            writer(rows, Path(path), 'json' if path.lower().endswith('.json') else 'csv', overwrite=True)
            self.status.configure(text=f'已导出 {len(rows)} 条 → {Path(path).name}', foreground=GREEN)
        except OSError as exc:
            messagebox.showerror('导出失败', str(exc), parent=self.root)

    def add_audit_log(self):
        selected = filedialog.askopenfilename(parent=self.root, title='选择审计 JSONL 文件',
                                              filetypes=[('审计 JSONL', '*.jsonl')])
        if not selected:
            return
        path = Path(selected).resolve()
        settings = load_settings()
        logs = settings.get('audit_logs', [])
        logs = logs if isinstance(logs, list) else []
        logs = [p for p in logs if isinstance(p, str)]
        if str(path) not in logs:
            logs.append(str(path))
        settings['audit_logs'] = logs
        try:
            temp = CONFIG_PATH.with_suffix('.tmp')
            temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(CONFIG_PATH)
        except OSError as exc:
            messagebox.showerror('保存失败', str(exc), parent=self.root)
            return
        if path not in self.monitor.audit_monitor.paths:
            self.monitor.audit_monitor.paths.append(path)
        self.view.set('思考审计')
        self.scope_changed()

    def smoke(self):
        # Only our own widgets are exercised; no external application is touched.
        self.auto.set(False)
        result = {'loaded': len(self.samples), 'clients': sorted({s.client for s in self.samples}), 'error': self.failure}
        original = self.client.get()
        counts = {}
        for client in ('Desktop', 'CLI'):
            self.client.set(client)
            self.apply_filters()
            counts[client] = len(self.filtered)
            assert all(s.client == client for s in self.filtered)
        self.client.set(original)
        self.apply_filters()
        displayed = self.audit_filtered if self.view.get() == '思考审计' else self.filtered
        if displayed:
            self.table.selection_set(displayed[0].uid)
            self.select_row()
            assert displayed[0].session_id in self.detail.cget('text')
        result['filter_counts'] = counts
        result['table_rows'] = len(self.table.get_children())
        result['chart_points'] = len(self.chart_points)
        result['view'] = self.view.get()
        result['audit_summary'] = summarize_audit(self.audit_filtered)
        self.root.update_idletasks()
        result['window_size'] = [self.root.winfo_width(), self.root.winfo_height()]
        result['table_height'] = self.table.winfo_height()
        assert self.table.winfo_height() >= 100, '响应表格没有足够的可见空间'
        if self.args.screenshot:
            from PIL import ImageGrab  # QA only; never required by the delivered app.
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.update()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            self.args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab(bbox=(x, y, x+self.root.winfo_width(), y+self.root.winfo_height())).save(self.args.screenshot)
            self.root.attributes('-topmost', False)
            result['screenshot'] = str(self.args.screenshot)
        self.args.smoke_report.parent.mkdir(parents=True, exist_ok=True)
        self.args.smoke_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        self.root.after(200, self.close)

    def close(self):
        self.closed = True
        self.root.destroy()


def run_gui(monitor: Monitor, args) -> int:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f'桌面窗口不可用：{exc}。仍可使用 list / watch / export 命令。')
        return 1
    Desktop(root, monitor, args)
    root.mainloop()
    return 0
