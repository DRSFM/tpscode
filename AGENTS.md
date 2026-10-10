# 本机约定

- Windows 命令使用 PowerShell 7（`pwsh`），不默认使用 Windows PowerShell 5.1。
- 全局命令使用安装记录中的本项目目录；不要重新引入 AppData 程序副本。
- 全局启动入口依赖 PATH 中的 PowerShell 7；默认日志只读模式需 Python 3.10+，旧采集恢复组件需 Python 3.11+。

## 协作修改记录

- 2026-10-10：本机 SFM 联合更新 TPS 至 a705440、ApiCodex 至 16d9d49，恢复 10 个 API 原地址并关闭旧转发，保留本地委派及历史记录。按用户确认的必要字段方案正式接入 Windows Desktop 和 exec/e 的原生内存诊断，TPS 自动发现各 home 的审计文件，缺失回显保持无法审计；普通交互 CLI 保留原生行为并继续研究。源码完整 ApiCodex 447 passed、38 skipped、263 subtests，TPS 111 passed、6 subtests，C:/tools 实际模块专项 117 passed、17 subtests；源码和安装副本各完成五项隔离真实内核对照，出站 low、回显 high/缺失、自动发现及重开均通过，新增诊断无正文标记和原始收发负载。三个运行模块已备份部署，保留包身份及辅助入口回退，Windows 参数透传、标准流退出和子进程回收通过；测试窗口启动成功，未完成界面回复验收。用户指出焦点干扰后立即停用 computer-use 并精确清理测试进程，后续仅隐藏后台验证。生产 13 个路由与恢复基线一致、旧采集 inactive；12 份配置哈希不变，一份验收期间变化未覆盖。仅只读核对用户新启动的真实 Desktop 又读到 16 条审计，14 条出站/回显 xhigh 一致、2 条 unknown，读取错误 0。旧客户端需用户自行通过 ApiCodex 重开，未重启用户客户端。本批按用户要求整理源码、测试与验收记录用于远端发布。 ApiCodex 按暂存内容导出的独立发布快照完整 pytest 435 passed、38 skipped、246 subtests，排除原有未提交委派改动；TPS 沿用本批源码完整 111 passed、6 subtests。详见 VALIDATION.md。

- 2026-10-07：按用户要求整理本机 TPS 改动用于 Git 提交与远端发布，包含可选官方采集、PowerShell 7/Git Bash 启动支持及对应文档和测试；固定 shell 脚本使用 LF，避免 Windows Git 的 CRLF 转换破坏入口。发布前已核对 origin/main、完整差异和 Git 忽略范围；沿用同一代码版本的 101 passed、4 subtests，diff 检查通过。采集日志、恢复状态及本机配置不纳入提交，运行中的采集进程保持。

- 2026-10-07：普通启动默认仅采集 API，新增单次 `profiles-audit --include-official` 并保留独立 `official-audit` 与历史日志；窗口展示当前范围，不复用范围不同的采集窗口。同步 apicodex 具名账号的受限兼容，恢复本机三个官方配置，10 个 API 配置和监听端口保持。TPS 完整 pytest 101 passed、4 subtests，apicodex 398 passed、17 skipped、256 subtests；隔离真实 Windows 进程识别/恢复及两个实际具名账号部署入口 features list 均通过。未发模型请求、未重启现有客户端；旧采集进程暂留，下一次实际启动加载新默认值。详见 VALIDATION.md。

- 2026-10-05：从 DRSFM/tpscode 拉取源码，将全局启动入口及 README 安装命令改为 PowerShell 7，以符合本机约定；补充 Git Bash 同名 shell 入口，由安装器一并注册并保护已有无关命令。全局入口安装到 `C:\Users\SFM\.local\bin`，此目录原已在用户 PATH 中。28 项原有测试、使用持久 PATH 的 PowerShell/CMD/Git Bash 跨目录调用、中文路径及带空格参数、list/watch 和 GUI 加载筛选验证均通过；无参数启动成功并立即返回终端。源码保留在本目录，未提交或推送远端；详细验收见 VALIDATION.md。
- 2026-10-06：更新到远端 `79b4468` 并重新部署全局命令，保留 PowerShell 7/Git Bash 入口和上次验收记录；仅 VALIDATION.md 追加内容发生冲突，已保留双方记录。97 项测试、三个终端跨目录调用、速度/审计只读 GUI 验证通过。本轮未启用真实 Profile 采集；新版无参数命令会启动采集并临时调整连接，纯读取使用 `tpscode gui`。备份及验收详见 VALIDATION.md。

- 2026-10-10：按用户要求将账号与所有 API 的 TPS 监控改为日志只读，关闭旧采集后台并恢复请求地址；无参数及旧图形入口不再开启转发，旧 include-official 参数仅兼容解析。保留远端 PowerShell 7/Git Bash 安装支持及历史验证记录。TPS 完全关闭时，AnyRouter Astra、官方账号和 ApiCodex 菜单 0 均完成真实“你好”请求；各请求前后配置哈希不变，重启时 AnyRouter 按普通启动逻辑同步 MCP/通知/项目及界面设置，请求地址不变。合并后完整测试与远端发布结果见 VALIDATION.md。
