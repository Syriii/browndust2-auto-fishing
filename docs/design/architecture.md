# 项目架构与扩展边界

[文档目录](../README.md) · [目录布局](repository-layout.md) · [开发指南](../development/guide.md) · [开发规范](../development/standards.md)

本文以 v0.2.0 和当前源码为基线，先描述已实现架构，再列后续目标。首轮方案、旧模块名及迁移过程保存在[架构阶段档案](../history/architecture-2026-09-08.md)。

## 划分依据

项目是单进程的 Windows 桌面应用，按功能归属、修改原因和资源所有权划分模块。抛竿、等待、QTE、结算是任务执行步骤，留在钓鱼能力内部，不作为仓库顶层分层。

`bd2_fishing/` 直接位于仓库根目录。统一包名服务于内部导入、工具调用和打包，不意味着要作为第三方库发布；构建显式收集应用包。公共图像与文字处理放 perception，取消和设备合同放 runtime，Windows 与持久化实现放 infrastructure，不建立万能 utils/common 模块。

## 当前依赖

以下箭头表示 **Python 导入方向**，不是游戏操作顺序。类或子包职责见[开发指南](../development/guide.md)。

```mermaid
flowchart TD
    B[bootstrap 启动组装] --> U[ui 桌面展示]
    B --> A[app 应用服务]
    B --> I[infrastructure 平台与存储]
    U --> A
    U --> R[runtime 运行控制与合同]
    A --> G[game 游戏能力]
    A --> I
    A --> P[perception 通用识别]
    A --> R
    G --> I
    G --> P
    G --> R
    I --> P
    I --> R
    P --> R
```

| 部分 | 拥有的职责 | 重要边界 |
| --- | --- | --- |
| ui | 任务选项、设置草稿、运行记录、更新与存储窗口 | 只通过 app 调用任务与设备服务，Tk 控件只在主线程更新 |
| app | 用户请求、单任务生命周期、配置/设备组装、跨功能恢复、更新用例 | 不让页面直接操作钓鱼策略或原生驱动 |
| game | 岛屿、导航、背包、钓鱼的识别、规则与动作 | 动作/观察器可调用现有适配器；纯机制、反馈规则与目录不依赖设备 |
| perception | 通用图像与文字处理、OCR 数据和读取合同 | 不导入游戏或具体平台引擎 |
| runtime | 取消、输入互斥、轮次上下文、几何、最小设备合同 | 不反向导入 app、game、ui、infrastructure |
| infrastructure | DXcam/GDI、窗口/输入、电源、OCR、配置、日志、证据与更新事务 | 不拥有 QTE 策略或岛屿业务判断 |

规则由 `scripts/checks/check_architecture.py` 自动检查。当前 game 执行代码仍使用部分具体适配器，不能把上图改成“所有设备均已注入”的理想结构；现有截图工厂和合同在需要模拟、录制或替换时使用。

## 钓鱼与机制链路

```text
game/fishing/
├── actions.py / cast_feedback.py  抛竿、恢复动作与提示判断
├── qte.py                        控制循环、地点策略与同步输入
├── mechanics/
│   ├── policy.py                 唯一动作意图及黄蓝目标策略
│   ├── regions.py                同帧红紫绿区域与泡泡几何
│   ├── blue_target.py            蓝区可靠内部边界与小孔修补
│   ├── green_control.py          有界按下、持有、释放状态
│   ├── bubbles.py                泡泡单次尝试许可
│   ├── blockers.py               既有深渊单挡板识别
│   └── lifecycle.py              观察侧多外观实例时间线
├── pointer.py / trigger_rules.py  真光标观察与同次入区去重
├── scene_signals.py               独立观察帧中的特殊外观线索
├── scene_evidence.py              场景事件和前后图
├── feedback*.py / recognition.py  反馈识别与按键归属
├── settlement*.py / page.py       鱼获与待机页面确认
├── tracing.py / hook_diagnostics.py  轮次统计与上钩取证
└── assets/                       运行时识别模板
```

两套地点策略共用 `BaseQTEStrategy.play_qte`。控制帧提取目标和机制区域后交给 `MechanismPolicy`，返回 normal、wait、press、down 或 up；只有执行层发送输入，处理器之间不各自按键。

普通目标黄色优先，无有效黄区时检查蓝区安全边界并连续确认；绿色模式约束优先于泡泡尝试，红紫局部障碍约束普通输入。时间从调用方传入，纯状态规则不截图、不等待、不写盘。

控制与观察是两条关联但不同的链：

```mermaid
flowchart LR
    C[DXcam 控制帧] --> V[目标与机制区域]
    V --> M[MechanismPolicy]
    M --> E[qte 同步执行]
    E --> N[受控原生输入]
    O[GDI 观察帧] --> F[反馈与特殊外观]
    E -. 按键记录 .-> F
    F --> Q[有界后台证据队列]
    Q --> Z[PNG / ZIP / 元数据]
```

独立观察帧不代表控制决策的同一时刻，旧观察不能授权当前输入。外观连续出现、消失或中断不等于技能身份确认；按键与消失时间接近也不证明解除成功。

**完整技能处理链尚未实现。** 绿色实际起按端未确认，识别不自动授权长按；泡泡许可只记录尝试；冰冻缺专用识别和解除，挡板仍为有限单墙算法。抵抗提示、组合技能身份及解除因果需继续补齐，见[机制链审计](../development/mechanism-chain-audit.md)与[验证计划](../development/validation-plan.md)。

## 生命周期与低时延

app 管理一个会话的工作线程、聚焦、COM、电源、截图和 OCR；runtime 提供取消与输入锁。停止、异常和窗口保护触发时释放输入与资源，旧任务未退出不启动第二个任务。`RunStopped(BaseException)` 的设计用于穿过普通业务异常捕获。

QTE 在原控制线程中采样、判断并同步输入，不增加待执行按键队列。PNG/ZIP 编码与文件日志在有界后台处理；证据积压不能通过同步写盘回退到控制路径。反馈、场景和 OCR 观察仍有资源与锁开销，必须单独测量。

循环节流、按住、松开后等待、页面确认是不同参数，不能统一缩短。基础等待校准不包括截图、驱动或游戏响应；目前没有完整游戏端到端时延基线，指标与测量方法见[QTE 时延设计](qte-performance.md)。

## 更新与数据

ui/updates 通过 app/updates 调用版本检查、本地包导入与重启交接；infrastructure/updates 执行下载、清单校验、文件备份替换和恢复。独立助手等待主程序退出，更新成功后重启至待机。

`manifest.json` 只管理程序文件，配置、校准、日志与截图独立保存。启动初始化和便携版待机清理不进入 QTE 循环。源码 `.local/`、便携目录、构建输出各有用途，见[目录布局](repository-layout.md)和[更新设计](portable-update.md)。

## 后续扩展：尚未实施

| 方向 | 归属与要求 |
| --- | --- |
| 从开始页进入钓鱼 | navigation 补已确认页面、转换与到达验证；app 组合准备任务，未知页面不盲点 |
| 第六岛及更多岛屿 | islands 补稳定身份、别名、来源和能力覆盖；不以列表下标持久化身份，不写死总数 |
| 玩法信息读取 | 所属功能提供值、时间、来源帧及未知/过期状态，app 汇总；读取失败不填成 0 |
| 更多机制及组合 | fishing/mechanics 扩充识别、约束与状态，由 policy 统一输入权限；配真实正负例及连续时序证据 |
| 其他岛屿玩法 | game 新增对应功能，app 增加任务入口；复用运行与导航能力，不复制整个钓鱼包 |
| 可替换设备与回放 | 在真实替换或测试需求处提取小合同，不给每个函数增加接口或转发层 |

地点资料收录、页面可识别、可以导航、信息可读、机制已验证是不同能力，不能用一个 supported 标志混在一起。每次扩展单独说明实现与实测范围，目录迁移不夹带未经验证的阈值和输入时序修改。
