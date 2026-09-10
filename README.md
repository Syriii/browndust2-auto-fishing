# 棕色尘埃 2 自动钓鱼

Windows 桌面工具，通过截图、OCR 和 QTE 判断控制钓鱼。程序打开后保持待机，在页面点击 **开始钓鱼** 才运行，点击 **停止任务** 结束。支持钓场选择、满包处理、日志与失败诊断。

当前策略仍有特殊机制覆盖限制，不能保证每条鱼捕获成功。能力边界见[开发状态](docs/development/status.md)和[机制参考](docs/reference/fishing-mechanics.md)。

## 快速开始

普通用户从 [Releases](https://github.com/Syriii/browndust2-auto-fishing/releases) 下载
`BD2_AutoFishing-windows.zip`，解压到独立文件夹后运行 `BD2_AutoFishing.exe`。
首次运行生成配置，后续可在“更新与存储”中在线更新或选择本地 ZIP。
下载附加的 Windows 发布包；GitHub 自动提供的 Source code 压缩包用于开发。
旧版迁移和目录用途见[更新说明](docs/user/updating.md)，版本变化见[更新记录](CHANGELOG.md)。

开发者从源码运行：

使用 Windows、Python 3.12。在下载或克隆后的仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe main.py
```

已有 `.venv` 时直接使用，无需重新创建。将游戏完整放在一块显示器上，进入可钓鱼的位置，在程序页面选择钓场并开始。任务运行期间游戏需保持前台；切换窗口、锁屏或移动/缩放游戏窗口会停止任务。

自动清包默认开启，满包时会出售背包物品。不希望自动出售时，在页面关闭 **自动清包**；检测到满包后程序停止，等待手动整理。

只预览页面，不连接游戏：

```powershell
.\.venv\Scripts\python.exe main.py --preview
```

如果使用已发布的便携包，从[本仓库 Releases](https://github.com/Syriii/browndust2-auto-fishing/releases)选择实际存在的版本，完整解压后运行 `BD2_AutoFishing.exe`；保留配套 `_internal/`。没有发布包时使用源码或自行[构建](docs/development/releasing.md)。

## 文档

| 要做什么 | 入口 |
| --- | --- |
| 启停任务、选择钓场、处理满包与多屏 | [使用指南](docs/user/usage.md) |
| 调整配置和了解保存规则 | [配置说明](docs/user/configuration.md) |
| 排查上钩超时、QTE 失误与捕获结果 | [日志与诊断](docs/user/diagnostics.md) |
| 修改源码、运行回归 | [开发指南](docs/development/guide.md) |
| 了解模块边界和下一步重构 | [架构规划](docs/design/architecture.md)（已完成首轮职责拆分） |
| 使用页面检查、截图和实测工具 | [工具说明](docs/development/tools.md) |
| 构建 ZIP、发布与部署 | [构建与发布](docs/development/releasing.md) |
| 分支管理、合并与版本标签 | [分支与发布约定](docs/development/branching.md) |
| 查找历史证据或其他文档 | [完整文档目录](docs/README.md) |

## 项目结构

```text
main.py                  桌面启动入口
setup.py                 构建路径适配，元数据仍在 pyproject
pyproject.toml           Python 包元数据与安装入口
bd2_fishing/         应用、玩法、通用识别、运行控制、基础设施与界面
tests/                   单元、集成回归与真实截图样本
scripts/                 构建、环境锁定、检查与实机工具
requirements/            Windows Python 3.12 完整依赖锁定
docs/                    使用、开发、设计、参考与历史文档
.github/workflows/       GitHub 构建流程
```

个人配置、日志与诊断统一放在 `.local/`，构建产物在 `build/`、`dist/`，虚拟环境保留 `.venv/`，均不上传。源码首次启动自动生成 `.local/config.ini`；默认值只维护在包资源 `bd2_fishing/resources/default.ini`。

完整目录归属与扩展规则见[统一布局](docs/design/repository-layout.md)，模块职责见[开发指南](docs/development/guide.md)。

规范与自动检查见[开发规范](docs/development/standards.md)：Ruff 格式与静态检查、模块依赖检查、离线回归均纳入 Windows CI。

## 主要依赖

DXcam 用于控制流程截图，OpenCV/NumPy 处理图像，RapidOCR/ONNXRuntime 识别文字，PyDirectInput/pywin32 提供 Windows 输入和窗口接口，Tkinter 提供页面。确切版本以 [pyproject.toml](pyproject.toml) 与[依赖锁定说明](requirements/README.md) 为准。

## 便携版更新与数据

新版发布采用完整 ZIP；通过界面的“更新与存储”在线下载或选择本地 ZIP 更新，无需手动管理依赖。配置位于 `config/config.ini`，日志与证据分别在 `logs/`、`screenshots/`。完整目录、旧版首次迁移及保留策略见[便携版更新说明](docs/user/updating.md)。
