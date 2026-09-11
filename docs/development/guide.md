# 开发指南

[文档目录](../README.md) · [架构说明](../design/architecture.md) · [开发规范](standards.md)

本项目是独立 Windows 桌面应用，应用包 `bd2_fishing/` 直接位于仓库根目录。wheel 用于安装与资源检查，用户通过便携 ZIP 运行；不要求发布到 PyPI。

## 环境与入口

使用 Windows x64、Python 3.12。CI 固定 Python 3.12.4；本机已有合适的 `.venv` 时复用，不顺带升级依赖。直接依赖和工具声明在 [pyproject.toml](../../pyproject.toml)，完整环境由 [requirements](../../requirements/README.md) 锁定。

在克隆后的仓库根目录执行：

```powershell
# 首次创建环境；已有 .venv 时跳过
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/windows-py312.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .

# 正常桌面入口，打开后待机
.\.venv\Scripts\python.exe main.py

# 仅模拟界面，不连接游戏或保存个人设置
.\.venv\Scripts\python.exe main.py --preview
```

可编辑安装后也可使用 `.venv/Scripts/bd2-fishing.exe`。脚本通过安装后的包导入，不自行修改 `sys.path`。包导入不自动启动 GUI、初始化设备或设置 DPI；入口负责组装。

## 已实现的模块职责

以下位置相对 `bd2_fishing/`：

| 模块 | 职责 |
| --- | --- |
| `bootstrap.py` | 日志、异常处理、DPI、启动检查与桌面组装 |
| `app/desktop.py`、`preferences.py`、`calibration.py` | UI 服务、设置字段与校准 |
| `app/service.py`、`session.py`、`ocr_setup.py` | 单任务工作线程、聚焦、COM、电源、OCR 与资源收尾 |
| `app/fishing_task.py` | 钓鱼轮次协调、地点策略选择、等待上钩与恢复 |
| `app/startup.py`、`updates.py` | 配置初始化和迁移、在线/本地更新用例 |
| `game/islands/` | 五地点目录与别名、文字读取、已有地图往返刷新 |
| `game/navigation/` | 码头、选岛、启航导航及 150402 退出重进；动作前复核页面 |
| `game/inventory/` | 背包判断、出售与退出检查 |
| `game/fishing/qte.py` | 两套地点策略共用的控制循环与同步输入执行 |
| `game/fishing/mechanics/` | 同帧区域、黄蓝目标、绿色/泡泡状态、挡板及动作仲裁 |
| `game/fishing/pointer.py`、`recognition.py` | 真光标候选与游戏反馈字形识别 |
| `game/fishing/feedback*.py`、`settlement*.py` | 游戏反馈、按键归属、鱼获确认及观察生命周期 |
| `game/fishing/scene_*.py`、`hook_diagnostics.py` | 特殊外观、场景时间线与上钩取证 |
| `game/fishing/actions.py`、`cast_feedback.py`、`page.py` | 抛竿与恢复、提示判断、待机页面确认 |
| `perception/` | 通用图像、OCR 合同和文字处理 |
| `runtime/` | 取消、输入锁、几何、有效区域落点、轮次上下文和设备合同 |
| `infrastructure/windows/`、`ocr/` | Windows 窗口与输入、DXcam/GDI、RapidOCR |
| `infrastructure/settings.py`、`paths.py`、`maintenance.py` | 配置、运行路径及便携版待机清理 |
| `infrastructure/diagnostics/`、`updates/` | 后台日志/证据与文件更新事务 |
| `ui/` | 主窗口、设置、日志展示、更新入口、主题与滚动容器 |
| `resources/`、`game/fishing/assets/` | 默认配置与应用图标、玩法识别模板 |

实际允许的导入方向由[开发规范](standards.md)及 `scripts/checks/check_architecture.py` 限制。UI 经 app 访问任务和设备；runtime 不导入游戏或基础设施；纯机制规则不持有设备。现有执行和观察模块仍可使用具体适配器，尚未把所有 I/O 改成依赖注入。

## 点击能力复用

精确坐标仍用 `infrastructure.windows.input.click(x, y)`；已确认有效矩形可用
`click_in_rect(Rect(left, top, right, bottom), inset_ratio=0.2)`，返回本次实际屏幕坐标。
右、下边界为开区间，默认从四边各内缩 20%；小区域最多内缩到一个有效像素。
无效范围或比例报错，不自动扩大区域。通用落点计算在 `runtime/click_area.py`，不依赖游戏。

调用方负责确认控件身份、范围与当前窗口；航海读数保留规范化坐标 `action_bounds`，
执行前换算到屏幕坐标。当前使用按钮文字框内部，不假设整个 OCR 搜索区都可点击。
只有点而无区域的旧操作不加偏移；地图拖动与 QTE 空格仍按各自规则执行。
实际坐标记录到导航动作 `click_point`，便于复核。

## 运行数据与资源

| 运行方式 | 配置 | 日志 / 证据 | 持久报告 |
| --- | --- | --- | --- |
| 仓库源码 / 可编辑安装 | `.local/config.ini` | `.local/logs/`、`.local/diagnostics/` | `.local/data/` |
| 便携 EXE | EXE 旁 `config/config.ini` | `logs/`、`screenshots/` | `data/` |
| 仓库外普通安装 | 用户目录 `BD2_AutoFishing/config.ini` | 同根 `logs/`、`diagnostics/` | 同根 `data/` |

路径不依赖终端当前目录。默认配置只维护在 `resources/default.ini`，设置读取器通过包资源加载。识别模板、图标、OCR 模型和 Tcl/Tk 随发布包收集；测试样本、个人配置和日志不打入包。

`build/` 保存中间文件和 egg-info，`dist/` 保存本机当前交付包。构建不会覆盖维护者的 `deployment/`，源码修改也不会改变旧 EXE。更多归属见[统一布局](../design/repository-layout.md)。

## 修改与验证

修改对应文档和必要回归后，执行与变化匹配的检查：

```powershell
.\.venv\Scripts\python.exe -m ruff check bd2_fishing scripts tests main.py setup.py
.\.venv\Scripts\python.exe -m ruff format --check bd2_fishing scripts tests main.py setup.py
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/check_architecture.py
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
```

隐藏 Tk 模拟检查不连接游戏：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/smoke_ui.py --hidden
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/smoke_updates.py
```

纯文档改动检查事实、路径、链接和差异即可，不需重复本地游戏或整套回归；GitHub CI 仍按仓库工作流执行。识别改动使用真实正负例；时序改动记录帧龄、输入与停止行为，不能用合成图或平均耗时替代端到端验证。

真实游戏调试从 `scripts/live/` 显式运行源码；发布 EXE 的用户验收另行安排。工具及参数的影响见[工具说明](tools.md)，不要在离线检查中顺带启动实机工具。

日常提交走[短期分支与 PR](branching.md)，发布走[构建与发布](releasing.md)。当前已验证范围和开放问题分别见[状态](status.md)与[验证计划](validation-plan.md)。
