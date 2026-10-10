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
