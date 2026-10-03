# Codex TPS

本地、只读的 Codex Desktop / CLI 实际会话速度监控工具。支持官方账号登录及中转 API 的 Codex 会话，无需在工具里登录或填写 API Key，也不会额外发起测速请求。需要会话日志提供真实 token 统计。

## 桌面窗口

Windows 双击 `Start-Codex-TPS.cmd`。可移动整个文件夹后使用。

安装全局命令后，可在任意目录直接输入：

```powershell
tpscode
```

它会打开桌面窗口并立即返回终端。安装或更新命令入口，在本工具目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-command.ps1
```

命令入口为 `%USERPROFILE%\.local\bin\tpscode.cmd`，旁边的 `tpscode-install.json` 记录本工具目录，`tpscode-launch.ps1` 负责使用该目录中的程序。全局命令直接使用本工具目录，不再依赖 AppData 中的安装副本。请保留整个工具文件夹；移动文件夹后，在新位置重新运行安装命令即可更新记录。仅在命令目录尚未注册时追加用户 PATH，此时需新开终端。

工具目录中的 `.\tpscode.cmd` 可直接作为便携入口使用。已安装的全局 `tpscode` 根据安装记录找到程序，支持中文和空格路径；找不到程序时会报告记录中的实际目录。

窗口每 2 秒增量读取日志，在模型响应完成后更新，支持客户端、模型、来源目录、时间范围与会话 ID 筛选。折线图显示最近 30 次有有效时间边界的响应；点击图上的点可定位表格。导出 CSV / JSON 包含当前筛选范围内的全部结果。

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

Python 3.10+，正常 Windows Python 安装自带 tkinter。运行只用标准库，不需要 pip、模型权重、额外运行服务或网络连接。不读取 `auth.json`、API Key、Cookie、账号配置或数据库；解析日志时只保留统计和结构字段，不保留或导出对话正文。原始日志以只读模式打开。

导出包含会话 ID、模型、统计数据和本地日志路径。分享导出文件时可按需要移除这些本地标识。

## 验证

```powershell
python -m unittest discover -s tests -v
python codex_tps.py diagnose
```

`tests` 使用合成日志，不包含用户对话或登录凭据。
