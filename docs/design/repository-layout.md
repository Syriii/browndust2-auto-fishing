# 源码、发布包与运行数据布局

[文档目录](../README.md) · [架构说明](architecture.md) · [更新说明](../user/updating.md)

目录按用途和生命周期组织。GitHub 上的源码仓库、用户解压的便携包、维护者本机工作区是三个不同层次。

## GitHub 源码仓库

```text
repository/
├── README.md                 项目介绍与快速开始
├── CHANGELOG.md              发布版本变化
├── AGENTS.md                 项目开发约束
├── pyproject.toml            包元数据、依赖、资源和工具配置
├── main.py                   桌面启动入口
├── setup.py                  setuptools 构建路径适配
├── bd2_fishing/
│   ├── bootstrap.py          启动组装
│   ├── app/                  用户任务、设置、校准、更新与资源组装
│   ├── game/
│   │   ├── islands/          地点资料、文字读取与已有地图往返
│   │   ├── navigation/       页面操作基础能力，完整导航待扩展
│   │   ├── fishing/          抛竿、QTE、反馈、结算与统计
│   │   │   ├── mechanics/    同帧区域、纯状态与决策
│   │   │   └── assets/       运行时识别模板
│   │   └── inventory/        背包判断与清理
│   ├── perception/           通用图像、OCR 合同与文字处理
│   ├── runtime/              取消、输入锁、几何与设备合同
│   ├── infrastructure/
│   │   ├── windows/          窗口、截图、原生输入和电源
│   │   ├── ocr/              RapidOCR 适配
│   │   ├── diagnostics/      后台日志及证据写入
│   │   └── updates/          清单、下载、更新事务与助手
│   ├── ui/                   主窗口、设置、日志、更新与主题
│   └── resources/            default.ini、应用图标
├── tests/
│   ├── unit/                 局部规则和行为回归
│   ├── integration/          跨模块、资源和包装回归
│   └── fixtures/             有来源的真实回归样本
├── scripts/
│   ├── build_release.py      便携包构建
│   ├── lock_environment.py   依赖锁定生成
│   ├── benchmarks/          离线局部时延测量
│   ├── checks/              规范、界面、包与只读截图检查
│   └── live/                会操作游戏的诊断、录制及清包工具
├── requirements/             Windows Python 3.12 完整锁定清单
├── docs/
│   ├── user/                 用户操作
│   ├── development/          开发、验证、工具和发布
│   ├── design/               架构与专项设计
│   ├── reference/            外部资料与来源
│   └── history/              按阶段保存的旧记录
└── .github/workflows/        Windows CI 与 Release 构建
```

`bd2_fishing/` 是独立应用的内部包，不需要额外 `src/` 层，也不把构建产物放入应用包。更细的职责和实际依赖方向见[架构说明](architecture.md)。图中省略了部分模块文件，不表示它们未纳入仓库。

## 开发过程中生成的目录

以下位于源码仓库内，均不提交：

```text
.venv/                       本机虚拟环境
.local/
├── config.ini               源码个人配置
├── data/                    环境与校准报告
├── logs/                    源码日志
├── diagnostics/             上钩、QTE、结算及录制证据
├── benchmarks/              局部时延报告
├── cache/                   工具缓存
└── maintenance/             调试分析、校验报告和临时工具
build/                       构建中间物、spec、egg-info 与 wheel
dist/
├── BD2_AutoFishing/          本机完整便携目录
├── BD2_AutoFishing-windows.zip
├── BD2_AutoFishing-windows.zip.sha256
└── README.txt               维护者整理的本次交付说明（非构建自动生成）
```

`build/` 是中间产物，`dist/` 是本机候选/交付产物，GitHub Release 的 Assets 是公开下载产物。相同源码的本机和云端构建不保证二进制哈希相同，验收记录实际包版本与哈希。

`dist/` 最终保留一套当前产物；临时候选可使用构建的 `--output-dir`，验证后再整理。旧候选及附带日志归维护者的历史目录，不能直接批量删除证据。构建不自动清理所有旧版本，也不覆盖当前部署，详见[构建与发布](../development/releasing.md)。

## 用户便携目录

首次下载并完整解压后，程序文件和后续生成的数据共同位于独立文件夹：

```text
BD2_AutoFishing/
├── BD2_AutoFishing.exe       主程序
├── BD2_Updater.exe           独立更新及恢复助手
├── _internal/               Python、Tk、OCR 与其他运行依赖
├── manifest.json            版本及程序文件清单
├── config/config.ini        用户设置，首次运行生成
├── data/                    环境与校准报告
├── logs/                    运行日志
├── screenshots/             异常与场景证据
│   └── keep/                手工保留的证据
└── cache/updates/            下载、暂存及恢复数据
```

Release ZIP 包含程序文件，个人数据按需生成。主程序运行库持久放在 `_internal/`，不在每轮钓鱼时解压。更新助手内部的临时运行环境只服务更新进程，详见[更新设计](portable-update.md)。

程序按清单处理依赖更新与过期文件，用户不需要逐个复制 DLL。设置和证据不属于程序文件清单；更新保留这些数据，日志与截图按独立保留规则清理。移动整个目录即可迁移，删除整个目录即可卸载并删除其中个人数据。首次旧版迁移见[用户更新说明](../user/updating.md)。

## 文件归属规则

| 内容 | 维护位置 | 规则 |
| --- | --- | --- |
| 默认配置 | `bd2_fishing/resources/default.ini` | 唯一默认来源，随包提供；不从个人配置构建 |
| 图标、模板与模型 | 应用资源及所属玩法 | 运行必需，构建检查完整性 |
| 回归样本 | `tests/fixtures/` | 记录来源、用途和正负例，不直接作运行模板 |
| 游戏封面与资料 | `docs/reference/` | 来源和观察结论分开，不等于已支持导航 |
| 新玩法、新岛屿、机制 | `game/` 对应功能 | 跨功能任务归 app，不按运行步骤拆顶层 |
| 调试散图、临时脚本 | `.local/maintenance/` | 不向根目录增加 debug/output/temp 等目录 |
| 用户操作与当前能力 | docs/user、development/status | 随实现更新；过程记录归 history |

普通 wheel 安装的运行根是用户目录 `BD2_AutoFishing/`，用于仓库外运行而不写入 site-packages；完整路径表见[开发指南](../development/guide.md#运行数据与资源)。

## 维护者本机工作区（不属于分发结构）

```text
BD2_AutoFishing/
├── auto_fishing-dev/         唯一在用的 Git 仓库，即上文 repository
├── deployment/              维护者当前运行的已部署程序与个人数据
└── archive/                 旧 Git、工作树、构建和历史证据
```

普通贡献者只需克隆源码，用户只需解压 Release，无需复刻这套外层目录。`deployment/` 没有 `current/` 子目录，也不是自动版本存档；明确执行本机部署时才成套更新。普通构建、推送和创建 GitHub Release 都不会自动覆盖它。

旧 Git、实验工作树和迁移清单仍保留于维护者 archive；日常开发只在源码仓库进行。迁移过程见[结构历史](../history/structure-2026-09.md)，不把当地路径写成通用安装要求。
