# 2026 年 9 月结构调整记录

[文档目录](../README.md) · [当前状态](../development/status.md)

以下保留前几轮结构调整时的实现、路径和验证记录。当前结构以[统一布局](../design/repository-layout.md)为准；旧 debug 记录和源码备份已归入本机 archive/development/2026-09-08/debug。历史中的“未迁移”“尚未单源化”等只对应当时状态。

## 历史阶段：首次目录归类

业务模块与 OCR、识别模板归入 `bd2_fishing/`；根目录保留启动和构建入口。导入、日志分类、测试补丁目标及打包资源路径同步迁移，源码配置和日志仍位于仓库根目录。

README 改为快速开始和导航；使用、配置、诊断、开发、工具、发布、机制参考与历史分别维护。重复配置表移除，过时状态保留在历史档案并明确标注。

验证：122 项离线回归通过，包含新增的源码工作目录独立性、冻结程序配置/资源路径及构建模板清单检查。实际 Tk 模拟检查通过两次启停、设置保存与应用、日志筛选和最小窗口布局。完整 PyInstaller 构建成功；核对全部 19 个业务模块、6 张模板与源码逐字节一致、3 个 OCR 模型及 Tcl/Tk 均在包内，ZIP 完整性检查通过。

对迁移前后的业务模块进行 AST 对比，除导入和 `utils.py` 的配置/资源路径适配外，无业务逻辑变化。16 份 Markdown 的 66 个本地链接检查通过。构建和测试日志分别位于本地 `debug/structure-build.log`、`debug/structure-tests.log`。

此次不调整钓鱼策略、HSV 数值和用户配置；没有真实游戏实测、启动新 EXE 验收或覆盖已有发布版。整理结果保留在本地工作区，尚未提交和推送 GitHub。

## 历史阶段：架构重新规划

上述目录归类没有完成职责分离：包内仍然平铺，配置、截图、识别、规则与写盘仍有混合依赖。修订的[架构方案](../design/architecture.md)面向岛屿玩法拓展，按岛屿、导航、钓鱼和背包等功能组织，共享运行控制与设备实现。设计依据见[源码审视与外部参考](../reference/python-project-architecture.md)。

用户指出游戏已有 6 个岛屿，当前代码仅登记 5 个地点；第六岛资料与自动操作支持尚未补齐。现有往返刷新不是完整岛屿导航；从开始页进入、更多信息读取及新机制均属于后续能力，不能从当前策略映射推导为已支持。

首轮架构已落地，当前模块入口见[开发指南](../development/guide.md)。下面记录本轮验证，前一轮 122 项测试和旧构建记录保留用于追溯。

QTE 低时延已列为架构验收条件，见[时延设计与验收](../design/qte-performance.md)。静态核对发现循环等待、驱动默认暂停、按键前反馈锁及同步文件日志等需要测量的耗时来源；本轮未修改执行参数，尚未建立端到端性能基线，不能声称已达到某个毫秒指标。

## 历史阶段：首轮架构实施

- 源码迁入 `src/bd2_fishing/`，建立可编辑安装、普通 wheel 和桌面入口；运行依赖继续由现有固定版本清单提供，没有升级依赖。
- 拆分配置/路径/窗口/截图/图像工具，拆分抛竿/背包/地图往返；游戏地点与业务识别移出 OCR 引擎模块。
- 反馈和整条鱼结果规则可独立导入，PNG/ZIP 写入归基础设施，结算写入模块持有唯一队列和线程状态。
- UI 通过应用服务访问设置与创建任务；运行控制不导入具体设备，OCR 和截图具有最小合同，截图工厂可注入录制工具。
- 迁移前 122 项回归通过，迁移后 126 项通过；新增验证覆盖导入边界、无原生库的规则导入、截图工厂注入与设置服务。Tk 模拟检查通过两次启停、设置保存/应用、日志筛选和最小窗口布局。
- 三个 QTE 策略类归一化导入引用后 AST 一致，默认配置内容一致。循环等待、驱动暂停、阈值和按键条件未修改。
- wheel 与 PyInstaller 构建成功；普通安装在仓库外工作目录通过导入、模板读取和运行路径检查。便携包核对 57 个包/模块、6 张逐字节一致的模板、3 个 OCR 模型、Tcl/Tk 与压缩包完整性。首次沙箱构建未能读取 Tcl/Tk，已在可访问运行库的环境中重建并核对。
- 本地日志：`debug/architecture-tests.log`、`debug/architecture-ui.log`、`debug/architecture-build.log`、`debug/architecture-behavior-audit.txt`、`debug/architecture-package-audit.txt`。源码迁移前备份保存在 `debug/architecture-before.zip`。15 份文档的 88 个本地链接通过检查。

本轮没有连接游戏实测、启动新 EXE 或覆盖已有发布版；也未提交或推送 GitHub。第六岛、完整导航和新机制仍未实现；完整设备注入、配置快照与时延优化继续按实际需求推进。

## 历史阶段：全工作区统一整理

- 本机外层分为 auto_fishing-dev、deployment/current 和 archive。旧 Git 元数据、完整历史 bundle、未提交差异及实验 worktree 一并归档，worktree 关联路径已修复；GitHub 源码仓库提交与远程保持原样。
- 源码根目录保留入口、包配置及导航文件；scripts 按 checks/live 分组，tests 按 unit/integration 分组，docs 按 user/development/design/reference/history 分组。详细规则见[统一布局](../design/repository-layout.md)。
- 默认配置合并为 resources/default.ini 一份包资源；个人配置、日志、诊断和构建产物统一归入 .local，旧开发记录归档。原个人配置与用户封面图逐字节保留。
- 直接依赖和构建工具由 pyproject 声明，34 项完整 Windows Python 3.12 依赖从现有验证环境生成锁定文件，未升级依赖；CI 使用相同锁定和构建路径。
- 127 项离线回归通过，包含新默认配置生成及已有个人配置不被覆盖的回归。Tk 模拟检查通过，不连接游戏。wheel 普通安装从仓库外通过包导入、默认配置生成、模板与用户路径检查。
- PyInstaller 核对全部 57 个包/模块、6 张逐字节一致模板、唯一默认 INI、3 个 OCR 模型、Tcl/Tk；wheel 与便携 ZIP 完整性通过。构建脚本新增 GUI 运行库缺失检查。
- QTE 策略文件与本次整理前备份逐字节一致，未修改循环等待、驱动暂停、按键顺序或阈值。端到端时延基线仍未实测。
- 旧版 EXE 已在用户退出后成套迁入 deployment/current，1177 个文件大小与 SHA256 前后一致；这是位置迁移，没有用新构建升级它。旧快捷方式需要更新 EXE 目标路径。

本轮日志与备份位于 `.local/maintenance/`：layout-tests.log、layout-ui.log、layout-build.log、layout-package-audit.txt、before-workspace-layout.zip 与 workspace-moves.json。本机 archive 另保存部署哈希和完整迁移清单。

没有真实游戏实测、启动新 EXE 验收、提交或推送。第六岛、开始页导航、信息读取扩展及新机制仍是后续工作，本次完成整体结构归类与路径配套。

前几轮目录迁移和架构验证见[结构调整历史](../history/structure-2026-09.md)。
