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

## 2026-10-05 本机安装验收

- 从 `https://github.com/DRSFM/tpscode.git` 拉取到 `E:\新版codex工作区\tpscode`，基于提交 `8e5580f`。
- Python 3.13.1 和 tkinter 8.6 已存在，无需安装 Python 包；普通终端的 PowerShell 7.6.6 可通过 WindowsApps 中的 `pwsh.exe` 调用。
- 全局入口改为 PowerShell 7，增加 Git Bash 的无扩展名 shell 入口；两者使用同一份安装记录和源码，未创建 AppData 程序副本。
- 命令安装到 `C:\Users\SFM\.local\bin`，此目录原已在持久用户 PATH 中。
- 28 项原有 unittest 全部通过。
- 在 `C:\Windows\Temp` 使用持久机器/用户 PATH、移除当前 `CODEX_HOME` 后，PowerShell 和 CMD 的帮助、查询，以及 PowerShell 的有限次数持续监控均成功；Git Bash 的命令发现、帮助、中文路径和带空格模型参数也成功。
- 本机日志解析未报告损坏记录或读取错误。GUI 自动检查加载 70 次响应，筛选、选中行、30 个图表点和表格空间验证通过，错误字段为空。
- 无参数的全局 `tpscode` 在约 0.78 秒内返回终端，随后确认新的 `Codex TPS · Desktop / CLI` 窗口已打开；保留窗口供用户使用。
- 以上是本机 Windows 终端验证，未测试 Linux、macOS 或 WSL。

## 2026-10-06 本机远端更新部署

- 本工作区从 `8e5580f` 快进到远端 `79b4468`（Add profile-wide reasoning audit and preserve historical TPS），保留本机 PowerShell 7 与 Git Bash 启动改动；VALIDATION.md 追加冲突已合并，双方历史记录均保留。
- 更新前的本机文件和已安装入口备份在 `C:\Users\SFM\AppData\Local\CodexTPS\update-backups\20261006-0543f8ca0b9e4f33ab576a55858bc6a0`；另保留 Git stash `2a469de59d540f709506494a4ca52664ecb7d15d`。该备份目录不是运行中的 AppData 程序副本。
- 重新运行 PowerShell 7 安装器，全局记录继续指向 `E:\新版codex工作区\tpscode`；CMD、PowerShell 和 shell 入口的 SHA256 与源码对应文件一致。
- 完整 unittest：97 项通过，无跳过，26.339 秒；包含临时目录中的配置接入/恢复、真实本机模拟 HTTP/SSE/WebSocket 及安装客户端隔离配置兼容检查。
- 在 `C:\Windows\Temp` 使用持久机器/用户 PATH、移除 CODEX_HOME/PYTHONPATH 后，PowerShell 的帮助、list/watch、CMD 的 list、Git Bash 的命令发现和新 audit 子命令均退出 0；中文审计路径正常。
- 只读速度 GUI 加载最近一天 70 次响应，表格及 30 个图表点正常；只读审计 GUI 读取全部历史 34,578 次响应，显示最新 300 行，错误字段为空。审计检查同时加载仓库中的 6 条明确合成样例；可比回显和降低结果来自样例，不作为真实提供商采集证据。检查报告为 `validation/local-update-speed-smoke.json` 与 `validation/local-update-audit-smoke.json`。
- 本次部署未在实际用户目录启用或恢复采集。新版无参数 `tpscode` 按远端设计启动全部 Profile 采集，会临时调整连接配置；`tpscode gui` 保留只读模式。无参数分发由隔离启动测试验证，不对当前会话执行该采集入口。

## 2026-10-07 官方账号默认关闭、保留可选采集

- 默认采集跳过 `.codex`、`.codex-api/accounts/*` 及明确要求 ChatGPT 登录的配置；`profiles-audit --include-official` 仅在本次包含官方账号，`official-audit` 独立入口与历史监控保留。
- 增加采集范围和开始时间到恢复记录；窗口标题、说明和复用检查与范围一致。明确要求 ChatGPT 登录的配置使用官方 ChatGPT 上游，不依赖登录状态探测把未登录的订阅配置错误导向 API 上游。
- 配套 apicodex 校验仅认可全局安装记录指定的源码、默认恢复记录、显式开启标志、匹配账号/标记/官方上游和实际监听进程；使用 Windows 进程创建时间拒绝复用 PID。该本机协调不构成抵御同一系统用户下恶意进程的安全边界。
- TPS 全量 pytest：101 passed、4 subtests；apicodex 全量 pytest：398 passed、17 skipped、256 subtests。新用例覆盖默认不读官方认证、动态发现的新账号仍跳过、显式开启后恢复、选项不跨次保留、配置同步和无效采集记录拒绝；原 HTTP/SSE/WebSocket 合成审计回归通过。
- 隔离临时目录运行实际采集进程（无凭据、无模型请求），实际验证 Windows 进程命令行/创建时间/监听端口、无关 PID 拒绝、官方配置完整恢复及采集进程正常退出。全局命令 help 可见新选项，语法和 diff 检查通过。
- 安装源码仍为本目录；apicodex 的 `codex_accounts.py` 备份至 `C:/tools/backups/tps-optional-20261007` 后部署，部署哈希一致。两个实际具名账号通过部署入口执行 `features list` 均退出 0，模型、思考等级和认证配置保持。
- 当前三个官方配置已按原恢复记录撤销代理地址，其他语义保持；10 个 API 配置哈希和原进程的 10 个 API 监听端口保持。仅备份运行模块及无密钥的恢复记录，不复制凭据。机器可读结果：`validation/optional-official-20261007.json`。
- 现有旧采集进程仍承载 API 流量，未关闭或热替换；其状态窗口可能显示官方配置已修改。下一次关闭旧窗口并实际启动新采集器时，加载默认排除官方的策略。新进程分配端口后，需按原采集流程重启需要采集的客户端。未进行真实模型新回复或 Desktop 完整重启验收。

## 2026-10-10：账号只读、API 采集与窗口解耦

- 旧状态关联的 16 份真实配置先备份，再按连接字段还原；逐份 TOML 语义核对通过，其他设置保留。备份在本次聊天 work/tps-recovery-backup-20261010。
- 默认统一入口对官方目录、账号目录与 ChatGPT 登录连接只读统计。API 采集服务独立于统计窗口；关闭窗口不停止转发，再打开复用服务。启动与进程所有权使用跨进程锁。
- 独立管道恢复进程在采集器被强制结束后恢复其所属配置；不恢复新 token 的配置。恢复失败保持可重试状态并返回非零，用户移除或注释的地址不再阻止清理标记。旧采集进程已死亡时，重启工具先恢复残留。
- 本机 ApiCodex 对普通 API 和图片转接都检查采集入口。可验证的采集器失效或已停止时恢复原 API/图片地址并提示本次无实时审计，用户修改的普通 API 地址保留。无效恢复记录仍明确报错。
- 基线 TPS 97 项通过；新增失败先复现。最终完整 unittest 104 项通过、30.727 秒；真实子进程强退、双并发启动、关闭统计窗口、后台复用、原配置恢复均通过。ApiCodex 完整 pytest 399 passed、17 skipped、26.99 秒；两仓库编译与 git diff --check 通过。
- 实际后台 PID 38072，13 个 API Profile 采集中、3 个账号只读。全部 13 个端口可连接；账号配置 SHA-256 完全不变，API 仅连接字段语义改变，13 个上游均匹配本机 ApiCodex 登记。未发送真实模型请求，未重启用户客户端。
- 本次旧窗口需重启以加载地址。以后显式停止实时审计，或采集器异常退出后，已缓存本机地址的客户端也可能需要重启；文件恢复不能修改客户端内存。整机断电由重启工具和 ApiCodex 启动检查处理，统计窗口关闭不触发停止。

## 2026-10-10：菜单 0 账号边界与 Windows 并发锁修复

- 明确 ApiCodex 菜单 0 的官方默认账号和独立账号均只读；API 根目录的 default 配置与菜单 0 的官方账号不同。强化默认采集测试：即使账号未登录、账号目录存在旧 API provider，仍不改账号配置；默认 API 根配置继续接入。
- Account menu 基线 10 项、TPS profiles 基线 14 项通过。ApiCodex 新增独立账号 CLI/Desktop 检查及默认账号采集准备禁入断言；菜单 11 项、完整 pytest 400 passed、17 skipped、27.61 秒。
- 本轮 TPS 完整测试复现 Windows 并发启动竞争：获取锁前读取已被其他进程锁定的首字节触发 PermissionError，并泄漏文件句柄。新增确定性锁竞争测试先复现同样失败。
- 查询 [Microsoft CRT _locking](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking?view=msvc-170) 与 [Python msvcrt.locking](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking) 官方说明：字节锁可覆盖文件末尾之外，已锁字节会拒绝其他进程访问。因此删除锁前不必要的读写，沿用原有等待、超时和释放逻辑；生命周期测试在启动失败时也清理所属临时服务。
- 修复后生命周期 5 项通过；完整 TPS unittest 105 项通过、30.981 秒，无跳过。编译与 git diff --check 通过。
- 实机复核 PID 38072 仍在运行，13 个 API 入口均可连接；官方目录与两个账号目录共 3 份配置均为官方直连、无采集标记，未列入 API 恢复记录。登记的菜单 0 独立账号也包含在该检查中。未发送模型请求、重启现有后台或用户客户端。

## 2026-10-10 当前最终模式：账号与 API 全部日志只读

- 用户随后要求所有账号与 API 统一改成日志只读，撤销本地 TPS 转发。先备份 16 份配置与原恢复记录到本次聊天 work/tps-readonly-backup-20261010，再恢复 13 个 API 原地址；其他 3 份账号配置字节不变，连接字段以外 TOML 语义不变。旧后台已退出、恢复记录 inactive、原 13 个端口与 8766 均无监听。
- 无参数 tpscode、launch.pyw、三个 CMD 桌面入口及旧 profiles-audit / official-audit 图形命令均进入只读日志。capture 和 --no-gui 转发入口停用，--restore 兼容保留。普通 GUI 不读取或恢复采集状态，不生成采集标记，不改配置，不启动网络监听；默认速度统计、每 2 秒刷新。两种表格均直接显示“思考等级（配置）”。
- ApiCodex API 启动仅清理完整旧 TPS 标记、恢复登记的 API/图片路由，不联系采集器。不存在或损坏的旧恢复记录不阻止启动；有效记录只辅助保护用户改过的本机地址，不使用其上游值。原图片功能与账号分支保留。
- 基线启动 13 项、GUI 6 项、ApiCodex TPS/账号菜单 18 项通过；新预期先复现启动 3 失败、GUI 1 失败、ApiCodex 4 失败。修复后完整 TPS unittest 109 项通过、28.606 秒；完整 ApiCodex pytest 402 passed、17 skipped、28.93 秒。Python 编译与两仓库 git diff --check 通过。
- 新增集成检查用账号与 API 日志验证增量响应从 high/10 TPS 更新到 xhigh/30 TPS；阻断网络 socket、子进程和配置恢复调用后仍通过。旧损坏采集状态也不影响图形入口。实际全局入口 GUI smoke 读取 920 条响应、300 行表格、30 个曲线点，无错误；实机随后只读读取 926 条记录，926 条有等级、913 条有真实 TPS 边界，无读取错误。
- 实际无参数 tpscode 已打开“Codex TPS · 日志只读”窗口（PID 55852）；启动前后全部 16 份配置 SHA-256 不变。截图与结果在本次聊天 outputs/tps-readonly.png、outputs/tps-log-readonly-result.txt。未发送真实模型请求、下载依赖或修改认证；未重启用户 Codex。
- 显示的是本轮客户端日志中的配置思考等级，不能证明服务端回显或实际计算量。既有客户端可能缓存旧 TPS 地址，需彻底退出后重新打开一次；之后监控启停均不改客户端路由。本节取代前述临时 API 转发方案作为当前使用方式。

## 2026-10-10：TPS 完全关闭时的真实请求与 Git 合并验收

- 关闭本轮只读 TPS 窗口，确认旧采集恢复记录 inactive，原 13 个端口与 8766 无监听。原 API 独立窗口已退出；重新通过 apicodex --desktop --api-profile anyrouter 启动，标题 ChatGPT (anyrouter)，加载原始 AnyRouter 地址。
- 官方 app-server 使用该 API Profile 的 gpt-6-astra / high 发送“你好”，收到完整回复；同协议默认账号 gpt-6.1-sol / xhigh 完成真实回复。实际 apicodex CLI 菜单 0 → 官方默认账号再次发送“你好”，退出码 0、收到完整回复。三次请求均在 TPS 关闭时进行，请求前后配置哈希一致；启动前后 15 份完整配置哈希不变，AnyRouter 由正常启动同步共享 MCP、通知及项目/界面设置，连接地址、模型和思考等级均不变。API 对话保存在该 Profile 会话目录，并经独立实例启动器请求打开对话；发布后激活该独立窗口，原生窗口截图已确认同名验证对话、用户“你好”及完整回复，输入框模型为 6 Astra / 高。
- origin/main 有一条 TPS 更新及两条 ApiCodex macOS 更新；保留双方提交历史，合并远端 PowerShell 7/Git Bash 安装支持及 macOS 实现。旧采集默认值、标题和测试按最终只读模式解决；include-official 旧参数仅兼容解析，不开启转发。
- 合并中测试发现旧 include_official 片段与只读版本的遗留类不兼容，已完整保留此前验证过的遗留恢复实现；最终完整 TPS unittest 109 项通过、28.886 秒。追加旧参数兼容断言后只读专项 3 项通过。ApiCodex 合并后完整 pytest 411 passed、38 skipped、27.07 秒；平台相关跳过保留。两仓库编译与 diff 检查通过。
- 凭据、会话正文、配置备份、采集状态和本机日志均未纳入 Git；仅源码、测试、说明及既有提交历史推送至两个仓库的 main。远端最终提交 ID 在本次聊天 outputs 的发布报告中核对。


## 2026-10-10：本机 SFM 联合更新与只读切换

- TPS `main` 从 `168e4bc` 快进至 `a705440`；ApiCodex `main` 从 `c0f26c0` 快进至 `16d9d49`。远端历史验收属于其他运行环境，本机以下列实测为准。
- ApiCodex 本地改动保存在 Git stash `joint-tps-readonly-20261010 preserve local account and delegate changes`，提交标识在 `work/joint-repair-20261010/apicodex-stash.txt`。恢复本地委派、额度保底功能及历史记录，保留远端 CLI 可靠性与 macOS 改动；旧账号 TPS 显式接入补丁不再应用，原始内容仍在 stash。AGENTS.md 的唯一合并冲突已保留双方历史并解决。
- TPS 恢复预检逐份比较 13 个真实配置的 TOML 语义；仅恢复 10 个 API 的原连接字段，其他字段不变，3 个官方账号配置字节不变。恢复记录单独备份，未复制认证数据；结果在 `work/joint-repair-20261010/recovery-result.json`。
- 旧采集进程 PID 64028 的命令行、创建时间及窗口归属核对后正常关闭，未强制结束；恢复记录 inactive，原 13 个采集端口无监听。新版默认窗口 PID 8220、标题“Codex TPS · 日志只读”，无监听端口。
- 安装器成功提示改为 read-only logs；恢复测试的状态读写显式使用 UTF-8，修复中文 Windows 默认 GBK 下首次完整 pytest 的 5 个失败（含子测试）。修复后完整 TPS pytest 109 passed、6 subtests passed，30.20 秒；ApiCodex 完整 pytest 423 passed、38 skipped、258 subtests passed，34.98 秒。
- 实际全局入口仍为 C:/tools/apicodex.bat；26 个 Python 模块与合并后源码哈希一致，更新 7 个文件（含 2 个新增平台模块）。备份和安装清单在 `C:/tools/backups/tps-readonly-joint-20261010-115728`，摘要在 `work/joint-repair-20261010/deployment-result.json`。预加载 26 个实际安装模块并核对路径后，TPS 清理、账号菜单/账号、CLI 可靠性及委派专项 90 passed、1 skipped、38 subtests passed。
- 真实 Codex CLI 对 13 个配置执行 features list 均退出 0，配置哈希不变；未发送模型请求。结果在 `work/joint-repair-20261010/config-load-result.json`。
- 全局 TPS GUI smoke 读取最近 7 天 812 条响应，表格 300 行、曲线 30 点，无错误；真实日志中缺少回显证据的记录保持无法审计。GUI 打开、关闭以及无参数默认启动前后 13 个配置 SHA-256 不变。截图/结果为 `work/joint-repair-20261010/readonly-gui-smoke.png/json`。
- 已重新部署 PowerShell 7/Git Bash 的 TPS 全局入口，仍指向本仓库；未改认证、登录状态、模型或思考等级，未重启用户 Codex 客户端。已缓存旧 TPS 端口的客户端需彻底退出并重新打开一次。本次本地修改未提交或推送。

### 后续：恢复历史显示及调查新回复的原生取数

- 用户反馈重开后出站/回显不可见。旧 `audits/profiles.jsonl` 仍在，但此前无本地 settings.json，默认 GUI 未加载该审计文件；现已将其绝对路径加入本地 audit_logs。真实历史文件包含 804 个事件（不等于 804 次回复），最后更新为本机 2026-10-10 03:12:30。最近 7 天审计一致筛选实际显示 152 条旧记录，smoke 无错误；报告在 `work/joint-repair-20261010/history-audit-smoke.json`，随后打开历史审计窗口 PID 133020。新回复的出站/回显尚未恢复采集，不能将这次历史显示修复表述为实时审计恢复。
- 本轮调查读取本地官方手册的诊断及遥测相关段落，并核对官方配置文档与本地官方源码 `7498521`。`sse_event_completed` 中 model_reasoning_effort 来自请求元数据；以出站 low、模拟回显 high 的对照验证，普通遥测仍记录 low，不可作为服务端回显。现用 Desktop 日志的 8 个文件和 14 个原生日志数据库的最近最多 3,000 行均进行了字段存在检查，未输出正文或认证数据；有原始收发记录的数据库条目来自 7–8 月，不能用于新回复。摘要为 `existing-native-log-summary.json`。
- 隔离 CODEX_HOME、无真实认证、127.0.0.1 模拟 Responses 服务验证：本机 CLI 0.156.0、Desktop 内核 0.162.0-alpha.17.2，以及后者的 app-server JSONL 接口，均请求出站 low、收到模拟 high、退出 0，隔离配置哈希不变。仅启用 `codex_http_client::transport=trace` 与 `codex_api::sse::responses=trace` 即可取到原始两项字段，原生日志数据库中仍未保存这些 HTTP 原始负载。报告为 `native-audit-probe/filtered-result.json`，完整诊断仅留在本项目忽略的 work 下；这些是合成服务验证，不能代表任一真实提供商已通过。
- WebSocket 模拟验证取到两个内核的原生发送帧和 response.created/completed 回显；解析 Rust 字节转义与 DEFLATE 压缩后，分别还原预热与正式请求的 low，回显为 high，明确排除预热记录。Desktop 内核整轮退出 0；CLI 0.156.0 在该模拟场景超时，虽字段提取成功，仍不视为整轮兼容性验收通过。结果为 `native-audit-probe/websocket-result.json` 与 `websocket-decoded-result.json`。
- 已只读检查本机 Desktop 包的启动代码：启动端可将 RUST_LOG 传入后台内核，并使用 JSON 格式诊断。可行方向是从客户端自身收集诊断，保持原请求地址，TPS 仅查看提取的字段；原生诊断包含正文和工具内容，不能直接宣称只开日志就满足仅保存元数据。用户已选择“仅必要字段，继续联合修复”，下述原型按此约束实现；未修改生产启动流程、开启生产诊断、增加转发或替换内核。验收边界需包括 TPS 关闭/重开不影响连接、多账号归属、HTTP/WebSocket、重复/预热排除及无字段时无法审计。
- 调查后重新核对历史修复开始时的 13 份真实配置 SHA-256，均保持不变；原恢复记录仍 inactive。调查与合成验证未向真实模型服务发送推理请求。本轮跟进记录与源码改动仍未提交或推送。

### 仅必要字段诊断原型（接入前阶段记录，现状见下节）

- ApiCodex 新增 `codex_native_audit.py` 与对应测试。Windows 小入口只转交参数、环境和原有标准输入/输出；原生 HTTP/SSE/WebSocket 诊断经内存解析，再写出等级、模型、响应/会话/轮次 ID、来源及时间。文件边界再次白名单过滤，不保存输入、输出、指令、工具内容、reasoning summary 或凭据。诊断写入使用有界队列和进程间追加锁，写入异常不阻断原生请求；重叠未绑定请求不猜配，重复响应及 WebSocket 预热排除。
- 本机两个真实内核分别执行 exec 和 app-server 的 HTTP 对照，均退出 0、原请求 low、模拟回显 high。Desktop 0.162 内核另经压缩 WebSocket 验证 exec、app-server、无回显三种情况，预热与正式请求分离；只保存正式请求的 3 个事件，无回显保存 null/缺失并保持 unknown。最终版本复验 CLI HTTP、Desktop WebSocket 及无回显均通过；报告在 `work/joint-repair-20261010/metadata-entry-probe/result.json`、`final-result.json`。
- 新增审计文件没有任何合成正文/摘要标记，app-server 对父进程的 stderr 也无这些标记；HTTP/SSE 原始负载及 WebSocket 原始帧/接收事件在原生日志数据库中计数为 0。CLI exec 的原有可见输入/输出进度仍经标准流显示，不写入新增审计文件；普通原生会话历史属于既有客户端行为，不将其称为新增诊断保存。早期完整合成诊断探测文件未用于新原型采集。
- TPS 当前显式加载这些元数据文件即能结合真实生成的原生 session 日志，HTTP/WebSocket 各对应 1 条回复，显示 low → high；无回显显示 unknown，读取错误 0。此项只证明数据契约与匹配，不代表生产 TPS 已自动发现新文件；报告为 `tps-integration-result.json`。
- 17 项原型测试涵盖双重字段限制、错误内容、缺失及冲突等级、并发归属、4 个同 home 写入器的 320 条完整记录、不同 Profile 状态隔离、预热/重复响应、Rust 字节与压缩，以及交互 CLI 参数保留。完整 ApiCodex pytest：440 passed、38 skipped、263 subtests，35.20 秒；TPS 完整 pytest：109 passed、6 subtests，32.53 秒。真实 Windows 包装入口另验证 8 种 Unicode/空格/引号/反斜杠/字面 shell 字符参数及父入口退出后子进程回收，均通过；报告为 `lifecycle/result.json`。另独立只读核对本轮全部隔离原生日志数据库的 HTTP/SSE/WebSocket 原始收发消息计数，均为 0，记录在 `sqlite-diagnostic-retention.json`。
- 发现覆盖限制：原生 TUI 不提供可收集的收发 stderr；显式 log_dir 会先追加完整文件。用 app-server + --remote 可在后台收集，但本机官方源码将该会话视作 Remote，改变 worktree、resume/fork 权限覆盖、本地工作区及认证含义，故未接入此路线。文件日志导向内存管道的符号链接原型在本机失败（Windows 1314：缺少符号链接权限），未提升权限或改变系统设置。原型的交互 CLI 直接调用原程序并提示未采集。
- 原型保留在源码中，尚未接入 ApiCodex 正常入口或 C:/tools，TPS 未增加自动发现逻辑。实际 Windows Desktop 的包装启动、包身份/沙盒及多实例窗口仍需进一步验证；后台协议通过不能替代 GUI 启动验收。已集中询问用户是否本轮先覆盖 Desktop/exec、保留交互 CLI 原行为，或继续研究全部入口；该范围选择未收到答复前不进行依赖此选择的正式改写。
- 最后核对 13 份真实配置字节全部保持，恢复状态 inactive，无测试包装子进程遗留。无真实提供商推理请求、认证写入、用户客户端重启、正式部署、提交或推送。仅必要字段保存方案已得到确认，当前未完成项是覆盖范围与正式接入验收。

### Desktop 与 exec 正式接入和后台部署验收

- 用户明确先修 Desktop 和 exec，普通交互 CLI 继续研究。ApiCodex 的 API、具名订阅账号及官方默认账号 Windows 分支接入原生诊断组件；TPS 每次刷新自动发现各已知 home 的 `audits/native-reasoning.jsonl`，保留手工导入与历史审计。不通过请求转发取数，TPS 不创建或管理收集进程、不改连接配置。
- 收集文件只含等级、模型、时间、来源与请求/响应/会话/轮次关联 ID。正文诊断在内存过滤，文件边界再次筛选；队列和追加锁有界，失败提示但不阻断模型请求。无法唯一关联的请求保持 unknown。临时启动参数只将 shell 子命令的 RUST_LOG 设为 warn，避免收集 TRACE 扩散至嵌套客户端，不改配置文件中的 shell 设置。
- Desktop 使用所选应用自己的 bundled codex.exe 与相邻沙盒辅助程序；仅在子进程经 OS 验证有包身份时恢复沙盒包提示。与已验证 0.162 runtime 的 SHA-256 完全相同。Desktop 初始化会将入口保存给辅助 MCP；编译入口在缺少审计上下文时直接退回原生程序，避免辅助调用失败或泄漏诊断。入口关闭通过 Windows Job 回收后代，标准流排空有超时，防止后台子进程持有管道导致 exec 退出挂起。
- 源码完整测试 447 passed、38 skipped、263 subtests，38.03 秒；TPS 111 passed、6 subtests，31.86 秒。C:/tools 真实模块预加载后的 auth/accounts/native-audit/CLI 专项 117 passed、17 subtests，10.33 秒。新增测试涵盖启动分支上下文、辅助回退、中文 Profile、无采集的普通 CLI、自动发现/重开/去重及同 home 并发写入。Windows 真实入口验证 8 种参数、无上下文辅助调用、持有标准流的后代及入口被关闭后的回收均通过。
- 源码与 C:/tools 安装副本分别完成 API exec、具名账号 exec、官方默认 exec、同包 Desktop app-server 和缺失回显五项隔离对照，全部退出 0，实际请求 low、回显 high 或缺失；每项 TPS 自动发现 1 条回复，重开后仍为 1 条且读取错误 0。Desktop 入口与测试宿主的 OS 包名一致，临时 shell RUST_LOG 为 warn。所有新增诊断无合成输入/输出/摘要标记，原生 SQLite 的原始 HTTP/SSE 收发计数为 0，隔离配置哈希不变。安装副本再次完成压缩 WebSocket 验证：预热排除、正式回复 3 事件、low → high、无诊断正文。后台报告位于 `work/joint-repair-20261010/background-validation/*-result.json` 和 `metadata-entry-probe/installed-websocket-result.json`。
- 独立 Desktop 测试窗口实际启动成功，包装入口、Python 收集器及 bundled app-server 全部运行，进入首次引导页；GUI 回复验证没有完成。首次启动由 Desktop 正常初始化功能/MCP/沙盒设置，所以该隔离配置全文件哈希发生变化，不能写成“GUI 启动不改所有配置”。用户指出激活窗口干扰工作后立即停止 computer-use，按唯一测试路径核对并清理 17 个测试进程；后续全部验证均为隐藏后台，不操作用户窗口。
- 部署仅更新 C:/tools 的 apiagent.py、codex_accounts.py，并新增 codex_native_audit.py；替换前核对安装文件仍等于上轮部署版本，备份到 `C:/tools/backups/native-metadata-desktop-exec-20261010-162239`，复制后哈希相等。TPS 全局入口仍指向本仓库，重开加载新自动发现逻辑；现有 Desktop 需用户方便时通过 ApiCodex 重开，新回复才使用新组件。没有重启用户客户端、发送真实提供商推理请求、修改认证或提交推送。
- 生产边界：旧采集仍 inactive。本轮未对生产配置执行写入操作；只读复核发现 12/13 份配置哈希保持，tiantiansub2api 的配置在 16:24:11 发生变化，未归因写入来源，也未覆盖或恢复这份变更。连接字段另与旧恢复基线逐项核对，13/13 相等、旧采集地址出现数为 0；结果保存在 `desktop-exec-production-boundary.json`，不能把整文件变化误报为采集改地址。
- 后续被动实证：只读发现用户新启动的 tiantiansub2api Desktop 已加载 C:/tools 新入口，其进程不属于隔离测试，未结束或操作。自动读取真实新增审计的 48 个事件并与会话关联，显示 16 条 Desktop 审计：14 条真实出站 xhigh、最终回显 xhigh，一致；2 条缺少可靠出站保留 unknown，读取错误 0。没有为这项检查发送任何请求、读取凭据或操作界面；摘要为 `passive-live-audit-summary.json`。这补充证明了实际生产 Desktop 新回复的采集与 TPS 自动发现，仍不声称执行过 GUI 输入框回复测试。
- 交互 CLI 继续调查：本地官方手册和当前源码确认 TUI 仅显式 log_dir 才启用原文文件诊断，remote 会改变 worktree/resume 语义；OTel 能给会话配置、请求状态和 token，但含工具输出片段，手册未列真实服务端 effort 回显，不能直接满足本次约定。未启用文件日志、remote 或遥测出口，后续需研究原生安全字段接口，避免以配置等级替代真实回显。
- 原始代码补证：官方源码快照 `7498521` 的 `codex-rs/otel/src/events/session_telemetry.rs:1034`，`sse_event_completed` 只接收用量与首 token 时间，输出的 `model_reasoning_effort` 来自 `self.metadata`，无法据此证明服务端回显；`codex-rs/tui/src/startup_orchestration.rs` 的文件日志 layer 以 append 打开，确认先落原文的风险。

### Git 发布范围核验

- 按用户要求将本轮 Desktop/exec 原生审计、TPS 自动发现、对应测试及说明分别整理为 main 提交。ApiCodex 仅暂存本批 9 个文件，其中 README.md 和 AGENTS.md 只暂存本轮片段；原有委派、额度保底、个人 Skill 与历史验收改动保持未提交，其文件哈希核对不变。TPS 暂存本批 7 个源码、测试及说明文件。运行日志、真实审计、凭据、配置备份及生成入口均未纳入暂存。
- 从 ApiCodex 暂存树导出独立快照执行完整 pytest：435 passed、38 skipped、246 subtests，35.53 秒。上节 447 passed 是含本机原有委派改动的工作区结果，不能作为本批独立提交的测试数量；TPS 本批源码未再修改，沿用 111 passed、6 subtests。两仓库暂存差异检查通过，远端基线分别为 a705440 / 16d9d49。
