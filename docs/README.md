# 文档目录

[项目首页](../README.md) · [正式版下载](https://github.com/Syriii/browndust2-auto-fishing/releases/latest) · [更新记录](../CHANGELOG.md)

用户说明以 v0.2.0 及当前实现为基线。当前能力看[开发状态](development/status.md)，未来目标看[架构说明](design/architecture.md)，旧测试与原型仅作为历史依据。

## 使用程序

| 文档 | 内容 |
| --- | --- |
| [使用指南](user/usage.md) | 启停、钓场、满包、窗口与常见问题 |
| [配置说明](user/configuration.md) | 配置路径、设备检测、手动时延和基础校准 |
| [更新与数据保留](user/updating.md) | 首次下载、在线/本地 ZIP 更新、旧版迁移和清理 |
| [日志与诊断](user/diagnostics.md) | 运行记录、异常截图入口、证据分类和排查方法 |

## 开发和发布

| 文档 | 内容 |
| --- | --- |
| [开发指南](development/guide.md) | 环境、已实现模块、源码运行和验证命令 |
| [开发规范](development/standards.md) | 依赖方向、公共逻辑、Ruff、CI 与时延约束 |
| [工具说明](development/tools.md) | 离线检查、只读截图、真实输入和输出位置 |
| [依赖管理](../requirements/README.md) | pyproject 与 Windows 锁定清单 |
| [分支与版本约定](development/branching.md) | main、短期分支、标签与 Release |
| [构建与发布](development/releasing.md) | 便携包构建、附件、更新协议和本机部署 |
| [当前开发状态](development/status.md) | 正式版本、已验证范围与开放问题 |
| [验证计划](development/validation-plan.md) | 后续机制、时延和游戏验收的完成判据 |

## 架构和专项分析

| 文档 | 内容与范围 |
| --- | --- |
| [统一目录布局](design/repository-layout.md) | 源码、便携目录、构建产物及维护者本机工作区 |
| [架构说明](design/architecture.md) | 当前职责、真实依赖、QTE 链路及尚未实施的扩展 |
| [页面识别与启动接续](design/scene-recognition.md) | 当前页面能力、启动分支、未知状态和验证边界 |
| [QTE 时延设计](design/qte-performance.md) | 控制与输入预算、后台争用、待建立的端到端基线 |
| [便携更新设计](design/portable-update.md) | 文件所有权、清单、独立助手和回滚 |
| [特殊机制处理设计](design/special-mechanism-handling.md) | 样本驱动的处理方案与历史设计过程 |
| [机制链审计](development/mechanism-chain-audit.md) | 攻略配图、源码行为与技能处理缺口 |
| [错误分类账](development/error-triage.md) | 历史故障与修复证据，当前待办以验证计划为准 |

## 游戏资料

- [钓鱼机制参考](reference/fishing-mechanics.md)：注明读取日期的社区资料与争议，不视为全部已实现。
- [Fishing Voyage 封面](reference/fishing-voyage.md)：原图、可见标题和页面识别边界。
- [入口、选岛与许可证](reference/voyage-navigation.md)：七张用户原图、页面转换、天空岛购买前后、鱼种解锁与待实现规则。
- [Python 结构参考](reference/python-project-architecture.md)：架构选择的参考依据与当时审视。
- [回归样本](../tests/fixtures/README.md)：真实图片来源和用途；不是运行时模板。

## 历史与设计记录

- [2026 年 9 月开发与发布过程](history/development-2026-09.md)：从原状态页迁出的完整阶段记录。
- [2026 年 9 月优化与实测](history/optimization-2026-09.md)、[目录迁移](history/structure-2026-09.md)。
- [首轮架构方案](history/architecture-2026-09-08.md)：旧路径、原目标和后续追加说明。
- [功能迁移核对](development/verified-features.md)：2026-09-08 的正式代码合入审计，不代表当前测试总数。
- [界面原型及取舍](design/desktop-script-prototype.md)、[已放弃的多页面方案](design/desktop-experience.md)。
- 个案：[a1d435a2](development/cases/2026-09-09-a1d435a2.md)、[b3e84021](development/cases/2026-09-09-b3e84021.md)、[质量与场景复核](development/cases/2026-09-10-quality-and-scenes.md)。

## 维护约定

README 保留介绍、快速开始和入口；操作归 user，开发步骤和验证归 development，设计与取舍归 design，外部资料归 reference，时间线归 history。当前状态页只保留最新结论和证据入口，不继续追加每次调试的流水记录。

行为以源码和发布版本为准。默认值唯一来源为 [default.ini](../bd2_fishing/resources/default.ini)；文档仅摘录关键设置。个人配置不提交：源码在 `.local/config.ini`，便携版在 EXE 旁的 `config/config.ini`。

变更用户行为时同步使用文档，变更路径时检查源码、脚本、构建清单和链接。纯文档改动可以合并 main，无需改版本号、移动标签或重新发布 EXE。历史证据保留当时结果，并标明适用日期。
