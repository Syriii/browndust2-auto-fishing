# 检查与实测工具

[文档目录](../README.md) · [开发指南](guide.md)

在仓库根目录通过 `.\.venv\Scripts\python.exe` 运行脚本。下面列明每个工具是否连接游戏或产生真实输入；普通离线验证不运行实机工具。

| 脚本（相对 `scripts/`） | 用途 | 对游戏的影响 |
| --- | --- | --- |
| `checks/check_architecture.py` | 静态导入方向与循环检查 | 不导入设备、不连接游戏 |
| `checks/replay_mechanisms.py` | 已保存原图的机制定位回放与局部耗时报告 | 不加载相机、窗口或输入模块；只读取原图，输出 JSON |
| `checks/review_feedback.py` | 只读证据包索引、未确认分类与同轮追溯 | 不连接游戏，不解压或改写原 ZIP；生成 JSON/Markdown |
| `benchmarks/qte_latency.py` | 合成图像与日志提交时延基准 | 不连接游戏、不发送输入；结果写入 .local/benchmarks |
| `checks/smoke_ui.py` | 实际 Tk 控件、模拟任务，检查启停、设置及日志筛选；自动结束 | 不连接游戏、不发送输入，设置写入临时配置 |
| `checks/preview_ui.py` | 带示例日志的手动页面预览 | 不连接游戏、不保存配置 |
| `checks/smoke_updates.py` | 隐藏 Tk 更新与存储入口检查 | 临时配置和模拟网络，不下载、不替换真实程序 |
| `checks/check_portable_package.py` | 完整包与真实更新助手的隔离升级、恢复验证 | 使用 C# 测试 EXE，不运行钓鱼程序；需 Windows .NET Framework csc |
| `checks/smoke_capture.py` | 检查 DXcam 创建、截图和释放；可模拟旧工厂缓存缺失 | 只读截图，不聚焦或发送输入 |
| `checks/smoke_feedback_capture.py` | 检查 GDI 与 DXcam 并行采集及资源释放 | 只读截图，不发送输入 |
| `live/run_live_diagnostic.py` | 有时限的钓鱼诊断，默认 90 秒 | 真实抛竿和按键，沿用读取的配置；失焦或到时停止 |
| `live/record_qte_session.py` | 录制输入时序、QTE 反馈和结算证据，默认 45 秒 | 真实钓鱼；本进程关闭自动清包，参数覆盖不写回配置 |
| `live/clean_backpack_once.py` | 明确执行一次手动清包 | 实际出售背包物品，不受自动清包开关约束 |

## 常用命令

对指定诊断目录生成反馈索引；可重复传入 `--input-dir`，原包不改写：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/review_feedback.py --input-dir .local/diagnostics --output-dir .local/maintenance/feedback-index
```

输出 `index.json` 和 `index.md`。按完整 ZIP 哈希去除重复副本，整轮/场景包只作为同轮上下文，
不算作新的反馈失败。旧包没有 diagnostics 时保持 legacy_unclassified，并按原原因分组；
不能从保存的稀疏图片数计算采样率或命中率。工具检查元数据和所引用文件是否存在，
不解码图片或宣称所有图像完整。坏包单列，存在读取错误时退出码为 1。

特殊机制离线回放（默认输出 `.local/maintenance/mechanism-replay.json`）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/replay_mechanisms.py
```

默认逐一核对 17 张控制原图中的绿色存在状态、未确认起按端和已标注的局部障碍；
输出原图 SHA-256、裁剪坐标、指针、色区及区域提取耗时，不验证游戏命中率。
外部 PNG 目录使用 `--input-dir 路径 --crop 上 下 左 右`，同目录图片应使用同一种原始 ROI；
坐标为半开区间，不猜测截图布局。外部原图仅生成观测报告，不冒充已标注回归通过。

页面集成检查不连接游戏：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/smoke_ui.py
```

只读检查显示器枚举与旧缓存失配，仅在独立测试进程模拟，不更改显示器布局：

```powershell
.\.venv\Scripts\python.exe scripts/checks/smoke_capture.py --simulate-stale-factory
```

已经安排真实游戏实测时，可使用限时诊断或反馈记录：

```powershell
.\.venv\Scripts\python.exe scripts/live/run_live_diagnostic.py --seconds 90 --location 4
.\.venv\Scripts\python.exe scripts/live/record_qte_session.py --seconds 45 --feedback --no-full-frames
```

两种工具分别运行，不要与页面任务或另一个钓鱼进程同时运行。实机调试始终运行 Python 源码，已部署 EXE 不用于替代源码调试。

## 反馈录制选项

`--config 路径` 只读使用指定配置。未指定时只读取本仓库 `.local/config.ini`，不隐式读取父目录部署配置。新克隆可先运行源码页面生成默认配置；跨工作区实测可显式指定已有配置。路径不存在会在游戏操作前报错。

`--no-full-frames` 关闭高频全窗口录像，保留时序、反馈和小区域证据。`--stop-file 路径` 允许创建该文件请求正常停止及写盘。参数细节可执行 `record_qte_session.py --help` 查看。

`--probe-outcomes` 会刻意尝试色条外及蓝条按键，采集反馈字样；`--probe-escape` 抛竿后只观察、不发送 QTE 按键，用于超时证据。二者互斥，均为专用实验模式，不用于正常钓鱼或评估命中率。

## 输出位置

源码日志位于 `.local/logs/`；截图、反馈、结算和录制证据位于 `.local/diagnostics/`。每次工具输出的实际目录用于定位本次记录。

## 结果判断

工具输出的“检测到上钩”“QTE 结束”和“确认捕获”是不同阶段。截图、反馈和结算证据格式见[日志与诊断](../user/diagnostics.md)。沙箱找不到窗口时先核对桌面会话与权限，不能直接认定游戏未打开；无法实测时如实记录限制。

### 不打扰游戏的 UI 检查

`python scripts/checks/smoke_ui.py --hidden` 保持 Tk 主窗口隐藏，只运行模拟任务与临时配置，验证设置、日志与启停。跳过可视布局检查，不代表实机或 EXE 验收。默认不带参数的 UI 检查仍会打开窗口，请在不影响游戏运行时执行。

`python scripts/checks/smoke_ui.py --short-screen` 显示测试窗口，模拟 125% Tk 缩放和 1366×768 屏幕的工作区，检查原生窗口边界及开始、保存按钮可见性；不能与 `--hidden` 同用。所有模式都覆盖诊断积压分批读取后的时间顺序，以及警告不等待积压清空即可显示。

## 更新与发布包验证

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/smoke_updates.py
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/check_portable_package.py dist/BD2_AutoFishing --report .local/maintenance/package-check.json
```

包检查要求候选目录同级存在 `BD2_AutoFishing-windows.zip` 及同名 `.zip.sha256`，并验证目录与 ZIP 的清单一致。真实助手只更新隔离目录中的测试 EXE，临时目录位于 `.local/maintenance/`，报告位置由 `--report` 指定。

工具不代替公开下载验收：正式发布后仍需检查 Release 附件、版本查询与实际下载，见[发布步骤](releasing.md#github-构建)。

## 仅验证航海导航

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/live/record_qte_session.py --seconds 90 --location 亚特兰蒂斯 --navigation-only --no-full-frames
```

此模式使用源码，从码头、地图、换岛确认或已确认待机的钓场进入目标岛屿，到达后立即停止，不抛竿。
钓场内通过本帧“更改”进入地图；按配置核对并确认普通换岛，不点击船锚或购买许可证。
不能与故意命中/脱钩探针参数组合。正常模式仍会钓鱼。
导航读数、动作和截图保存在 `.local/diagnostics/navigation/`；窗口变化和失焦照常停止。

### 验证自动换点往返

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/live/record_qte_session.py --seconds 180 --location 亚特兰蒂斯 --refresh-island-only --no-full-frames
```

使用正式 `game/islands/travel.py` 的中转、返回路径，回到原钓场即停止，不抛竿。
仅此模式允许 180 秒测试上限；两段导航各自最多 75 秒。单程 `--navigation-only` 和普通钓鱼仍最多 90 秒，模式之间及 QTE 探针互斥。测试不修改个人配置中的自动换点开关。
