# 开发指南

[文档目录](../README.md) · [当前开发状态](status.md) · [架构方案与实施范围](../design/architecture.md)

本页描述已经落地的源码结构。首轮迁移建立功能归属、设备与运行边界，源码包 bd2_fishing 直接位于仓库根目录；新岛屿、新机制和完整导航尚未实现。

## 环境与入口

Windows、Python 3.12。[pyproject.toml](../../pyproject.toml) 管理元数据、直接依赖和入口，[Windows 锁定清单](../../requirements/README.md) 固定已验证环境的直接、间接依赖和构建工具。本轮没有升级依赖。开发安装后工具无需修改 sys.path。

以下命令均在仓库根目录执行，本地对应 `auto_fishing-dev/`：

```powershell
# 首次创建环境后安装固定依赖；已有环境复用
.\.venv\Scripts\python.exe -m pip install -r requirements/windows-py312.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .

# 默认页面待机；也可以使用安装后的 bd2-fishing 入口
.\.venv\Scripts\python.exe main.py

# 模拟页面，不连接游戏
.\.venv\Scripts\python.exe main.py --preview

# 离线回归，不发送真实游戏输入
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v

# 实际 Tk 控件、模拟任务检查
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/smoke_ui.py
```

## 代码职责

根目录 `main.py` 调用 bootstrap，导入包不会自动设置 DPI 或启动界面。具体 DPI 初始化在启动/运行入口执行。

| 位置（相对 `bd2_fishing/`） | 职责 |
| --- | --- |
| `bootstrap.py` | 日志、异常处理、DPI 与桌面启动 |
| `app/desktop.py`、`app/service.py` | 页面使用的设置与任务服务、单任务工作线程 |
| `app/session.py`、`app/ocr_setup.py` | 聚焦、COM、电源、OCR 初始化与每次运行资源收尾 |
| `app/fishing_task.py` | 当前钓鱼任务协调、策略选择与等待上钩；可注入截图工厂 |
| `game/islands/catalog.py`、`reading.py`、`travel.py` | 现有地点与别名、地点信息识别、原地图往返刷新 |
| `game/navigation/actions.py` | 共享的相对坐标点击原语，尚未建立完整页面导航 |
| `game/inventory/` | 背包文本判断、清包与退出检查 |
| `game/fishing/actions.py`、`cast_feedback.py` | 抛竿、位置恢复与抛竿提示判断 |
| `game/fishing/qte.py`、`perception/image.py` | 原 QTE 策略与图像/阈值工具；输入条件、等待和顺序保持原样 |
| `game/fishing/feedback_rules.py`、`settlement_rules.py` | 可独立导入的反馈归属和整条鱼结果规则 |
| `game/fishing/feedback.py`、`settlement.py`、`hook_diagnostics.py` | 游戏反馈/结算观察与上钩证据采集协调 |
| `game/fishing/assets/` | 运行时识别模板，与测试样本分开 |
| `runtime/` | 取消、输入锁、轮次上下文、几何与设备合同 |
| `perception/` | 通用图像、文字、OCR 类型与读取合同调用；不依赖游戏或具体设备 |
| `game/observation.py` | 当前游戏的 OCR 场景区域与会话设置 |
| `game/fishing/recognition.py`、`tracing.py` | 反馈字形共享识别、QTE 统计与生命周期观察 |
| `infrastructure/windows/` | DXcam/GDI、显示器、窗口、受控输入、桌面和电源实现 |
| `infrastructure/ocr/` | RapidOCR 引擎适配 |
| `infrastructure/settings.py`、`paths.py` | INI、默认配置、保留注释的保存及运行路径 |
| `infrastructure/diagnostics/` | 文件日志、PNG/ZIP 与结算证据队列；写入线程由写入模块持有 |
| `ui/window.py` | Tk 控件和展示，配置与任务通过应用服务访问 |

`runtime` 不导入 app、game、ui 或 infrastructure；UI 不直接导入设备或玩法实现。规则和地点目录可在没有 Windows/Tk/OCR 引擎的进程中导入。现有功能执行仍有具体受控输入和观察设备依赖，尚未将所有 I/O 都改为注入；这些边界继续按实际替换需求提取，不为迁移新建空框架。

录制工具通过 `run_once(..., capture_factory=...)` 选择原相机或录制相机，取消与工作线程生命周期保持一致。按键录制和探针仍有局部包装，不能当成已经具备完整离线回放框架。

## 路径与包装

- 可编辑安装使用 `.local/config.ini`，日志写入 `.local/logs/`，证据写入 `.local/diagnostics/`；路径不随工作目录变化。
- 普通安装的运行目录为用户主目录下 `BD2_AutoFishing/`，避免向 site-packages 写入；唯一默认配置由 settings 从 `resources/default.ini` 包资源读取。
- 便携版继续使用 EXE 旁的用户配置和日志；自定义 OCR 相对资源从冻结资源目录解析。
- 运行时模板随 Python 包和 PyInstaller 收集。包资源与运行目录分开；本机部署已成套归入外层 `deployment/`，未升级 EXE。
- `.local/` 集中配置和生成物，egg-info 及 setuptools 中间文件由 setup.py 固定写入 `build/`；`.venv/` 和 Python 缓存按正常行为生成并忽略。原图与证据保留；完整规则见[统一布局](../design/repository-layout.md)。

## 修改与验证

[开发规范与检查门槛](standards.md)规定依赖方向、格式、公共逻辑归属和时延边界。提交前运行 Ruff、架构检查和相关回归；CI 在 push/PR 时执行相同检查。

行为约束见 [AGENTS.md](../../AGENTS.md)。修改识别使用真实正负例，停止仍穿过普通业务异常捕获；保持输入锁和窗口保护。

现有回归覆盖按键条件、停止/重启、清包开关、恢复、截图、日志和证据。新增架构测试覆盖导入边界、轻量规则导入、截图工厂注入和桌面服务。涉及打包时同时检查 wheel、便携包模板、OCR 模型及 Tcl/Tk；源码和构建验证不代表 EXE 已实机验收。

QTE 关键路径没有增加消息队列、线程跳转或输入暂停修改。三个策略类在归一化导入引用后 AST 与迁移前一致；这证明实现表达式保持一致，不替代[端到端时延实测](../design/qte-performance.md)。

工具影响范围见[工具说明](tools.md)，发布流程见[构建与发布](releasing.md)。提交和推送从源码仓库执行，外层旧 Git 已归档到 archive，不能从旧实验工作树推送旧结构。
