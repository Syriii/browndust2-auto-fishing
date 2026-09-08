# 检查与实测工具

[文档目录](../README.md) · [开发指南](guide.md)

在仓库根目录通过 `.\.venv\Scripts\python.exe` 运行脚本。下面列明每个工具是否连接游戏或产生真实输入；普通离线验证不运行实机工具。

| 脚本（相对 `scripts/`） | 用途 | 对游戏的影响 |
| --- | --- | --- |
| `checks/check_architecture.py` | 静态导入方向与循环检查 | 不导入设备、不连接游戏 |
| `benchmarks/qte_latency.py` | 合成图像与日志提交时延基准 | 不连接游戏、不发送输入；结果写入 .local/benchmarks |
| `checks/smoke_ui.py` | 实际 Tk 控件、模拟任务，检查启停、设置及日志筛选；自动结束 | 不连接游戏、不发送输入，设置写入临时配置 |
| `checks/preview_ui.py` | 带示例日志的手动页面预览 | 不连接游戏、不保存配置 |
| `checks/smoke_capture.py` | 检查 DXcam 创建、截图和释放；可模拟旧工厂缓存缺失 | 只读截图，不聚焦或发送输入 |
| `checks/smoke_feedback_capture.py` | 检查 GDI 与 DXcam 并行采集及资源释放 | 只读截图，不发送输入 |
| `live/run_live_diagnostic.py` | 有时限的钓鱼诊断，默认 90 秒 | 真实抛竿和按键，沿用读取的配置；失焦或到时停止 |
| `live/record_qte_session.py` | 录制输入时序、QTE 反馈和结算证据，默认 45 秒 | 真实钓鱼；本进程关闭自动清包，参数覆盖不写回配置 |
| `live/clean_backpack_once.py` | 明确执行一次手动清包 | 实际出售背包物品，不受自动清包开关约束 |

## 常用命令

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
