# 棕色尘埃 2 自动钓鱼

面向 **BrownDust II / Fishing Voyage** 的 Windows 钓鱼助手，通过截图、图像识别和 OCR 判断游戏状态，执行抛竿、QTE 与结算处理。

[下载最新正式版](https://github.com/Syriii/browndust2-auto-fishing/releases/latest) · [使用指南](docs/user/usage.md) · [更新记录](CHANGELOG.md) · [完整文档](docs/README.md)

**版本说明：** 当前源码版本为 **0.3.9**，包含黄条实体分组与绿色区域分离修复；旧 0.3.8 EXE 不含这两项改动。下载包版本与验证范围以对应 Release 为准，源码与本机交付记录见[当前状态](docs/development/status.md)。

## 快速开始

1. 从 Release 的 **Assets** 下载 `BD2_AutoFishing-windows.zip`，完整解压到独立文件夹。
2. 运行其中的 `BD2_AutoFishing.exe`。无需安装 Python，首次启动自动生成配置并检测环境。
3. 在游戏中进入 Fishing Voyage 码头、选岛页或钓场，将游戏窗口完整放在一块显示器上；已在钓场时站到可以抛竿的位置。
4. 在助手中核对当前钓场和选项，点击左下角 **开始钓鱼**。同一个按钮切换为 **停止任务**。

**满包时自动清理默认开启，会出售背包物品。** 不希望自动出售时，先取消勾选；此后检测到满包会停止。

程序启动后保持待机。任务运行时游戏需要保持前台可见；失焦、锁屏、移动、缩放或最小化游戏窗口会停止任务。恢复窗口后需手动重新开始。

下载完整 Windows ZIP；GitHub 的 `Source code` 是源码。主 EXE、`BD2_Updater.exe`、`_internal/` 和 `manifest.json` 需要成套保留。旧版迁移见[更新说明](docs/user/updating.md#手动更新)。

## 当前能力

| 能力 | 支持范围 |
| --- | --- |
| 钓鱼任务 | 从钓鱼待机、等待或 QTE 接续，处理鱼获、升级及运行中的 150302 提示；页面恢复可持续观察并间隔重试，150402 退出重进待长期验证 |
| 钓场识别与选择 | 源码已登记六个钓场（含天空岛）；可从码头/地图进入所选岛屿，不自动购买许可证。天空岛暂用通用策略，尚待实测 |
| QTE 与特殊场景 | 黄区优先、仅蓝区回退、明暗指针区分、泡泡独立去重、红紫/贝壳避让；绿色范围外可继续判断普通目标，真实绿色起按端仍未确认 |
| 设备与时延设置 | 客户区自动适配或尺寸核对、手动时延设置、本机基础等待校准；建议值显示在输入框旁 |
| 运行记录与截图 | 钓鱼和日志同屏；失败、未确认结果、异常及特殊外观自动留证，不要求开启调试模式 |
| 更新与存储 | 正式 Release 在线更新、本地 ZIP 导入、配置保留及待机日志/截图清理 |

目前只支持 Windows x64。六钓场目录和码头/选岛导航已接入；从游戏开始页进入玩法、天空岛专属机制、完整玩法资料读取，以及全部特殊机制的识别和解除确认仍未完成。自动缩放与离线回归不等于所有分辨率和电脑均已实测；不能保证每次 QTE 或每条鱼都成功。

2026-09-14 全量审查通过 574 项离线回归、Ruff、架构和隐藏界面检查，同时发现 **8 项待修问题**，包括清包页面确认、手动工具失焦保护、证据保留目录大小写、启动弹窗处理及配置/更新缓存容错。清包仍按固定坐标执行；启动前已存在的 150302 提示需手动关闭；保留证据的目录请使用小写 `keep`。问题位置、复现条件和优先级见[代码审查报告](docs/development/code-review-2026-09-14.md)。

## 设置、更新与数据

左侧 **设备与时延设置** 打开右侧设置表单，建议需手动采用并保存。基础校准可以在没有打开游戏时运行，用来测量本机等待精度，不会自动找出游戏命中率最优参数。

运行记录下方的 **更新与存储** 支持检查正式新版或导入本地 ZIP。在线更新失败时，可用浏览器从 Release 下载 ZIP，再在程序中选择该文件，无需解压。更新会保留配置和运行数据。

| 便携程序目录内的位置 | 内容 |
| --- | --- |
| `config/config.ini` | 个人配置 |
| `data/` | 环境检测与校准报告 |
| `logs/` | 运行日志 |
| `screenshots/` | 异常、QTE 和结算证据 |
| `screenshots/keep/` | 手工保留、免于自动清理的证据 |
| `cache/updates/` | 更新下载与恢复数据，由程序维护 |

完整目录、清理规则及旧版配置导入见[便携版更新与数据保留](docs/user/updating.md)。

## 开发与项目结构

本项目是独立桌面应用，使用仓库根目录下的 `bd2_fishing/` 统一内部导入；无需额外的 `src/` 层。

```text
bd2_fishing/       应用服务、游戏能力、通用识别、运行控制、平台实现与界面
tests/             单元与集成回归、真实截图样本
scripts/           构建、检查、基准与实机工具
requirements/      Windows Python 3.12 依赖锁定
docs/              用户、开发、设计、参考和历史文档
.github/workflows/ CI 检查与 Release 构建
main.py            桌面启动入口
pyproject.toml     包元数据、依赖与工具配置
setup.py           构建路径适配
```

源码运行的个人数据位于 `.local/`；中间产物位于 `build/`，本机构建包位于 `dist/`。这些目录以及 `.venv/` 不上传 GitHub，与用户解压后的便携目录用途不同。

开发使用 Windows Python 3.12 与仓库锁定依赖；首次安装后可运行：

```powershell
.\.venv\Scripts\python.exe main.py --preview
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/check_architecture.py
```

`--preview` 使用模拟任务，不连接游戏。实机工具位于 `scripts/live/`，会发送游戏输入；其中清包工具会出售物品。构建命令生成 `dist/` 产物，不会自动更新维护者的 `deployment/`。

开发环境、安装和检查命令见[开发指南](docs/development/guide.md)，目录职责见[统一布局](docs/design/repository-layout.md)，实际依赖与扩展方向见[架构说明](docs/design/architecture.md)。日常采用 `main` 与短期分支；合并不自动发布，版本通过标签和 Release 保留，详见[分支约定](docs/development/branching.md)。

## 文档导航

| 要做什么 | 文档 |
| --- | --- |
| 开始钓鱼、处理满包与窗口问题 | [使用指南](docs/user/usage.md) |
| 调整分辨率、时延和配置 | [配置说明](docs/user/configuration.md) |
| 查找报错截图、提交有效证据 | [日志与诊断](docs/user/diagnostics.md) |
| 下载、更新、迁移和清理 | [更新说明](docs/user/updating.md) |
| 查阅版本变化与待验证项 | [CHANGELOG](CHANGELOG.md) · [验证计划](docs/development/validation-plan.md) |
| 修改源码、构建或发布 | [开发指南](docs/development/guide.md) · [构建与发布](docs/development/releasing.md) |
| 查阅本轮代码问题与修复顺序 | [2026-09-14 全量审查](docs/development/code-review-2026-09-14.md) |
| 确认此前问题是否解决、修复是否入包 | [历史问题逐项复核](docs/development/issue-status-2026-09-14.md) |
