# 开发规范与检查门槛

[文档目录](../README.md) · [完整目录布局](../design/repository-layout.md) · [当前状态](status.md)

本项目是独立桌面应用，采用仓库根目录直接放 bd2_fishing 的扁平布局。保留统一导入名称和明确的模块依赖边界；pyproject 显式只收集 bd2_fishing 包，普通 wheel 检查资源与导入完整性，不代表向 PyPI 发布第三方库。[PyPA 布局说明](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)

## 应用包内职责与依赖

| 包 | 职责 | 可导入的本项目部分 |
| --- | --- | --- |
| runtime | 取消、输入互斥、几何、轮次上下文、设备合同 | runtime |
| perception | 通用图像、OCR 数据/读取、文字与识别上下文 | perception、runtime |
| infrastructure | Windows、OCR 引擎、配置存储、后台文件输出 | infrastructure、perception、runtime |
| game | 本游戏的岛屿、导航、背包、钓鱼规则及操作 | game、perception、runtime、infrastructure |
| app | 用户任务、跨功能协调、资源组装和桌面服务 | app、game、perception、runtime、infrastructure |
| ui | Tk 控件和展示 | ui、app、runtime |
| bootstrap | 日志与桌面启动组装 | app、ui、infrastructure |

game 中的纯规则和识别模块进一步限制：feedback_rules、settlement_rules、cast_feedback、recognition 和 catalog 不导入具体基础设施、app 或 ui。动作与观察器可以使用当前适配器；需要录制、模拟或替换设备时再通过小型合同注入。当前没有宣称全部 I/O 已实现依赖倒置。

静态规则由 `scripts/checks/check_architecture.py` 执行，覆盖绝对/相对导入、from 别名导入、函数内导入和模块循环。它不执行代码，也不分析运行时动态拼接的 import；新增动态装载必须单独验证。目录名本身不是架构验收。

`game/fishing/mechanics/` 整个子包按纯识别/规则边界检查，新增文件自动纳入；不得导入
基础设施、app、ui，也不得通过 qte/feedback 等游戏执行模块间接获取设备。可依赖同包模块、
普通目标去重规则 `trigger_rules`、perception 和 runtime。时间以参数传入，不在机制中等待或派发输入。

正式应用不得导入 scripts、tests 或 tools；工具调用应用能力，实验探针不能反向进入正常任务。异常与结算共用 infrastructure/diagnostics/bundle_writer.py，玩法只提交结构化证据。

## 公共逻辑的抽取原则

- 已有多个调用方且语义相同的图像/文字处理归 perception；不创建收纳任意代码的 common.py 或 utils.py。
- QTE 亮字反馈归 game/fishing/recognition.py；结算关闭提示为灰字，使用独立灰度模板与有限像素取整搜索，不能套用亮白阈值。这些识别具有游戏语义，不提升成通用 OCR 引擎功能。
- 地点、地图和满包 ROI 属于本游戏的观察设置，归 game/observation.py；QTE 统计归 game/fishing/tracing.py。runtime 不拥有玩法场景字段。
- 设备合同与实现分开命名；通用 OCR 读取依赖 FrameSource/OCREngine，不借用 DXcam/RapidOCR 名字伪装通用接口。
- 提取以调用关系和变更原因作为依据。小型模块保持简单，不为每个函数增加接口、工厂、线程或多层转发。

## 格式、检查与 CI

统一配置在 pyproject.toml：Python 3.12、100 列格式化目标、Ruff 的导入排序、未定义/未使用名称及基础错误检查。Ruff 固定为开发依赖，缓存放 `.local/cache/ruff/`。少数用于验证原生依赖能否导入的 import 保留带原因的局部 F401 注释；不使用全仓库忽略掩盖问题。[Ruff 配置文档](https://docs.astral.sh/ruff/configuration/)

提交前在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -m ruff check bd2_fishing scripts tests main.py setup.py
.\.venv\Scripts\python.exe -m ruff format --check bd2_fishing scripts tests main.py setup.py
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/check_architecture.py
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
```

需要整理格式时使用 `ruff format`；检查发现的逻辑问题仍需人工理解和回归，不对业务代码批量使用 unsafe fixes。CI 在 push/PR 时执行相同检查并构建 wheel；发布工作流额外构建含 OCR/Tk 的便携包。当前仍使用 unittest，不为换测试框架重写已有回归。

## 时延要求

QTE 控制继续在同一工作线程采样、判断和调用受控输入。模块拆分只增加导入边界，不为动作增加消息队列或线程跳转。循环等待、驱动暂停、按下持续时间与页面确认等待具有不同用途；修改前必须分别测量，不能统一清零。

文件日志由 BufferedHandler 交给后台输出，控制线程只固定消息并入队，不写盘或格式化 traceback。队列容量 4096，其中 256 个位置为 INFO 及以上的结果/错误预留；DEBUG 达到预算或总队列满时丢弃新记录，由后台报告丢弃数；不以同步写盘回退阻塞控制。close 最多等待两秒排空；显式 flush 另有有界等待，强制退出或长期磁盘阻塞可能留下未保存记录。UI 筛选独立于文件日志；原生故障日志保留独立文件。标准库同样建议把阻塞的日志处理移到工作线程。[Python Logging Cookbook](https://docs.python.org/3.12/howto/logging-cookbook.html#dealing-with-handlers-that-block)

按键前的反馈记录只复制小图、固定提交时间，并向容量 128 的队列非阻塞提交；按键不等待观察状态锁。归属、证据整理和反馈日志由观察线程处理，日志处理器在状态锁外调用。队列满时计数丢失记录，本会话后续按键归属保持未知，不能把缺失候选按键的反馈确认为某次命中。整轮元数据的 feedback_diagnostics 记录过载与观察线程退出状态。

关闭先停止接收并封存账本，再有限等待观察线程。原生识别迟到返回时不能继续发布反馈或更新 OCR 读数，采集资源仍由原线程退出时释放。同轮后台 OCR 与结算 OCR 串行，等待本轮锁时响应取消，超过两秒未释放则结算保持未知。RapidOCR 引擎另持有覆盖所有入口和轮次的互斥锁；原生调用仍忙时，新观察明确报忙且不排队，不能把未执行识别伪装成空结果。原生调用和结果转换无论正常或异常结束均释放引擎锁。

QTE 执行中的停止、超时和异常优先保留；反馈清理再次失败时附加原因并记录日志，仍尝试封存整轮证据。正常执行后的清理失败继续抛出，阻止任务继续。PNG/ZIP 编码和写盘继续在有界后台执行，三类证据写入器共用写入事务，失败时清理本次临时文件。消息固定、控制台/UI handler 和截图/输入驱动仍有开销，以上边界不是端到端时延保证。

离线基准命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/benchmarks/qte_latency.py --iterations 2000
```

输出在 `.local/benchmarks/qte-latency.json`，记录环境、样本数、p50/p95/p99/max 和日志丢弃数。使用 perf_counter_ns 测量局部耗时；固定尺寸的合成图只用于比较工作量，不作为真实识别证据或完整策略回放。[Python 时钟文档](https://docs.python.org/3.12/library/time.html#time.perf_counter_ns)

完整截图到游戏响应、停止响应及不同设备负载的验收仍按[QTE 时延设计](../design/qte-performance.md)执行。当前没有真实游戏端到端基线，不设置没有依据的全局毫秒达标线。
