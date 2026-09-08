# 文档目录

[返回项目首页](../README.md)

## 使用

- [使用指南](user/usage.md)：启动、停止、钓场、满包、多显示器和常见问题。
- [配置说明](user/configuration.md)：配置位置、界面保存规则与各配置段用途。
- [日志与诊断](user/diagnostics.md)：上钩超时、QTE 反馈、决策证据和整条鱼结算。

## 设计

- [工作区与仓库统一布局](design/repository-layout.md)：源码、部署、归档、默认配置、脚本、测试与文档的完整归属。
- [架构规划](design/architecture.md)：面向岛屿玩法的功能边界、岛屿与机制扩展及迁移范围；首轮职责拆分已实施，后续目标单独标明。
- [QTE 时延设计与验收](design/qte-performance.md)：关键路径、帧新鲜度、输入暂停、后台争用与性能基线；尚未完成时延实测。

## 开发与发布

- [开发规范与检查门槛](development/standards.md)：模块边界、公共逻辑、Ruff、CI 与时延要求。
- [开发指南](development/guide.md)：代码职责、路径约定、环境与离线验证。
- [依赖管理](../requirements/README.md)：声明来源与 Windows 锁定清单。
- [工具说明](development/tools.md)：每个工具的用途、输入影响和运行命令。
- [构建与发布](development/releasing.md)：OCR 模型、PyInstaller、GitHub Actions 与部署验收。
- [当前开发状态](development/status.md)：当前能力、验证边界、暂缓事项与本轮整理记录。
- [已验证功能的正式代码核对](development/verified-features.md)：历史测试到当前实现的对应关系、合入结论和未覆盖范围。

## 参考与历史

- [Fishing Voyage 封面与页面参考](reference/fishing-voyage.md)：用户提供的游戏封面原图、可见标题及导航识别边界。
- [Python 项目结构参考](reference/python-project-architecture.md)：本地源码审视、官方项目参考、设计取舍与待核实事项。
- [钓鱼机制参考](reference/fishing-mechanics.md)：社区资料与源码覆盖对照，保留来源和读取日期。
- [2026 年 9 月优化与实测记录](history/optimization-2026-09.md)：历史证据档案，不能用其中的旧状态代替当前说明。
- [2026 年 9 月结构调整历史](history/structure-2026-09.md)：前几轮目录与架构迁移的验证记录。
- [测试样本目录](../tests/fixtures/README.md)：离线回归图片的来源和用途。

## 文档维护约定

README 只保留项目介绍、快速开始和入口。行为说明归入使用文档；开发命令和实现职责归入 development；架构目标与取舍归入 design；原始实测记录按月份归档，当前结论汇总到开发状态。

配置默认值只维护在 `bd2_fishing/resources/default.ini`，settings 从资源读取。个人配置位于 `.local/config.ini`，不提交。文档说明含义及关键开关，避免再次复制整套默认值表。修改路径时同步更新代码导入、测试、工具、构建清单和文档链接。
