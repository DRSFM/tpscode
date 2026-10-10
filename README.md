# Codex TPS

Codex Desktop / CLI 实际会话速度与思考等级审计工具。支持官方账号登录及中转 API 的 Codex 会话，无需在监控窗口登录或填写 API Key，不额外发起测速或模型探测请求。`tpscode` 对账号登录和所有 API Profile 统一只读会话日志，不启动转发服务、不修改请求地址。TPS 需要会话日志提供真实 token 统计；出站/回显审计需要额外的请求响应证据。

## 桌面窗口

Windows 双击 `Start-Codex-TPS.cmd`。可移动整个文件夹后使用。

安装全局命令后，可在任意目录直接输入：

```powershell
tpscode
```

它会打开日志只读统计窗口并立即返回终端；账号和 API 的配置保持原样。监控未启动或窗口关闭均不会改变 Codex 的连接。`tpscode gui` 使用同一只读模式。安装或更新命令入口，在本工具目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-command.ps1
```

命令入口为 `%USERPROFILE%\.local\bin\tpscode.cmd`，旁边的 `tpscode-install.json` 记录本工具目录，`tpscode-launch.ps1` 负责使用该目录中的程序。全局命令直接使用本工具目录，不再依赖 AppData 中的安装副本。请保留整个工具文件夹；移动文件夹后，在新位置重新运行安装命令即可更新记录。仅在命令目录尚未注册时追加用户 PATH，此时需新开终端。

工具目录中的 `.\tpscode.cmd` 可直接作为便携入口使用。已安装的全局 `tpscode` 根据安装记录找到程序，支持中文和空格路径；找不到程序时会报告记录中的实际目录。

原来的 TPS 功能保留在同一个窗口。将“思考审计”下拉菜单切换为“速度统计”，即可查看历史 TPS、曲线、平均速度和 token 统计；默认加载最近 7 天，更早记录可选择“全部历史”，归档日志通过“包含已归档会话”加载。统一入口同时读取原会话日志、已保存的额外日志目录及审计文件，不删除或替换历史数据。

窗口每 2 秒增量读取日志，在模型响应完成后更新，支持客户端、模型、来源目录、时间范围与会话 ID 筛选。折线图显示最近 30 次有有效时间边界的响应；点击图上的点可定位表格。导出 CSV / JSON 包含当前筛选范围内的全部结果。

## 思考等级审计

窗口中的“速度统计”下拉菜单可切换到“思考审计”。速度表与审计表都直接显示“思考等级（配置）”；审计表还显示完成时间、客户端、Profile、请求/配置模型、出站等级、首包回显、最终回显、思考 token 和审计结果；点击一行可查看配置等级、完整关联标识、观测边界、数据来源与缺失原因。Profile 下拉菜单同时筛选表格和导出；旧审计日志没有 Profile 时显示“未记录”，不按时间猜测来源。

两类判定分开显示：

- **配置等级变化**：比较同一会话相邻配置记录的模型和思考等级。当前会话日志就能提供，不代表服务器降低了等级，也无法区分用户手动调整和客户端自动调整。
- **回显等级差异**：比较同一次请求实际出站的请求级 `reasoning.effort` 与最终响应的对应字段；首包与最终回显变化另行记录。缺少字段、未知等级、字段冲突或关联歧义时显示无法审计。

思考 token 少不能单独证明降级，回显一致也不能验证实际模型权重或计算量。`configuration_update` 的有效等级单独保存；回显比较使用请求级参数，避免把不同语义的字段混在一起。

界面显示可比记录数、回显降低数、配置降低数与无法审计数，覆盖率 = 可比记录 / 当前筛选记录。并发和重试通过请求/尝试 ID 隔离；只有可靠的响应 ID 能唯一匹配会话记录时才关联 TPS，不按时间邻近猜测。匹配上的审计用量不会重复计入 TPS。

```powershell
# 查看当前日志中的思考等级与配置变化
tpscode audit --limit 25

# 直接打开审计视图；也可在窗口中点击“+ 审计日志”
tpscode gui --view audit --audit-log 'D:\logs\audit.jsonl'

# 筛选等级降低；参数也适用于 audit / gui / 审计导出
tpscode audit --audit-log 'D:\logs\audit.jsonl' --audit-status lowered

# 导出审计 CSV / JSON（速度统计仍是默认导出视图）
tpscode export --view audit --audit-log 'D:\logs\audit.jsonl' --format json --output '.\audit-report.json'

# 合成样例：展示降低、一致、提高和缺失；这些不是用户真实请求
.\tps.cmd gui --view audit --audit-log '.\examples\reasoning-audit.jsonl' --days 0
```

已添加的审计文件保存在工具目录的 `settings.json` 的 `audit_logs` 中。可在这个列表中移除不再使用的文件；不会删除原日志。终端也支持重复 `--audit-log` 参数，参数可指向单个 JSONL 文件或包含这些文件的目录。

## 全部账号与 API 日志只读监控

Windows 双击 `Start-Codex-TPS.cmd`、`Start-All-Profiles-Audit.cmd`、旧 `Start-Official-Audit.cmd` 或 `launch.pyw`，以及无参数运行 `tpscode`，都进入日志只读模式。默认“速度统计”同时显示 TPS、思考等级（配置）、思考 token；自动刷新间隔为 2 秒，新日志记录出现后更新。

自动发现 `~/.codex`、`~/.codex-api`、`.codex-api/accounts/*`、`.codex-api/profiles/*` 及保存的额外会话目录，持续发现新日志。ApiCodex 菜单 `[0] Account login` 内官方默认账号与独立账号、API 默认配置与命名 API Profile 均使用同样的只读统计。Profile 筛选、历史曲线与导出保留。

思考等级来自每轮会话的 `turn_context.effort` / `reasoning_effort`，不是重新读取全局配置来猜测。配置等级变化可实时观察，但不能证明实际出站参数、服务端回显或真实计算量。缺少日志字段时显示未记录；TPS 仍要求真实 token 用量与时间边界，不生成测试请求或填补未知值。

旧 `profiles-audit` 与 `official-audit` 图形入口也改为只读；`capture` 与 `--no-gui` 转发入口停用。终端持续监控使用：

```powershell
tpscode watch
```

旧采集记录和导入的审计文件保留，可通过 `--audit-log` 或界面选择只读查看。不会自动接回任何旧采集地址。仅手动恢复命令仍会改动由旧 TPS 接管的连接字段：

```powershell
tpscode profiles-audit --restore
tpscode official-audit --restore
```

本机切换只读模式时已先备份并恢复所有旧 TPS 地址、停止采集后台；其他电脑若仍有旧接入，需先恢复。已经运行的客户端可能缓存旧地址，需要彻底退出并重新打开一次。之后 TPS 未启动、已退出或自身出错均不改变客户端路由。ApiCodex 对完整旧 TPS 标记只做清理与原 API/图片运行时地址恢复，不再检查采集端口或要求恢复记录存在。

## 外部审计 JSONL 格式

外部代理可以按下列格式输出日志。每行一个完整 JSON 对象，以换行结束；监控器支持增量追加、半行等待、截断、替换与复制日志去重。当前接受 `schema_version: 1`。

```json
{"schema_version":1,"source_id":"my-relay","request_id":"req-1","attempt_id":"1","timestamp":"2026-10-06T02:00:00Z","protocol":"responses","observation_boundary":"client_to_provider","event_type":"request_sent","client":"CLI","request":{"model":"gpt-6-astra","stream":true,"reasoning":{"effort":"xhigh"}}}
{"schema_version":1,"source_id":"my-relay","request_id":"req-1","attempt_id":"1","timestamp":"2026-10-06T02:00:01Z","protocol":"responses","observation_boundary":"client_to_provider","event_type":"response_created","response":{"id":"resp-1","reasoning":{"effort":"high"}}}
{"schema_version":1,"source_id":"my-relay","request_id":"req-1","attempt_id":"1","timestamp":"2026-10-06T02:00:10Z","protocol":"responses","observation_boundary":"client_to_provider","event_type":"response_completed","response":{"id":"resp-1","reasoning":{"effort":"low"},"usage":{"output_tokens":504,"output_tokens_details":{"reasoning_tokens":404}}}}
```

- 同一次尝试必须使用一致的 `source_id`、`request_id` 和 `attempt_id`；重试使用新的 attempt ID。省略 source ID 时按文件路径隔离，不会跨文件拼接。
- `timestamp` 必须包含时区。`session_id`、`turn_id` 可选；不能唯一关联时，审计记录独立展示。
- 支持 `request_sent`、`response_created`、`response_completed`、`response_failed`、`response_incomplete`；响应事件名也接受 `response.created` 等点号形式。
- `protocol` 当前仅支持 `responses`；`observation_boundary` 支持 `client_to_provider` 和 `proxy_to_upstream`，必须按实际观测点填写。
- 思考等级读取 `reasoning.effort`，兼容 `reasoning_effort` 别名。两个字段同时存在但不一致时标记字段冲突。
- 出站请求中的 `input` 只提取 `configuration_update` 的等级，其他正文不保留。外部日志自身应脱敏，工具不会改写原文件。
- 请求和响应可以分文件提供，但完整身份与观测边界必须一致；缺失值不会覆盖已观察到的字段。
- 审计 JSON 导出包含 `schema_version`、`summary`、`records`；CSV 使用平铺字段。原速度统计导出保持原有口径，并增加上一次配置的参考字段。

参考了 [is-gpt-nerfed 的会话配置变化检测思路](https://github.com/kiyoakii/is-gpt-nerfed)；没有安装其插件或引入其探测请求。字段语义依据 [OpenAI Reasoning 文档](https://developers.openai.com/api/docs/guides/reasoning)及 [Responses 流式事件](https://developers.openai.com/api/reference/resources/responses/streaming-events)。

## 终端使用

在此目录打开 PowerShell：

已安装全局命令时，在任意目录用 `tpscode list`、`tpscode watch`、`tpscode --help`，参数与下面的 `tps.cmd` 相同。

```powershell
# 最近 7 天的最新响应
.\tps.cmd list

# 持续监控 Desktop 和 CLI；Ctrl+C 退出
.\tps.cmd watch

# 只看 CLI / Desktop
.\tps.cmd list --client cli
.\tps.cmd list --client desktop

# 筛选模型、会话、历史范围
.\tps.cmd list --model gpt --days 30 --limit 50
.\tps.cmd list --session 会话ID --days 0

# 添加其他 Codex home（可重复），或使用 sessions 目录
.\tps.cmd watch --home 'D:\CodexProfile'

# 包含已归档会话
.\tps.cmd list --archived --days 0

# 导出
.\tps.cmd export --format csv --output '.\report.csv'
.\tps.cmd export --format json --output '.\report.json'

# 检查来源、识别情况与读取提示
.\tps.cmd diagnose
```

也可直接使用 `python codex_tps.py list` / `watch` / `gui`；跨平台终端入口相同。未提供命令时默认打开桌面窗口。所有日期在界面和终端中显示为 UTC+8；JSON / CSV 的完成时间带 UTC 时区。

## TPS 口径

- **有效 TPS** = 本次响应的 `output_tokens` ÷ 从可用输入边界到最后模型输出的耗时。
- **输出 token 包含思考 token**。可见输出 = 输出 − 思考，思考统计未知时显示 `—`。
- **包含首字等待**、上下文处理、排队和网络等待；按已记录的工具调用和结果边界排除工具执行等待。
- **加权平均有效 TPS** = 有有效时间的响应输出 token 之和 ÷ 对应响应耗时之和。并发会话不会被当作一个模型的生成速度相加。
- 日志没有逐 token 到达轨迹，因此不会声称这是精确的纯生成 TPS 或实时逐 token 速度。
- 缺少时间边界、零耗时、损坏统计会显示 TPS 不可用或跳过；不按字符数猜测 token。

新版使用 `token_usage_record`，并去重对应的 `token_count`；旧版使用 `token_count` 的本次用量或安全的累计差值。CSV 的 `input_tokens` 仅供查看，**不会计入输出 TPS**。

## 日志来源

自动查找：

- 当前用户的 `.codex/sessions`；
- `CODEX_HOME` 指向的 Codex home；
- `.codex-api/sessions`；
- `.codex-api/accounts/*/sessions` 与 `.codex-api/profiles/*/sessions`。

自定义位置可在桌面窗口点击“+ 日志目录”，或用 `--home`。添加的目录只保存在本工具目录内的 `settings.json`。已归档日志需勾选或添加 `--archived`。WSL 用户可添加可访问的 `\\wsl.localhost\发行版\home\用户名\.codex` 目录。

“Desktop / CLI”根据会话日志中的 originator / source 识别；跨客户端续接同一会话时，日志可能仍保留最初客户端标签。提供商字段是日志中的 ID，不能仅凭 `openai` 判断官方直连，也不能验证中转模型身份。

**覆盖 Codex Desktop 和 Codex CLI；不覆盖 ChatGPT 网页聊天。** 当中转不返回 token usage，或客户端不保存完整的响应时间边界时，无法可靠提供 TPS。Codex 内部日志格式未来变化可能需要更新解析器。

## 环境与隐私

日志只读模式需 Python 3.10+，旧配置恢复辅助需 Python 3.11+；正常 Windows Python 安装自带 tkinter。交付程序只用标准库，不需要 pip、模型权重或安装包。所有正常监控、审计、导出入口只读日志，不启动网络监听、不发起模型请求、不读写 Codex 配置或认证文件；窗口偏好与用户主动导出另行保存。原会话与导入日志以只读模式打开，解析时只保留统计和结构字段，不保留或导出对话正文。旧的恢复子命令仅用于清理本工具先前写入的地址与标记。

导出包含会话 ID、模型、统计数据和本地日志路径。分享导出文件时可按需要移除这些本地标识。

## 验证

```powershell
python -m unittest discover -s tests -v
python codex_tps.py diagnose
```

`tests` 使用合成日志，不包含用户对话或登录凭据。

本机运行产生的 `audits/`、`validation/`、配置恢复记录及截图不随 Git 提交；验证说明保存在 `VALIDATION.md`，仓库中的 `examples/` 只包含合成样例。
