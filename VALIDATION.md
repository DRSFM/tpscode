# 验证记录

2026-10-03，Windows / Asia-Hong-Kong。

| 检查 | 结果 |
| --- | --- |
| Python 3.13.5 / Python 3.14 核心测试 | 两个环境均 21 项通过 |
| Windows `py -3` / Python 3.14 终端入口 | Desktop / CLI 查询成功 |
| 真实日志识别 | 同时识别 Desktop 与 CLI，多账号目录自动发现 |
| 本地统计 | 当时读取近 7 天 16 个日志文件、12 个会话、超过 500 次模型响应，读取错误为 0 |
| 原生 GUI | 在 3840×2160 高 DPI 屏幕下打开，表格可见；模型、客户端筛选与图表定位通过 |
| 持续读取 | 已验证部分写入、增量追加、日志截断、替换、重复记录去重 |
| CSV / JSON | 合成数据往返验证成功；未导出对话正文；CLI 默认拒绝覆盖已有文件 |
| 依赖 | Python 标准库；未下载或安装包、模型或数据集 |

执行命令：

```powershell
python -m unittest discover -s outputs/codex-tps/tests -v
.\outputs\codex-tps\tps.cmd list --client desktop --limit 3
.\outputs\codex-tps\tps.cmd list --client cli --limit 3
python outputs/codex-tps/codex_tps.py watch --client cli --interval 0.1 --count 2
```

GUI 在本工具自己的控件上做了加载、客户端筛选、选中行和图表检查，并渲染截图核对布局。截图工具仅用于开发验证，交付应用不依赖 Pillow。

限制：TPS 的分子来自日志记录的真实 token 数，耗时来自日志边界推算；不是纯解码速度，也不是逐 token 流速。未在 Linux、macOS 或 WSL 下实机验证。Codex 的内部日志格式变化时可能需要更新解析器。

## 2026-10-04 命令入口

增加全局 `tpscode` 命令。无参数打开窗口；`list`、`watch`、`--help` 等参数透传给终端入口。应用副本位于 `%LOCALAPPDATA%\CodexTPS\app`，命令位于已加入用户 PATH 的 `%USERPROFILE%\.local\bin`。

安装器在 Windows PowerShell 下完成安装与重复更新；更新文件采用临时写入加原子替换。检查安装副本与源文件一致，并从 `C:\Windows\Temp` 验证命令发现、客户端查询、错误退出码和窗口启动。

### 命令路径修复

用户报告在工具目录执行 `tpscode watch` 提示未安装。当前执行环境未直接复现该终端状态，但将子进程的 `LOCALAPPDATA` 指向无效目录后，复现了相同错误：旧入口只依赖这一环境变量。

入口改为按自身位置发现程序，本地入口优先使用相邻程序，全局入口优先使用相对位置的安装副本；环境变量路径作为备用。已更新安装入口，并在用户提供的同一工作目录实测 `tpscode watch --count 1 --interval 0.1` 和便携入口成功。

新增 4 项 Windows 入口测试（包含子场景）：中文及空格路径、无参数打开桌面、全局入口环境变量错误或缺失、程序不存在时列出检查路径。连同原有测试共 25 项通过。
# 全局入口与用户终端验证修正

- 用户在 PowerShell 7.6.6 中再次执行全局 `tpscode list` 失败；用户执行 `Test-Path "$env:LOCALAPPDATA\CodexTPS\app\codex_tps.py"` 返回 False，而 `.\tpscode.cmd list --limit 1` 成功。确认用户终端看不到旧安装副本，但工具目录可用。
- Codex 内和使用 Windows 登录环境启动的子进程能看到旧 AppData 文件，这不能证明用户已打开的终端也能看到它。先前将此类测试当作用户环境通过依据不充分，不能把 LOCALAPPDATA 的值认定为根因。
- 用合成目录复现“源程序存在、AppData 副本缺失”时旧全局入口退出 1。
- 全局入口改为通过 `.local/bin/tpscode-install.json` 记录的工具目录启动；PowerShell 读取 UTF-8 配置，保留参数和退出码。本地便携入口与测速代码未改动。
- 28 项测试通过，新增覆盖 AppData 缺失但源目录有效、中文和空格目录及参数、桌面启动、源目录移动后准确报错。
- 全局命令依赖当前工具目录；移动后必须从新目录重新运行安装器。AppData 中旧文件保留，没有删除。


补充验证：使用 CreateEnvironmentBlock(inherit=false) 建立 Windows 登录环境，启动系统安装的 PowerShell 7.6.6，移除 Codex 注入的环境；在原工具目录及 C:\Windows\Temp 执行 list，并执行 watch / --help，4 项均退出 0。此结果作为辅助验证，用户原终端的实际结果需单独确认。

最终验收：用户在原来报错的 PowerShell 7.6.6 窗口执行全局 tpscode list --limit 1，成功显示 TPS 和会话汇总（574 次响应 / 12 个会话）。已取得用户实际终端的成功输出，入口修复完成。

## 2026-10-06 思考等级审计

| 检查 | 结果与证据 |
| --- | --- |
| 改动前基线 | 原有 28 项 unittest 全部通过 |
| 改动后完整测试 | `python -m unittest discover -s tests -v`：50 项通过，无跳过；新增 22 项审计、采集与原生 GUI 测试 |
| 语法与差异检查 | `python -m py_compile codex_tps.py reasoning_audit.py audit_capture.py desktop.py`、`git diff --check` 通过 |
| 审计判定 | 覆盖出站/首包/最终、降低/提高/一致、未知等级、缺失/零 token、字段冲突、配置更新、失败与不完整响应 |
| 配置变化 | 覆盖相邻配置等级降低；下一轮保持同等级时不会重复沿用上一轮的降低判定；提示无法区分用户调整与自动调整 |
| 数据读取及关联 | 覆盖部分写入、追加、截断、复制去重、跨文件合并、乱序和重复、尝试隔离、严格响应 ID 关联、关联歧义及不重复计入 TPS |
| HTTP/SSE 采集 | 使用本机临时模拟服务验证；请求正文与验证头可正常透传、首包不等待最终响应、CRLF/分段 SSE、非流式、HTTP 503、缺少终态、并发写入与隐私白名单均通过 |
| 原生 GUI 行为 | 实际 tkinter 控件验证视图切换、审计筛选、仅外部日志展示、相同 uid 的后到字段刷新、选中详情与导出范围 |
| 界面视觉检查 | 2168×1504 高 DPI 窗口中查看八列和详情，表格高度 765 px；6 条明确标识的合成记录，5 条可比、2 条降低、1 条未知；见 `validation/audit-view.png` 与 `audit-smoke.json` |
| 本地会话兼容 | GUI 读取 18,853 条已有会话响应，无读取错误；同屏审计数据包含合成样例，此检查不代表真实上游回显采集成功；见 `validation/local-log-smoke.json` |
| 真实命令入口 | 全局 `tpscode audit --json --limit 1`、原有 `list --json --limit 1` 和合成审计 lowered 筛选均退出 0；见 `validation/cli-smoke.json` |
| 依赖与账号操作 | 交付程序只用 Python 标准库；未下载包/模型/数据集，未读取凭据文件或修改 Codex 连接配置；截图 QA 使用已有 Pillow |

尚未验证：实际提供商的端到端转发、所有 Desktop/官方订阅的接入方式。WebSocket 与 chunked 请求体明确未支持，不计为已验证路径。采集器只在手动启动且客户端手动接入后转发请求；没有运行任何真实模型探测。

## 2026-10-06 真实官方账号后续验证

本节为用户要求真实官方桌面测试后的新检查点，上节的“未修改连接、未发起真实请求”只描述前一阶段。

| 检查 | 结果 |
| --- | --- |
| 官方账号确认 | 默认 ~/.codex 的 login status 确认为 ChatGPT 登录；测试子进程明确使用此目录，未使用当前 .codex-api/accounts/wup24 |
| 真实后端请求 | 官方账号 CLI 后端实际请求完成，捕获模型 gpt-6.1-sol、出站 xhigh、首包 xhigh、最终 xhigh、思考 tokens 0，判定一致；validation/official-fixed-result.json |
| 真实响应发现 | 此次官方 /responses 缺少 Content-Type；旧采集器漏掉 SSE 字段。已增加帧前缀识别与回归测试，无效非流式 JSON 改为未完整结束 |
| 网络连接 | 采集器使用现有 HTTP 系统代理进行 HTTPS CONNECT，保持来源 TLS 校验与本机/NO_PROXY 直连；不输出或保存验证头 |
| 官方桌面入口 | 新增 official-audit，临时 profile 保留原模型/effort/内置 provider，关闭恢复；已有 profile、自定义连接和非官方登录拒绝自动改写 |
| 恢复机制 | 覆盖原始字节、BOM、用户追加编辑、异常恢复、用户修改临时文件后保留、写入失败清理、重复实例保护；未删除任何用户原文件 |
| 完整测试 | python -m unittest discover -s tests -v：65 项通过，无跳过；语法与 git diff --check 通过 |
| 桌面前端状态 | 已打开官方审计窗口并临时接入默认 .codex，等待用户重启官方桌面发送新消息；尚不算桌面端到端验收完成 |

WebSocket 仍未支持。实际内置客户端先出现 501 与重连，随后回退到 HTTP/SSE 并成功完成；首次连接可能明显延迟。真实捕获日志已从 Git 忽略，保存的验证结果只含审计元数据，不含对话或凭据。

### 官方桌面配置错误与恢复

用户实际桌面提示 legacy profile 不再支持，证实 config.toml 中加入 profile 选择不适用于此版本。此前 TOML 语法测试没有验证客户端兼容性，此检查点替代上文“等待桌面验收”的运行状态。

- 已从默认 .codex/config.toml 移除本工具添加的完整前缀，临时 profile 文件已移除，自建监控进程已停止。
- 默认官方目录实际执行 Codex features list 返回 0，profile 标记/旧键均不存在，模型/思考等级为原 gpt-6.1-sol/xhigh。
- 在完全隔离的临时目录复现 legacy profile 被真实配置加载器拒绝，未再次改写官方配置。
- 自动入口新增实际客户端兼容预检查：当前运行 official-audit 返回 1，报告兼容性错误，官方配置前后字节完全一致。
- 官方桌面自动接入仍未完成；应使用其支持的启动方式，不能继续把旧字段写入现有配置。

## 2026-10-06 WebSocket 与官方接入修复（最新检查点）

| 检查 | 结果 |
| --- | --- |
| 修复前基线 | 66 项测试通过；新增真实 socket 测试复现 WebSocket 501 |
| 完整测试 | `python -m unittest discover -s tests -v`：78 项通过，无跳过，17.357 秒；包含窗口启动入口正确传递 official-audit 的回归检查 |
| WebSocket | 实际本机 socket 覆盖握手后已缓冲帧、分片/心跳、原始帧与认证头透传、并行 stream_id、同通道 FIFO、预热排除、未知/重复响应 ID、错误/断流、64 位帧长度与日志隐私 |
| HTTP 回退 | 不可解码的压缩请求原样转发，缺少出站字段时判为未知；未改客户端压缩开关 |
| 配置兼容 | 已安装的真实 Codex 在隔离目录接受 openai_base_url，拒绝 legacy profile；新接入不写 profile、不创建 profile 文件 |
| 恢复/失败 | 覆盖候选检查失败、写入失败、检查期间用户编辑、重复实例、原始字节与 BOM、用户追加内容、崩溃恢复及旧接入恢复兼容 |
| 真实官方账号 CLI | WebSocket 请求成功，退出 0，无 501/重连；gpt-6.1-sol、xhigh/xhigh/xhigh、思考 token 0、一致。见 `official-websocket-result.json`；此测试期间两处账号配置均字节不变 |
| 入口与窗口 | 新增 Start-Official-Audit.cmd / Restore-Official-Config.cmd，官方窗口增加“停止并恢复配置”；窗口已打开并持续运行，127.0.0.1:8766 |
| 激活后配置 | 默认 .codex 的原配置尾部字节保留；当前 .codex-api 配置字节不变；真实 Codex features list 退出 0，旧 profile 字段不存在。见 `official-desktop-ready.json` |
| 语法/差异 | 所有相关 Python 文件 py_compile 与 git diff --check 通过 |

桌面前端验收已完成：用户重启官方桌面并发送新消息，截图显示一条真实 Desktop 请求。原始 audits/official-desktop.jsonl 核对为 Desktop/gpt-6.1-sol/xhigh/xhigh/xhigh/2,070/completed/match，香港时间 2026-10-06 14:26:35，transport=websocket；与截图一致。脱敏验证结果见 official-desktop-result.json。窗口没有载入合成样例或 CLI 审计记录。此前旧 profile、WebSocket 不支持和桌面待验收描述属于历史检查点，已由本节状态替代。此检查点时 AnyRouter 只提供手动步骤；后续全部 Profiles 接入见下节。

## 2026-10-06 全部 Profiles 采集（当前检查点）

| 检查 | 结果 |
| --- | --- |
| 覆盖范围 | 默认官方目录、隔离 accounts 和 profiles 共发现 16 个配置；15 个有效配置接入，1 个无效地址保持原样；`all-profiles-ready.json` |
| 真实配置加载 | 15 个完整候选均通过已安装 Codex 的隔离加载检查；不使用 legacy profile 字段；`profiles-preflight.json` |
| 配置改动核对 | 激活后逐项 TOML 语义比对：只改变选定的连接字段；未接入配置字节不变，模型/effort/认证配置保留 |
| 完整 TPS 测试 | `python -m unittest discover -s tests -q`：90 项通过，无跳过，23.766 秒 |
| Profile 与网络隔离 | 两个真实本机 WebSocket 入口写同一日志；相同 response ID 的不同 Profile 不串行关联；Profile 列、过滤与导出一致，认证及正文不进入日志 |
| 恢复和失败 | 测试覆盖官方/accounts/API 恢复、BOM/CRLF/引用表名、用户编辑、用户改地址、候选拒绝、并发编辑、部分写入失败即时撤销、异常 URL 不回显、新 Profile 自动发现 |
| 图片识别转接启动器 | ApiCodex 新增显式标记和恢复记录验证，只恢复到已监听的本机采集入口；3 项单元测试覆盖有效、停用、不匹配、非本机、失效状态；完整启动器测试 395 passed、17 skipped，29.76 秒 |
| 跨项目集成 | 临时目录内运行真实本机采集监听，启动器重建 vision 配置后保留采集；停止恢复上游，保留启动器创建的图片设置；图片 worker 使用模拟，不发送模型请求；`vision-capture-integration.json` |
| 窗口和显示 | 独立只读 GUI 验收：9 列完整显示，包括 Profile；加载真实官方已验收记录，Profile=官方、思考 token=2,070，汇总一致；无错误、表格高度 765 px；`all-profiles-gui.json/png` |
| 当前运行 | 旧单官方入口先恢复并退出，新统一窗口正在运行；恢复记录 `audits/profiles-state.json`，统一日志 `audits/profiles.jsonl`；关闭窗口或恢复命令会恢复连接 |
| 编译与差异 | TPS 和启动器相关 Python 编译、两个仓库 `git diff --check` 通过 |

第三方客户端需重启并发送新消息才会产生新审计。已接入不等于已验证全部服务的真实响应；本轮未发起第三方模型请求，不把模拟网络测试或官方历史记录当作 AnyRouter 等服务的端到端结果。无回显字段时保持未知。原始日志和恢复记录均留在 Git 忽略目录，公开验证文件只记录脱敏证据。

## 2026-10-06 默认 `tpscode` 入口

- 用户要求简化命令：无参数 `tpscode`、便携启动 CMD 与双击 `launch.pyw` 默认进入全部 Profile 采集；`tpscode gui` 保留只读模式，其余显式子命令不变。
- 启动器通过恢复记录中的 PID 和精确窗口标题复用正在运行的采集窗口，不重复启动服务或改写配置。无记录、已停止或找不到匹配窗口时走原启动逻辑；仍保留采集器本身的重复实例保护。
- 实测发现安装记录指向 Documents 中的旧工具副本；通过本项目安装器将全局入口注册到当前 `F:\vscode代码\杂聊\tps学习`，旧副本保留。
- 启动测试基线 9 项通过；新增检查在旧实现中复现 3 项失败，修复后启动专项 13 项通过；完整 TPS 测试 94 项通过，无跳过，26.520 秒。Python 编译和 `git diff --check` 通过。
- 原采集窗口此前已关闭且 15 个配置全部恢复。实际无参数调用已安装的 `tpscode` 启动新版采集窗口，15 个配置接入；再次无参数调用复用同一 PID，恢复记录和配置字节不变，临时启动进程退出；未发送模型请求。见 `default-command-result.json`。

## 2026-10-06 统一窗口恢复历史 TPS（当前检查点）

- 用户指出旧 TPS 不见了，定位为统一入口创建 `Monitor([])`，只加载了审计文件，未接入会话日志；原始日志及旧工具副本均存在，旧版与新版无额外保存的日志目录设置。
- 修复统一入口：加载正常发现的会话目录、已保存的额外目录及审计文件，按指定用户目录动态发现新日志。官方独立入口的固定目录保护保留。速度统计和思考审计仍可在同一窗口切换。
- 同时修复 `~/.codex-api/config.toml` 根目录漏采，将该来源映射为 `default`；现在 16 个有效配置全部接入，实际客户端候选检查和连接字段之外的语义不变检查通过。见更新后的 `all-profiles-ready.json`。
- 新增临时目录测试验证历史样例真实 TPS=10、保存的日志目录/审计文件仍加载、根目录 default 恢复原始字节、动态扫描遵循指定用户目录；修改前复现两个失败和一个参数缺失。完整 `python -m unittest discover -s tests -q` 97 项通过，无跳过，26.109 秒；编译和差异检查通过。
- 实际只读 GUI 验证速度统计：近 7 天读取 945 条响应，Desktop 871、CLI 74，扫描 18 个日志文件，无错误；显示最新 300 行、30 个曲线点，汇总识别 933 条有效时间边界，截图与数据一致。见 `restored-tps-gui.json/png`。此截图不使用合成数据，未关闭实际采集窗口。
- 旧窗口通过恢复命令退出后重新打开新版，当前 PID 48256；新增历史 TPS 读取不产生模型请求。旧请求的 TPS 可正常重读，出站/首包/最终回显不能追溯补采，仍依据已有审计证据判定。
