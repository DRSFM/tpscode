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
