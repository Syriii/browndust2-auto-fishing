# 工作区与仓库统一布局

[文档目录](../README.md) · [程序架构](architecture.md) · [开发指南](../development/guide.md)

状态：2026-09-08 已实施。目录按文件用途、维护者和生命周期划分。游戏运行流程由应用层组织，不决定仓库顶层结构。

## 本机工作区

```text
BD2_AutoFishing/
├── README.md / AGENTS.md     本机导航与工作边界
├── auto_fishing-dev/         唯一在用的 GitHub 源码仓库
├── deployment/             当前使用的 EXE、运行库、配置、日志和旧 debug
└── archive/                 旧 Git、实验工作树、旧记录及迁移清单
```

GitHub 仓库根目录就是 auto_fishing-dev 的内容，不上传外层部署和归档。外层原 Git 已保存为 `archive/git/legacy-workspace.git`，同时保留完整 bundle 与工作区差异；实验 worktree 已归档并修复关联。历史仍可读取，不再与源码仓库混用。

deployment 直接保存用户正在使用的版本，没有 current 子目录、自动版本切换或自动历史保存机制。候选构建留在源码 `dist/`。两者之间只有明确的发布操作，不由普通构建自动覆盖。现有部署只迁移位置，EXE、运行库、配置与证据保持原内容。

## 源码仓库

```text
auto_fishing-dev/
├── README.md / AGENTS.md     快速开始与开发约束
├── pyproject.toml           包元数据、直接依赖、入口和资源清单
├── main.py                  桌面薄入口
├── setup.py                 setuptools 构建路径适配，不定义重复元数据
├── bd2_fishing/
│   ├── __init__.py          Python 包标识
│   ├── bootstrap.py         桌面启动组装
│   ├── app/                 任务、跨功能协调与资源组装
│   ├── game/                本游戏的功能和规则
│   │   ├── islands/         岛屿资料、地点读取与地图往返
│   │   ├── navigation/      页面操作基础能力，完整导航待扩展
│   │   ├── fishing/         钓鱼、QTE、反馈、结算与统计
│   │   │   └── assets/      运行时识别模板
│   │   └── inventory/       背包识别与清理
│   ├── perception/          跨功能图像与文字处理、OCR 数据和读取
│   ├── runtime/             取消、输入互斥与最小设备合同
│   ├── infrastructure/      具体平台、引擎与存储实现
│   │   ├── windows/         窗口、截图、受控输入和电源
│   │   ├── ocr/             RapidOCR 引擎适配
│   │   └── diagnostics/     后台日志及诊断证据写入
│   ├── ui/                  桌面展示
│   └── resources/default.ini  唯一默认配置
├── tests/
│   ├── unit/                规则、判定和局部行为回归
│   ├── integration/         跨模块协作、设备适配与包装回归（模拟依赖）
│   ├── fixtures/            有来源的真实回归样本
│   └── support.py           测试共用路径，不读取个人配置
├── scripts/
│   ├── build_release.py     Windows 便携包构建
│   ├── lock_environment.py  从验证环境生成依赖锁定清单
│   ├── benchmarks/         离线图像和日志时延基准
│   ├── checks/             架构检查、页面模拟、只读截图检查
│   └── live/               会控制游戏的诊断、录制和清包工具
├── requirements/            Windows Python 3.12 完整依赖锁定清单
├── docs/
│   ├── user/               使用、配置与故障排查
│   ├── development/        安装、验证、工具、发布与当前状态
│   ├── design/             架构、仓库布局、QTE 时延设计
│   ├── reference/          游戏机制、封面原图与外部依据
│   └── history/            按时间保存的旧实测记录
├── .github/workflows/       Windows 离线回归与发布构建
├── build/                  构建中间物和 egg-info，不提交
├── dist/                   候选便携程序目录和发布 ZIP，不提交
├── .venv/                  本机 Python 环境，不提交
└── .local/                 本机配置和生成物，不提交
    ├── config.ini           源码用户配置
    ├── logs/               日志与故障日志
    ├── diagnostics/        上钩、QTE、结算及录制证据
    ├── benchmarks/         离线基准结果
    ├── cache/              开发工具缓存
    └── maintenance/        本次迁移备份、清单和验证日志
```

bd2_fishing 内职责与允许的依赖见[程序架构](architecture.md)。尚未实现的完整导航、岛屿目录和机制组合不预建空目录；功能达到需要独立维护的规模时再拆包。

## 配置、资源与运行数据

| 内容 | 唯一归属 | 维护规则 |
| --- | --- | --- |
| 默认配置 | `bd2_fishing/resources/default.ini` | 随 wheel/便携包发布，代码通过资源 API 读取，不再复制整份字符串 |
| 个人源码配置 | `.local/config.ini` | 初次运行生成；已有值和注释保留；不提交 |
| 便携版配置 | EXE 旁的 `config.ini` | 独立于源码；打包不读取个人源码配置 |
| 识别模板 | `game/fishing/assets/` 等所属功能包 | 运行必需，随包收集 |
| 测试样本 | `tests/fixtures/` | 有来源、正负例与回归用途，不作为运行依赖 |
| 游戏封面资料 | `docs/reference/images/` | 保留用户原图与可见信息；资料不等于已实现导航模板 |
| 日志和现场证据 | `.local/logs/`、`.local/diagnostics/` | 有回归价值的样本经整理后复制到 fixtures |
| 依赖 | pyproject 声明，requirements 生成锁定 | 不再维护另一份手写 requirements.txt |

开发路径不随终端当前目录变化。普通 wheel 安装使用用户主目录的 `BD2_AutoFishing/` 保存配置，下设 logs 和 diagnostics；新便携版在 EXE 旁保存配置、日志及 diagnostics；旧部署的 debug 原样保留。自定义 OCR 相对资源仍从仓库或冻结资源目录解析，配置迁移不改变资源含义。

`.venv/` 含绝对路径，原位保留；以后重建环境再按标准命令生成。Python 缓存仍按解释器正常行为生成。setuptools 的 egg-info 统一位于 `build/`，普通 wheel 中间文件位于 `build/setuptools/`；setup.py 仅准备路径并调用构建后端，元数据和依赖仍由 pyproject 维护。

## 自动维护规范

Ruff 统一检查与格式化，静态架构检查限制反向依赖并检测模块循环，Windows CI 在 push/PR 时执行；具体命令见[开发规范](../development/standards.md)。

## 新文件如何归类

- 新岛屿资料与读取器归 game/islands；页面转换归 game/navigation；钓鱼机制归 game/fishing；跨功能任务归 app。
- 应用与复用实现归 bd2_fishing，开发脚本只负责参数和调用，不能把业务逻辑藏进 scripts。
- 离线规则回归放 unit，模拟跨模块协作放 integration，真实游戏操作只从 scripts/live 显式执行。未来录制回放规模足够时再建立 replay 测试组。
- 操作方法归 user，开发步骤归 development，设计目标和取舍归 design，外部游戏事实与来源归 reference。历史文档保留当时结论，最新结果归 development/status。
- 调试散图、临时脚本与构建日志放 `.local/`，不在根目录新建 debug、output、temp 等并列目录。

## 本次迁移与验证

保留原用户配置、日志、证据和源码备份；旧开发记录归本机 archive。部署迁移前后 1177 个文件大小和 SHA256 全部一致。离线回归、Tk 模拟检查与打包资源核对见[当前开发状态](../development/status.md)。

迁移不调整 QTE 等待、按键顺序、HSV 阈值或游戏策略。端到端低时延仍需按[QTE 验收设计](qte-performance.md)单独实测，目录整理不等于性能优化完成。
