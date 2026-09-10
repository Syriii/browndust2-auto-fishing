# 历史功能迁移与正式代码核对

[文档目录](../README.md) · [当前状态](status.md) · [历史实测](../history/optimization-2026-09.md)

本文是 2026-09-08 的迁移审计档案，测试数、AST 一致性和功能边界均指当时版本。其后已增加蓝区、指针、机制与更新功能，不用本文的旧限制替代[当前状态](status.md)，也不把历史一致性结论外推到后续改动。

核对日期：2026-09-08。归档仓库的 main 与 test/qte-feedback 均为 `22339195d6172ec309d2a541c4831564cd3835c8`，实验工作树干净；没有遗留的独立待合并提交。GitHub 源码后来重建了历史，因此本次按功能、规则和真实样本核对迁移结果，不将旧目录重新复制进当前仓库。

## 正式能力与证据

下表入口均在 bd2_fishing 应用包中，由 main.py 的正常任务路径调用，无需运行实验脚本。

| 已验证内容 | 当前实现 | 验证依据 |
| --- | --- | --- |
| 反馈识别 CRITICAL/HIT/MISS/FAIL | game/fishing/recognition.py、feedback.py | 12:30–12:34 真实采样，字形正负例；模板与归档逐字节相同 |
| 反馈与按键归属分开、动画去重、未知兜底 | game/fishing/feedback_rules.py | 13:03、14:06 真实记录；Outcome/OutcomeTracker AST 与旧实现一致 |
| GDI 小区域观察与 DXcam 控制并行 | infrastructure/windows/gdi.py、capture.py | 历史双采集与资源释放验证；GDI 类 AST 一致 |
| 失败前后图和同帧掩膜 | game/fishing/feedback.py、infrastructure/diagnostics/qte_evidence.py | 重新核对 30 个历史 ZIP：240 张原图、720 张掩膜完全一致 |
| 控制决策图与按键依据 | game/fishing/qte.py、feedback.py | 原有决策证据、连续尝试不串图、停止仅用缓存等回归保留 |
| 鱼获确认、疑似逃脱、中断和未知 | game/fishing/settlement.py、settlement_rules.py | 对 13:03 两份捕获和 13:11 逃脱原图执行当前 OCR 与规则，结果保持 caught/caught/suspected_escape |
| 全退出路径收尾、最后一次按键结果 | game/fishing/settlement.py 的 run_observed_qte | 历史 105 次真实按键的完整记录及当前正常/超时/异常/停止回归 |
| 轮次与证据 ID、详细日志 | runtime/context.py、infrastructure/diagnostics/ | 历史日志回放与当前跨轮隔离、后台写入回归 |
| 夜间上钩、重抛后的完整等待 | app/fishing_task.py、resources/default.ini | 原有夜间正负例、模拟 20 秒清包后等待、位置受阻恢复回归 |
| 单任务启停、输入释放与窗口保护 | app/service.py、runtime/control.py、infrastructure/windows/ | TaskController、RunControl 和 RunStopped AST 一致；窗口保护只迁移了导入路径 |
| 实时显示器枚举与旧工厂隔离 | infrastructure/windows/display.py | 原有只读实机验证和旧工厂失配离线回归保留 |

旧版 119 个测试名称中，117 个仍直接存在；另两项按新要求调整：允许关闭反馈观察改为旧开关无法关闭必要取证，旧工作树配置路径改为 .local/config.ini。其他已验证功能没有因为搬目录被移入 scripts 或丢弃。

## 本次收紧

- 失败与异常取证常驻，成功与失败分别轮转；逐帧文本仍可选。旧反馈开关不再关闭维护证据。
- 通用后台写入器命名为 infrastructure/diagnostics/bundle_writer.py，供结算与异常共用。异常堆栈格式化、PNG 编码、ZIP 写入及保留清理都由后台执行。
- 上钩超时复用异常分支已经取得的客户区帧，专用诊断不再重复截图；无图时仍保留峰值/最后 ROI 和无图标记。
- 静态检查禁止正式应用导入 scripts、tests、tools；实验探针不会成为正常任务的依赖。
- 保留按职责划分的应用包；底层不反向导入游戏，纯识别/规则不依赖原生引擎，UI 经 app 调用。截图工厂已有注入点；未宣称所有设备实现都已完全注入。

## 通过范围

147 项离线回归、Ruff 和 63 模块静态依赖检查通过。两套实际 QTE 策略与归档在导入引用归一化后 AST 一致；规则、GDI 与控制器的比较结果见上表。新的常驻取证、保存路径和写入实现由本轮回归验证。

历史结算复核重新执行了奖励与距离图像的 OCR；倒计时读数、按键归属和游戏反馈沿用原记录，并用当前正式结算写入器重新保存。不能把离线复核描述为重新操作游戏。

真假指针跟踪、绿色长按、完整特殊机制组合、第六个岛屿与从开始页进入玩法尚无已验证实现，本次不宣称支持。--probe-outcomes 与 --probe-escape 会刻意偏离正常输入，继续作为显式实验工具保留在 scripts/live；--feedback 仅兼容旧命令。

本轮不操控游戏、不更新已部署 EXE。实际命中率、未知机制和不同设备上的端到端时延仍需后续实机验收。提交包含源码、测试、构建配置与文档，不包含本机配置、历史截图、运行库或生成的发布 ZIP。
