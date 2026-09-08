# Python 项目结构参考与源码审视

[文档目录](../README.md) · [采用的架构方案](../design/architecture.md)

整理日期：2026-09-08。范围为本地源码、测试、诊断工具和构建入口，以及下列项目的官方文档和部分源码。没有全面审计上游项目；上游链接指向可变化的分支或文档，结论限于本次查阅内容。

## 对本项目的理解

当前包约 4,174 行 Python，含 19 个业务模块及两个包初始化文件；测试目录有 17 个测试文件、122 个测试方法。这是本轮静态检查，不是本轮重新运行测试的结果。

已经阅读启动、任务控制、Windows 会话与输入、DXcam/GDI、OCR、抛竿恢复、清包、地图往返、QTE、反馈、结算、诊断和构建代码，并核对测试与工具的调用方式。

| 观察 | 对设计的影响 |
| --- | --- |
| main 不只是入口，还负责策略选择、等待上钩和恢复协调 | 薄入口、应用任务与玩法内部循环分开 |
| 地点枚举位于 OCR 包，中文值同时用于界面和策略选择 | 游戏身份独立于文字识别和显示名称 |
| 地图转换表是有限的往返关系 | 不将当前刷新能力当成通用导航；新增页面需到达验证 |
| 两种 QTE 策略依赖颜色、坐标、时间和输入状态 | 保留游戏识别的功能归属，在其内部拆出可回放判断 |
| 反馈采样、控制决策截图、结算 OCR 和写盘具有不同时间与线程 | 共享接口不能抹平采样用途；资源所有权和时间元数据必须明确 |
| utils 被多个模块依赖，混合设备、配置和记录 | 先分职责与接口，再移动文件，不能仅换目录名 |
| 部分测试通过 AST 提取函数避开原生依赖，工具需要 monkeypatch 设备和时间 | 应提供轻量导入边界、可替换设备和统一运行服务 |
| 发布需包含 OCR 模型、模板、Tcl/Tk 与原生库 | src 和插件等设计必须同时考虑冻结交付 |

## 外部参考与取舍

以下“采用”是针对本项目的设计判断，不代表上游项目推荐本项目使用相同架构。

| 官方资料或源码 | 查阅内容 | 对本项目的启发与取舍 |
| --- | --- | --- |
| [PyPA：src 与 flat](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) | 两种布局的导入和安装差异 | 采用 src 帮助验证安装产物；增加开发安装步骤。目录布局与业务架构是两个决策 |
| [PyPA：pyproject](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) | 包元数据、依赖与可选依赖 | 统一依赖声明，另外维护可复现安装清单；不顺带升级现有设备依赖 |
| [napari：目录组织](https://napari.org/dev/developers/architecture/dir_organization.html) | 功能组件、模型与 GUI 实现的分离 | 相关功能保持集中，隔离桌面框架导入；无需照搬 Qt、层模型或其全部目录 |
| [Home Assistant：集成结构](https://developers.home-assistant.io/docs/creating_integration_file_structure/) | 一个功能域内集中集成代码和配置入口 | 岛屿、钓鱼、背包各自拥有模型与实现，共享运行基础；不引入其完整平台和调度体系 |
| [AzurLaneAutoScript：页面模型](https://github.com/LmeSzinc/AzurLaneAutoScript/blob/master/module/ui/page.py)、[页面导航](https://github.com/LmeSzinc/AzurLaneAutoScript/blob/master/module/ui/ui.py) | 页面连接、当前页识别、目标页导航、已到达判断 | 用已知页面关系支持多个起点；保留未知页结果。借鉴导航边界，不照搬全局页面注册与继承结构 |
| [Scrapy：架构](https://docs.scrapy.org/en/latest/topics/architecture.html) | 引擎协调、爬取逻辑、下载和处理的职责边界 | 任务协调与具体能力通过接口协作；本项目实时游戏控制不据此改成异步流水线 |
| [HTTPX：Transport](https://www.python-httpx.org/advanced/transports/) | 自定义传输和模拟传输由同一客户端调用 | 实际截图与回放帧、真实输入与记录器使用明确合同，以相同任务代码验证；不引入 HTTPX 依赖 |
| [pytest：插件](https://docs.pytest.org/en/stable/how-to/writing_plugins.html) | 明确的扩展钩子、内置和外部插件发现 | 扩展性需要稳定边界；本阶段用内置功能和策略注册即可，第三方插件等独立发布需求出现再设计 |
| [PyInstaller：hooks](https://pyinstaller.org/en/stable/hooks.html) | 隐式导入、数据与入口点收集 | 动态发现涉及冻结包收集，不能认为有 Python 插件接口就已完成 EXE 扩展支持 |
| [Python：资源 API](https://docs.python.org/3.12/library/importlib.resources.html)、[Protocol](https://docs.python.org/3.12/library/typing.html#typing.Protocol) | 包资源读取与结构化接口 | 将包资源和用户运行数据分开；只在必要设备边界使用轻量接口 |

这些项目采用不同布局，不能推出“成熟 Python 项目都应采用某一种四层目录”。共同可借鉴的是明确功能归属、隔离易变实现、公开有限接口，并能验证真实安装和运行边界。

## 修正上一版方案的原因

上一版将业务判断集中到 domain，识别放 adapters，执行放 application。对本项目而言，这容易让一种机制的识别、规则、执行和样本分散到整个仓库，增加功能扩展时的查找成本。

新的选择是功能为主、功能内部按需要拆识别与规则；通用设备与存储独立。例如“识别冰冻”属于钓鱼，“调用 RapidOCR”属于基础设施，“从开始页进入某岛并开始钓鱼”属于应用协调。

用户明确目标是岛屿玩法拓展：更多岛屿、导航、机制和信息读取。因此不将架构预设为多游戏宿主，也不将第六个岛屿简单当成第三个策略类。岛屿目录、动态状态和能力覆盖必须分别建模。

## 仍需事实核验的内容

- 用户指出已有第六个岛屿；当前代码仅含 5 个地点。名称、入口、解锁要求和机制尚未在本轮获得足够来源，不补写为已确认资料。
- 开始页到岛屿玩法的实际页面、弹窗和转换条件需要真实画面确认。
- 岛屿与钓鱼地点是否一一对应，需要核对后再决定是否建立两级关系。
- 信息读取字段逐项定义来源与有效期；已有 OCR 引擎不代表已经具备等级、图鉴等读取能力。
- 机制参考包含社区资料及未覆盖项，持续时间与组合规则不能未经实测就写入策略常量。

这些缺口不阻碍确定模块边界，但会限制具体资料和自动操作实现。[架构方案](../design/architecture.md)给出了分步迁移和各类扩展的验收方式。
