# 本机约定

- Windows 命令使用 PowerShell 7（`pwsh`），不默认使用 Windows PowerShell 5.1。
- 全局命令使用安装记录中的本项目目录；不要重新引入 AppData 程序副本。
- 全局启动入口依赖 PATH 中的 PowerShell 7；新版默认采集需 Python 3.11+，只读模式需 Python 3.10+。

## 协作修改记录

- 2026-10-07：按用户要求整理本机 TPS 改动用于 Git 提交与远端发布，包含可选官方采集、PowerShell 7/Git Bash 启动支持及对应文档和测试；固定 shell 脚本使用 LF，避免 Windows Git 的 CRLF 转换破坏入口。发布前已核对 origin/main、完整差异和 Git 忽略范围；沿用同一代码版本的 101 passed、4 subtests，diff 检查通过。采集日志、恢复状态及本机配置不纳入提交，运行中的采集进程保持。

- 2026-10-07：普通启动默认仅采集 API，新增单次 `profiles-audit --include-official` 并保留独立 `official-audit` 与历史日志；窗口展示当前范围，不复用范围不同的采集窗口。同步 apicodex 具名账号的受限兼容，恢复本机三个官方配置，10 个 API 配置和监听端口保持。TPS 完整 pytest 101 passed、4 subtests，apicodex 398 passed、17 skipped、256 subtests；隔离真实 Windows 进程识别/恢复及两个实际具名账号部署入口 features list 均通过。未发模型请求、未重启现有客户端；旧采集进程暂留，下一次实际启动加载新默认值。详见 VALIDATION.md。

- 2026-10-05：从 DRSFM/tpscode 拉取源码，将全局启动入口及 README 安装命令改为 PowerShell 7，以符合本机约定；补充 Git Bash 同名 shell 入口，由安装器一并注册并保护已有无关命令。全局入口安装到 `C:\Users\SFM\.local\bin`，此目录原已在用户 PATH 中。28 项原有测试、使用持久 PATH 的 PowerShell/CMD/Git Bash 跨目录调用、中文路径及带空格参数、list/watch 和 GUI 加载筛选验证均通过；无参数启动成功并立即返回终端。源码保留在本目录，未提交或推送远端；详细验收见 VALIDATION.md。
- 2026-10-06：更新到远端 `79b4468` 并重新部署全局命令，保留 PowerShell 7/Git Bash 入口和上次验收记录；仅 VALIDATION.md 追加内容发生冲突，已保留双方记录。97 项测试、三个终端跨目录调用、速度/审计只读 GUI 验证通过。本轮未启用真实 Profile 采集；新版无参数命令会启动采集并临时调整连接，纯读取使用 `tpscode gui`。备份及验收详见 VALIDATION.md。
