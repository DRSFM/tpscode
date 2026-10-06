# Codex TPS

Codex Desktop / CLI 实际会话速度与思考等级审计工具。支持官方账号登录及中转 API 的 Codex 会话，无需在监控窗口登录或填写 API Key，不额外发起测速或模型探测请求。`tpscode` 默认启动全部 Profile 采集，普通只读监控用 `tpscode gui`。TPS 需要会话日志提供真实 token 统计；出站/回显审计需要额外的请求响应证据。

## 桌面窗口

Windows 双击 `Start-Codex-TPS.cmd`。可移动整个文件夹后使用。

安装全局命令后，可在任意目录直接输入：

```powershell
tpscode
```

它会打开全部 Profile 采集窗口并立即返回终端；已经打开时复用现有窗口，不重复改配置。关闭该窗口会恢复各 Profile 的连接配置。只读监控仍可使用 `tpscode gui`。安装或更新命令入口，在本工具目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-command.ps1
```

命令入口为 `%USERPROFILE%\.local\bin\tpscode.cmd`，旁边的 `tpscode-install.json` 记录本工具目录，`tpscode-launch.ps1` 负责使用该目录中的程序。全局命令直接使用本工具目录，不再依赖 AppData 中的安装副本。请保留整个工具文件夹；移动文件夹后，在新位置重新运行安装命令即可更新记录。仅在命令目录尚未注册时追加用户 PATH，此时需新开终端。

工具目录中的 `.\tpscode.cmd` 可直接作为便携入口使用。已安装的全局 `tpscode` 根据安装记录找到程序，支持中文和空格路径；找不到程序时会报告记录中的实际目录。

原来的 TPS 功能保留在同一个窗口。将“思考审计”下拉菜单切换为“速度统计”，即可查看历史 TPS、曲线、平均速度和 token 统计；默认加载最近 7 天，更早记录可选择“全部历史”，归档日志通过“包含已归档会话”加载。统一入口同时读取原会话日志、已保存的额外日志目录及审计文件，不删除或替换历史数据。

窗口每 2 秒增量读取日志，在模型响应完成后更新，支持客户端、模型、来源目录、时间范围与会话 ID 筛选。折线图显示最近 30 次有有效时间边界的响应；点击图上的点可定位表格。导出 CSV / JSON 包含当前筛选范围内的全部结果。

## 思考等级审计

窗口中的“速度统计”下拉菜单可切换到“思考审计”。审计表显示完成时间、客户端、Profile、请求/配置模型、出站等级、首包回显、最终回显、思考 token 和审计结果；点击一行可查看配置等级、完整关联标识、观测边界、数据来源与缺失原因。Profile 下拉菜单同时筛选表格和导出；旧审计日志没有 Profile 时显示“未记录”，不按时间猜测来源。

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

## 一次采集全部 Profiles

Windows 双击 `Start-Codex-TPS.cmd` / `Start-All-Profiles-Audit.cmd`，或直接运行：

```powershell
tpscode
```

窗口标题为“Codex TPS · 全部 Profiles 审计”。自动发现默认官方目录 `~/.codex`、默认 API 配置根目录 `~/.codex-api`（Profile 为 `default`）、`.codex-api/accounts/*` 和 `.codex-api/profiles/*`，为每个有效的 Responses 配置建立独立本机采集入口，写入同一个 `audits/profiles.jsonl`。官方、账号和 AnyRouter 等 API Profile 的记录一起显示，Profile 列区分来源，可按 Profile 筛选。运行期间每 3 秒检查新建目录；“采集状态”显示已接入和跳过的原因。

启动后完全退出并重新打开需要采集的客户端，再发送新消息。AnyRouter 仍使用原来的 `apicodex --desktop --api-profile anyrouter` 启动方式。采集窗口保持打开；已有客户端要重新加载连接配置，旧请求不能补采。Desktop / CLI 来源根据客户端发送的标识判断，缺失时显示“其他”。

接入前先验证地址、配置语义及已安装 Codex 的实际配置加载结果，只临时改连接地址；模型、思考等级和认证设置保留。无效地址、包含凭据的地址、不支持的协议或无法安全定位的配置会跳过，不打印配置原文。采集日志只保存白名单审计字段，不保存认证头或对话正文。

本机 ApiCodex 启动器已增加图片识别转接配置的兼容钩子：它重建自己的图片转接地址后，仅在本工具标记、恢复记录及本机监听均有效时保留采集入口。其他电脑若使用会重写连接地址的旧启动器，需要同样的兼容支持；“配置已修改”表示当前配置已脱离采集，工具不会静默覆盖用户修改。

关闭窗口或点击“停止并恢复配置”恢复各自原连接，保留接入期间其他配置编辑；之后再次重启客户端。异常退出时双击 `Restore-All-Profiles-Config.cmd`，或运行：

```powershell
tpscode profiles-audit --restore

# 只看 AnyRouter，也适用于审计导出
tpscode audit --audit-log '.\audits\profiles.jsonl' --profile anyrouter
```

恢复记录为 `audits/profiles-state.json`，仅含连接字段和恢复标记，不保存完整配置或密钥。统一入口不能与单独官方自动采集同时占用同一个配置；请先关闭旧采集窗口。当前本机接入 16 个有效配置，包括 `default`；此前无效地址的未登记目录已按用户要求移到回收站。第三方服务是否回显思考等级取决于其真实响应，缺少字段时显示“无法审计”。

## 官方账号桌面真实采集

Windows 双击 `Start-Official-Audit.cmd`，或运行下面的命令。窗口标题为“Codex TPS · 官方账号真实审计”。入口先在隔离目录用已安装的 Codex 加载完整候选配置，检查通过后，只在官方 `config.toml` 顶部临时添加指向本机采集器的 `openai_base_url`。原模型、思考等级、内置 provider 与登录方式保留：

```powershell
tpscode official-audit
```

该入口默认目标是 `~/.codex`，不采用当前进程的 CODEX_HOME。已有其他 profile、自定义连接、未登录官方 ChatGPT 或未通过客户端配置检查时拒绝改写。接入后需要完全退出并重新打开官方账号桌面，发送新消息，八列数据才会更新；旧消息不能补采。窗口保持打开才能继续采集。

点击“停止并恢复配置”或关闭窗口会移除本工具的临时前缀，保留原配置及用户在其后追加的编辑。停止后需要再次重启官方桌面。旧式 `profile` 接入已废弃，新入口不创建或选择 profile 文件。

已分别验证真实官方账号的 CLI 和 Desktop WebSocket 请求。用户重启桌面并发送新消息后，Desktop 捕获 gpt-6.1-sol、出站/首包/最终均为 xhigh、思考 token 2,070，判定一致；见 `validation/official-desktop-result.json`。CLI 测试另见 `validation/official-websocket-result.json`，两类证据独立记录。

异常退出后双击 `Restore-Official-Config.cmd`，或显式恢复本工具的临时配置，再重启官方桌面：

```powershell
tpscode official-audit --restore
```

恢复时保留原配置及接入期间追加的用户编辑，只移除本工具的标记和未经用户修改的临时连接字段。真实审计日志默认保存在 `audits/official-desktop.jsonl`，已从 Git 忽略；恢复连接不会删除日志。

默认官方账号的 CLI 后端和 Desktop 前端均已捕获真实请求；这不代表所有第三方中转已通过实测。接入方式依据 [OpenAI Docs 配置说明](https://developers.openai.com/codex/config-reference)。

## 可选 HTTP/SSE/WebSocket 采集入口

没有现成审计日志时，可手动启动仅监听 `127.0.0.1` 的采集入口。它转发客户端原有请求，并把白名单审计字段写入 JSONL；不额外探测模型，不读取账号配置或凭据文件，不修改 Codex 连接配置，不自动重试。

```powershell
# 将 URL 替换成你实际使用且支持 Responses HTTP/SSE 的提供商 API base URL
tpscode capture --upstream 'https://provider.example/v1' --audit-log '.\audit.jsonl' --client cli

# 在另一个终端打开监控窗口
tpscode gui --view audit --audit-log '.\audit.jsonl'
```

采集入口默认是 `http://127.0.0.1:8766/v1`。只有在客户端支持自定义 API base URL、并手动将其指向该入口时，正常请求才会被采集；启动采集器本身不会产生模型请求。身份验证头在转发过程中仅存在于内存，日志不保存 Authorization、Cookie、请求正文和回答正文。请求正文的 model、effort 和内容原样转发；传输层会使用 identity 编码请求响应，并重新处理分块传输。

支持 `/v1/responses` 的 HTTP/SSE、非流式 JSON 与 WebSocket，以及其他 `/v1/` GET/POST 的转发。WebSocket 帧原样转发，支持分片、心跳、响应 ID 与 `stream_id` 并行通道关联；`generate:false` 预热请求不计入推理审计。双方不协商可选的 WebSocket 消息压缩。

不支持 HTTP 请求体的 chunked 编码。压缩 HTTP 请求/响应均原样转发；无法解码的出站字段保持未知，不更改客户端压缩设置。缺失终态或超过捕获上限时无法给出完整审计。HTTP 请求/非流式和单个 WebSocket 消息的捕获上限为 32 MiB，单个 SSE 捕获事件上限为 1 MiB；超大流式消息仍原样转发，但不作为完整证据。

默认官方账号的 CLI 后端已通过实际请求验证，尚未覆盖所有 Desktop、官方订阅或提供商的接入路径；只有经过此入口的请求才能提供证据。SSE 也会检查帧前缀，兼容官方响应缺少 Content-Type 的情况；无效 JSON 不会被当作完整响应。采集器沿用无认证的 HTTP 系统代理或 HTTP(S)_PROXY，并保持本机和 NO_PROXY 目标直连。这里观测的是“客户端 → 提供商”边界，不能证明中转后续真正发往最终上游的参数。停止手动采集器前，应先将客户端连接地址恢复为原提供商地址。

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

普通只读模式需 Python 3.10+，默认全部 Profile 采集及官方自动接入需 Python 3.11+；正常 Windows Python 安装自带 tkinter。交付程序只用标准库，不需要 pip、模型权重或安装包。`gui` 及 audit/list/export/watch 只读日志，不需要网络连接；capture 转发手动接入的正常 API 请求，profiles-audit / official-audit 临时修改对应目录的连接配置，并在结束时恢复。程序不读取 `auth.json`、钥匙串或数据库；自动接入读取 config.toml 的连接配置，并调用客户端自己的 login status 确认官方登录，不输出或保存登录命令原文。解析时只保留统计和结构字段，不保留或导出对话正文。原会话与导入日志仍以只读模式打开，采集器只追加指定的脱敏元数据日志。

导出包含会话 ID、模型、统计数据和本地日志路径。分享导出文件时可按需要移除这些本地标识。

## 验证

```powershell
python -m unittest discover -s tests -v
python codex_tps.py diagnose
```

`tests` 使用合成日志，不包含用户对话或登录凭据。

本机运行产生的 `audits/`、`validation/`、配置恢复记录及截图不随 Git 提交；验证说明保存在 `VALIDATION.md`，仓库中的 `examples/` 只包含合成样例。
