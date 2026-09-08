# 棕色尘埃2的python钓鱼脚本

## 介绍

基于图像识别进行QTE操作，只点击黄色区域，简单的QTE操作没问题，例如QTE条上有一些遮挡物，把黄色区域覆盖了，就容易失败

## 使用步骤——源码运行

+ 测试环境：
+ Python 3.12.4
+ Pypi 24.0

### 1. 创建虚拟环境

打开空文件夹，并在空文件夹打开`powershell`，输入下面命令

```sh
# py -版本 -m venv 环境名字
py -3.12 -m venv auto_fishing
```
### 2. 进入虚拟环境

继续输入下面命令进入虚拟环境

```sh
# .\环境名字\Scripts\activate
.\auto_fishing\Scripts\activate
```

### 3. 安装必要的依赖

```sh
pip install -r requirements.txt
```

### 4. 运行脚本

默认打开图形页面并保持待机。点击 **开始钓鱼**，程序会恢复并聚焦游戏窗口，确认成功后再初始化并运行；点击 **停止任务** 停止。
页面显示当前阶段、最近提示和日志筛选，支持选择钓场、自动清包开关、保持唤醒和逐帧诊断。开始时保存这些选项，其他配置和注释保留。自动识别失败时可在页面直接选择钓场。
停止会释放按键和截图资源；再次启动重新定位窗口。运行中切走焦点、锁屏、移动/缩放或最小化游戏会结束当前任务，处理完成后手动重新开始。**游戏需完整可见且保持前台**，并且不要同时运行两个版本。

```sh
python main.py
```

只预览页面而不连接游戏：`python main.py --preview`（不保存页面设置）。程序仅通过页面按钮启停，不监听全局快捷键。

### Windows 待机与电源

- 人离开电脑但系统未锁屏、未睡眠，游戏仍在前台：可以继续。
- 锁屏、睡眠、休眠：不支持继续钓鱼。解锁或唤醒后重新开始，不会自动绕过锁屏或自动续跑。
- 勾选“运行时防止自动息屏 / 睡眠”，仅在任务线程存活期间请求保持唤醒，停止后撤销；默认关闭，不永久修改电源计划。它不能阻止主动睡眠、合盖睡眠或屏幕保护程序。
- 手动关闭显示器、拔线或远程桌面断开可能让截图失效，不能保证运行。

电源选项对应 `[app] prevent_sleep`；实现依据 [Windows SetThreadExecutionState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate)。桌面切换和会话断开可能使截图失效，参见 [DXGI 错误定义](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/dxgi-error)。

### 背包自动清理开关

在运行程序旁的 `config.ini` 中设置：

```ini
[backpack]
auto_clear_enabled = false
```

`true` 表示识别到“背包已满”后自动清理；`false` 表示不自动出售，检测到满包后停止待机，手动整理后点击“开始钓鱼”继续。
程序不按固定 30 只或 400 只计数清理，扩容后仍以游戏满包提示为准。新配置默认开启，旧配置缺少此项也保持开启。
每次点击开始时保存页面设置，并以该配置启动。满包检测依赖 `[ocr] enabled = true`，关闭 OCR 后不能保证满包时自动停止。

### 多显示器

游戏客户区可以完整放在任意一块显示器上，包括左侧或上方负坐标屏幕。程序自动选择对应显卡与输出，将截图坐标转换为该屏幕内坐标；鼠标使用整个虚拟桌面定位。各屏缩放不同时使用每显示器 DPI 感知。

运行中移动、缩放或最小化游戏窗口会停止本轮并释放输入；放好窗口后点击“开始钓鱼”重新定位。客户区横跨两块屏幕或超出屏幕边界时会提示调整位置；目前不拼接跨屏截图。屏幕热插拔、唤醒或更改显示器排列后，请停止当前任务，等显示器稳定再开始。每次创建截图会话都重新枚举并使用同次枚举的设备对象，避免 DXcam 旧输出索引缓存失配；不会自动续跑中断的任务。

截图输出选择依据 [DXcam 多显示器接口](https://github.com/ra1nty/DXcam#multiple-monitors--gpus)，鼠标坐标依据 [Windows MOUSEINPUT 的虚拟桌面定义](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput)。

实际执行一次背包清理流程，不进入自动钓鱼循环：

```sh
python tools/clean_backpack_once.py
```

这是明确执行一次清理的手动工具，不受自动清理开关控制。

有时限的真实游戏实测（运行 90 秒，OCR 失败时使用第 4 个地点）：

```sh
python tools/run_live_diagnostic.py --seconds 90 --location 4
```

此命令会实际抛竿和按键。启动时有 8 秒准备时间，游戏失去焦点或达到时限时停止，
并释放脚本使用的空格和方向上键。`--hook-upper-hue 35` 可仅为本次实测覆盖上钩色相上限。

### 5. 运行测试

```sh
python -m unittest discover -s tests
```

## 上钩超时诊断截图

### OCR 与 QTE 日志

`auto_fishing.log` 同时保存项目日志和 RapidOCR 原始警告。OCR 记录包含业务场景、屏幕区域、图像尺寸、文字数量与耗时；原始库消息保留等级及代码位置。背包提示允许为空，地点文字为空则作为需要关注的结果。无新图与真正的截图/模型异常分别记录，后者保留调用栈。

QTE 日志每 5 秒汇总采样状态、挡板识别次数与位置范围、位置变化次数和按键次数。文件默认额外记录每次挡板位置变化。正常结束、超时、点击停止任务和异常退出均补齐最后一段汇总并记录退出原因；倒计时条消失不等于已经确认捕获成功。

需要逐帧复现时，在程序旁的配置中临时开启：

```ini
[diagnostics]
qte_detail_log = true
```

逐帧记录只写文件，不刷页面；点击“开始钓鱼”重新启动后生效。排查完成后改回 `false`，避免额外写盘开销和过快轮转。日志沿用单文件 5 MiB、保留 3 份备份的上限；出现问题后请及时保留 `.log` 及 `.log.1`～`.log.3`。关闭逐帧开关不会关闭汇总、挡板变化或异常记录。日志不能替代识别错误发生时的原始图片。

### 超时图片

程序原本会持续截图识别，但不会把截图写入文件。现在默认在上钩超时时，
最多每 60 秒向程序目录的 `debug/hook_timeouts/` 写入一份 ZIP 诊断包，
循环覆盖 10 个槽位。源码运行时该目录位于源码文件夹；重新打包后位于 EXE 旁。
现有 EXE 不会因为修改源码而自动更新。

- `peak_hook.png`：该等待周期内，符合当前 HSV 条件的像素数最多的一帧原图。
- `peak_mask.png`：峰值原图对应的颜色遮罩。
- `last_hook.png`：超时前最后一帧有效的感叹号区域，可与峰值帧对比。
- `timeout_game.png`：执行恢复操作前额外截取的游戏客户区，与峰值帧时间不同。
- `metadata.json`：时间、区域坐标、颜色范围、阈值、有效帧数、返回 None 的次数及现场截图耗时。

没有有效图像的文件会省略，并在 JSON 中注明。截图返回 None 不一定代表故障，
也可能表示没有新画面。峰值为零时，保留该周期第一帧有效图像和最后一帧有效图像。

正常识别时只在内存复制很小的感叹号区域；PNG 编码和文件写入在后台执行。
超时现场截图仍是同步调用，会增加一次截图耗时，记录在 `context_capture_ms`；
上述上钩诊断不在 QTE 循环保存截图。后台忙时跳过本次保存，程序退出时未完成的保存可能中断。
日志出现“上钩超时诊断已保存”后，可把对应 ZIP 用于分析夜间漏检。

`[diagnostics]` 的 `enabled = false` 可关闭诊断；`interval_seconds` 和 `max_events`
分别控制保存间隔和诊断包数量。此功能不调整识别阈值或按键策略。

### 日志如何阅读

默认页面与控制台显示 INFO 及以上：每次观察到新的游戏反馈显示一次中文结果，每条鱼结束显示一条结算与统计。MISS/FAIL 是游戏结果；按键归属未确认也不代表程序错误，不再逐条作为 WARNING 展示。需要处理的保存失败、观察器异常、控制超时等仍明确提示；预期的失焦停止不输出异常堆栈，真正异常保留堆栈。

`auto_fishing.log` 保留 DEBUG 及以上，包含每次按键归属、候选按键、匹配分数、控制采样和证据保存位置；页面选择“详细诊断”也能查看近期细节。“逐帧诊断写入文件”只控制每帧额外数据，关闭它不会丢弃逐次按键记录。主日志按每份 5 MiB、3 份备份轮转；原生崩溃记录 `auto_fishing.fault.log` 在重启时追加，不清空旧内容。

每轮从抛竿开始分配 `[轮次=进程标识-序号]`，位置恢复重抛沿用该编号。QTE、OCR、结算以及后台诊断日志使用同一编号，诊断 ZIP 的 `metadata.json` 也保存 `round_id`。包内独立的 `evidence_id` 用于区分同名槽位的不同版本；旧日志指向的 ZIP 若已覆盖，必须核对 ID，不能只凭文件名认定仍是当时截图。

汇总中的“暴击/普通命中/未命中”统一统计实际游戏反馈；“按键尝试、归属未确认”单独列出，不能用它们推算实际命中率。“已发送破冰尝试按键”只描述动作，不宣称破冰成功。

### QTE 单次反馈与失败留图

Python 页面通过“记录 QTE 结果、失败截图和鱼获结算”开关控制，点击开始时保存并应用；源码配置与缺省配置均默认开启。已有配置明确设为 `false` 时保留关闭，可在页面重新勾选。对应 `[diagnostics] qte_feedback_enabled`。当前根目录 EXE 尚未包含此功能。

开发实测运行 `tools/record_qte_session.py --seconds 45 --feedback`，仅该 Python 进程启用，不修改配置文件。该工具会真实钓鱼并保存高频调试画面，限时、失焦停止，自动清包在本次进程内关闭；不要与其他钓鱼任务同时运行。

验证正常采集路径时使用 `tools/record_qte_session.py --seconds 45 --feedback --no-full-frames`，保留按键时序、反馈日志与失败小区域证据，不开启高频全窗口录像。开发和实测始终从项目虚拟环境启动 Python 源码。

在独立工作树实测时可追加 `--config "原目录的绝对路径/config.ini"`，只读沿用用户配置；自动清包关闭等调试覆盖只在进程中生效。未指定配置时，优先读取父目录部署配置，不存在则使用当前工作树源码配置。缺失的显式配置会在启动游戏操作前报错。

反馈对应：`CRITICAL` 为暴击，`HIT` 为普通命中，`MISS`/`FAIL` 为未命中。一次新反馈最多对应一次按键；残留动画、反馈等待超时、连续按键归属不清、未识别文字均保留“未确认”，不自动补按、不改变策略或提前结束 QTE。无对应脚本按键的 FAIL 单独记录，不误算给某次操作；社区攻略提到蓝区缩完未命中也会出现 FAIL，不能仅据此认定特殊机制惩罚。这些记录不代表整条鱼是否捕获。

游戏反馈与按键归属分别统计：例如已经看到 HIT，但候选按键有两次，游戏反馈仍记为一次普通命中，按键归属保留未确认。候选按键按反馈实际出现时刻核对现有 750 ms 窗口，已经过期的旧按键不会让新结果继续含糊。没有新反馈的重复按键不能算成新的一轮 QTE 失败。

没有新截图也会结算反馈等待超时，但不会据此认定旧文字消失。相同反馈重新计数需要实际观察到持续空白后再出现；留图优先保留反馈出现帧及按键前后帧，并记录每帧相对按键和反馈的毫秒偏移。

观察器只在 QTE 期间独立采集客户区 30%–70% 横向、64%–93% 纵向的小区域；匹配采用本机实测反馈字形，其他分辨率、语言和特殊机制尚未实机验证。每次未命中/未确认保存最多 8 张前后帧及其原始白、黄、蓝颜色掩膜到 `debug/qte_feedback/qte_01.zip` 等诊断包。记录区域、时间和反馈归属原因；原图与掩膜同帧，但观察帧不保证是控制线程的同一决策帧。编码写盘在后台，队列最多 2 份，磁盘按 `max_events` 循环覆盖；队列满或无图时明确记日志，不能保证每次都有文件。QTE 留图开关独立于上钩诊断的 `enabled`。

开启反馈记录时，每次策略按键额外记录触发分支：`yellow_overlap`（黄区重叠）、`blue_fallback`（蓝区回退）、`no_cursor_fallback`（未找到指针时的原有按键）、`ice_break_attempt`（破冰尝试）。这些是程序决定尝试按键的原因，不是游戏命中结果，也不证明游戏收到输入。DEBUG 文件日志记录“QTE 按键决策”；整轮结算包的 `attempt_outcomes[].decision` 保留相同依据，包括指针位置、容差，以及对应分支使用的挡板范围或阈值。

未命中/未确认包另附最多一张 `decision.png` 及其白/黄/蓝原始掩膜：它复用控制线程当时的 DXcam BGR 原图，与 `frame_*.png` 独立观察图分别标明坐标和时间。`decision` 中的指针、检查列、挡板和有效范围均以 QTE 裁剪区域为原点；`qte_crop_percent` 顺序为上、下、左、右，裁剪基于 `frame_region` 对应的决策原图。原始掩膜不包含策略膨胀，不可直接等同最终按键判定掩膜。控制线程只在按键尝试时复制区域，不新增截图、编码或写图；仍有少量复制与日志开销，实机时序影响待日常使用观察。

命中明确时只保留决策元数据，不额外保存决策图；无对应按键的 FAIL 不附上一次按键的决策图。停止时用已缓存帧完成最后一笔记录。即使反馈采集无图，只要存在决策图仍可保存，包中明确列出 `frames=[]` 和 `decision_frame_available=true`；两类图都没有时记录无可用截图。历史包不会自动补齐新字段或决策图。

反馈采集使用 GDI `BitBlt`，游戏控制继续使用原 DXcam；在本机实测中创建第二个 DXcam 会话会报参数错误。独立观察用于覆盖原按键调用约 300 ms 的等待期间可能出现的反馈，不改变原按键条件或暂停时长。`tools/smoke_feedback_capture.py` 可只读验证两种采集并行及资源释放，不发送输入。实测工具可添加 `--stop-file 新文件路径`，创建该文件即请求正常停止，完成清理和诊断写盘；该入口仅用于 Python 测试，不是全局快捷键。

当前优先满足个人高等级角色的使用场景。低级 QTE 的旧特殊机制补全，以及“条上出现非基础内容就记录”的检测方案，均暂缓到后续讨论；现阶段仅按未命中/未确认结果留图。后续应以实际失败样本补充对应机制的回归与策略，范围记录见 `OPTIMIZATION.md`。

社区攻略中的 13 种特殊技能、绿色维持区与当前源码覆盖情况见 [钓鱼机制参考](docs/FISHING_MECHANICS_REFERENCE.md)。该文档区分攻略描述、代码事实与待验证线索，不代表已经支持全部机制。

### 整条鱼结算（与反馈观察一同启用）

开启 `qte_feedback_enabled` 后，同时观察整条鱼的结算。只有结算关闭提示、奖励数量和尺寸同时识别到，才记录“确认捕获”。鱼名可能识别不准，数量可单独复核，日志中的名称保留 OCR 读数。

倒计时多次读到 1 或更小，或最近三次读数单调下降至 1（例如 2、2、1），同时剩余距离大于零、QTE 退出且没有奖励证据时，记录“疑似超时逃脱”。这是画面推断，不是游戏明确失败提示；仅看到 QTE 消失或空场景仍为“未确认”。任务中断不记为逃脱。末帧距离被特效遮住时，最多回看三张近期图；计时器和距离取自不同帧时分别记录时间与原图。

每轮 QTE 退出都会提交一份结构化记录到 `debug/catch_result/catch_01.zip` 等包，包含结果、退出原因、游戏反馈及逐次按键归属。先关闭反馈观察器、结算最后一笔待确认按键，再保存整轮记录。正常结算附带全图、计时器/QTE 小图及 OCR 依据；超时、异常或任务中断只使用已缓存的图片，不在停止后重新截图或 OCR。没有图片时明确记录 `screenshots_available=false`；单纯中断不记为逃脱，已确认捕获后停止仍保留捕获结果。

图片编码和写盘在后台，队列上限 2，按 `max_events` 循环覆盖。队列满或写盘失败会记日志；进程被强制结束不能保证保存。结算识别在原关闭面板前的等待预算内执行；OCR 过慢可能延后关闭，停止后不继续点击。单次按键条件、黄蓝条阈值和驱动暂停参数保持原样。

`tools/record_qte_session.py --probe-escape --feedback --no-full-frames --seconds 45` 仅供授权实测：抛竿后不发送 QTE 按键，采集超时结束证据，不能与 `--probe-outcomes` 同用；不是正常钓鱼模式。

`--probe-outcomes` 是采样反馈字样的专用实验选项，会刻意尝试色条外和蓝条内按键，不用于正常钓鱼或验证命中率。普通 `main.py` 和未指定该选项的调试运行均不使用这种实验策略。

## 使用步骤——exe运行

### 1. 下载压缩包

点击 [Release](https://github.com/hahg2000/auto_fishing/releases)；下载最新的版本里的压缩包制品

### 2. 双击运行

### 3. 在程序页面开始任务

开始按钮会聚焦游戏。识别到当前位置无法抛竿时，会沿用原恢复动作：向前移动 2 秒、点击游戏画面并重新抛竿；同一轮重试后仍收到该提示才停止，请手动调整位置。运行中切换到程序页面或其他窗口会因游戏失焦而停止。

点击 **开始钓鱼** 开始，点击 **停止任务** 停止。打开 EXE 本身不会自动抛竿。
运行期间开始按钮禁用；停止后可以重新开始。关闭页面会先停止任务并释放资源。
自动识别钓场最多尝试 3 次，未匹配时隔 0.5 秒重新截图，日志保留每次识别文字和区域。仍无法识别时，请在页面选择钓场后重新开始；例如 4 号钓场选择“深渊巨口”。手动选择可直接跳过地点 OCR，其他识别仍按配置运行。
停止会立即发出取消信号并释放按键，正在执行的原生截图或 OCR 调用会在返回后退出。

“已发送抛竿按键”仅说明输入动作已发送。若 OCR 识别到“当前位置无法抛竿”，程序会保留原提示及恢复过程日志；这项识别复用现有提示区域，依赖 OCR 开启。恢复动作完成后重新计算完整的上钩等待时间。关闭自动清包不会关闭位置恢复。

## 配置文件说明

程序从 `config.ini` 读取配置。下表中的“变量值”是仓库当前配置值，修改前建议保留一份可正常运行的配置。

- `*_percent` 使用 `0～100` 的百分比；`left/top/right/bottom` 分别表示区域的左、上、右、下边界。
- 背包点击坐标使用 `0～1` 的窗口比例，超出该范围可能点击到游戏窗口外。
- OpenCV HSV 中，Hue（色相）范围为 `0～180`，Saturation（饱和度）和 Value（明度）范围为 `0～255`。
- HSV 下限应小于或等于对应上限。颜色、坐标和像素阈值可能因分辨率、显示设置及游戏画面亮度而需要调整。

### `[hook]` 上钩检测

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `top_percent` | `25` | 感叹号区域上边界 | 相对游戏客户区 |
| `bottom_percent` | `36` | 感叹号区域下边界 | 相对游戏客户区 |
| `left_percent` | `49` | 感叹号区域左边界 | 相对游戏客户区 |
| `right_percent` | `51` | 感叹号区域右边界 | 相对游戏客户区 |
| `hook_lower_hue` | `20` | 上钩黄色色相下限 | 只用于感叹号黄色遮罩 |
| `hook_lower_saturation` | `35` | 上钩黄色饱和度下限 |  |
| `hook_lower_value` | `210` | 上钩黄色明度下限 |  |
| `hook_upper_hue` | `35` | 上钩黄色色相上限 | 夜间实测感叹号包含 H=31～34 的像素 |
| `hook_upper_saturation` | `120` | 上钩黄色饱和度上限 |  |
| `hook_upper_value` | `255` | 上钩黄色明度上限 |  |

### `[roi]` QTE 截图、颜色与挡板

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `top_percent` | `82` | QTE 整体区域上边界 | 相对游戏客户区 |
| `bottom_percent` | `90` | QTE 整体区域下边界 | 相对游戏客户区 |
| `left_percent` | `32` | QTE 整体区域左边界 | 相对游戏客户区 |
| `right_percent` | `65` | QTE 整体区域右边界 | 相对游戏客户区 |
| `time_top_percent` | `0` | 倒计时条上边界 | 相对 QTE 整体截图区域 |
| `time_bottom_percent` | `100` | 倒计时条下边界 | 相对 QTE 整体截图区域 |
| `time_left_percent` | `0` | 倒计时条左边界 | 相对 QTE 整体截图区域 |
| `time_right_percent` | `18` | 倒计时条右边界 | 相对 QTE 整体截图区域 |
| `qte_top_percent` | `50` | QTE 条上边界 | 相对 QTE 整体截图区域 |
| `qte_bottom_percent` | `97` | QTE 条下边界 | 相对 QTE 整体截图区域 |
| `qte_left_percent` | `22` | QTE 条左边界 | 相对 QTE 整体截图区域 |
| `qte_right_percent` | `100` | QTE 条右边界 | 相对 QTE 整体截图区域 |
| `time_lower_green_hue` | `65` | 倒计时绿色色相下限 |  |
| `time_lower_green_saturation` | `185` | 倒计时绿色饱和度下限 |  |
| `time_lower_green_value` | `210` | 倒计时绿色明度下限 |  |
| `time_upper_green_hue` | `75` | 倒计时绿色色相上限 |  |
| `time_upper_green_saturation` | `195` | 倒计时绿色饱和度上限 |  |
| `time_upper_green_value` | `255` | 倒计时绿色明度上限 |  |
| `time_lower_red_hue` | `170` | 倒计时红色色相下限 |  |
| `time_lower_red_saturation` | `155` | 倒计时红色饱和度下限 |  |
| `time_lower_red_value` | `240` | 倒计时红色明度下限 |  |
| `time_upper_red_hue` | `180` | 倒计时红色色相上限 |  |
| `time_upper_red_saturation` | `170` | 倒计时红色饱和度上限 |  |
| `time_upper_red_value` | `255` | 倒计时红色明度上限 |  |
| `yellow_lower_hue` | `20` | QTE 黄色色相下限 | 黄色区域按键判定 |
| `yellow_lower_saturation` | `125` | QTE 黄色饱和度下限 |  |
| `yellow_lower_value` | `220` | QTE 黄色明度下限 |  |
| `yellow_upper_hue` | `30` | QTE 黄色色相上限 |  |
| `yellow_upper_saturation` | `255` | QTE 黄色饱和度上限 |  |
| `yellow_upper_value` | `255` | QTE 黄色明度上限 |  |
| `red_lower_hue` | `170` | 破冰红色色相下限 | Frost 策略用于检测破冰提示 |
| `red_lower_saturation` | `100` | 破冰红色饱和度下限 |  |
| `red_lower_value` | `100` | 破冰红色明度下限 |  |
| `red_upper_hue` | `180` | 破冰红色色相上限 |  |
| `red_upper_saturation` | `255` | 破冰红色饱和度上限 |  |
| `red_upper_value` | `255` | 破冰红色明度上限 |  |
| `blue_lower_hue` | `95` | QTE 蓝色色相下限 | Abyss 策略在有效范围没有黄色时使用 |
| `blue_lower_saturation` | `105` | QTE 蓝色饱和度下限 |  |
| `blue_lower_value` | `255` | QTE 蓝色明度下限 |  |
| `blue_upper_hue` | `102` | QTE 蓝色色相上限 |  |
| `blue_upper_saturation` | `255` | QTE 蓝色饱和度上限 |  |
| `blue_upper_value` | `255` | QTE 蓝色明度上限 |  |
| `white_lower_hue` | `0` | 光标白色色相下限 | 用于定位 QTE 光标 |
| `white_lower_saturation` | `0` | 光标白色饱和度下限 | 饱和度范围过大会把挡板识别成光标 |
| `white_lower_value` | `240` | 光标白色明度下限 |  |
| `white_upper_hue` | `180` | 光标白色色相上限 | 白色低饱和时色相通常不稳定，因此覆盖完整色相范围 |
| `white_upper_saturation` | `10` | 光标白色饱和度上限 | 与挡板饱和度范围分离 |
| `white_upper_value` | `255` | 光标白色明度上限 |  |
| `blocker_one_lower_hue` | `0` | 挡板区间一色相下限 | 两组挡板 HSV 遮罩最终取并集 |
| `blocker_one_lower_saturation` | `25` | 挡板区间一饱和度下限 |  |
| `blocker_one_lower_value` | `230` | 挡板区间一明度下限 |  |
| `blocker_one_upper_hue` | `180` | 挡板区间一色相上限 |  |
| `blocker_one_upper_saturation` | `52` | 挡板区间一饱和度上限 |  |
| `blocker_one_upper_value` | `255` | 挡板区间一明度上限 |  |
| `blocker_two_lower_hue` | `0` | 挡板区间二色相下限 | 用于覆盖另一种亮度或透明状态 |
| `blocker_two_lower_saturation` | `0` | 挡板区间二饱和度下限 |  |
| `blocker_two_lower_value` | `200` | 挡板区间二明度下限 |  |
| `blocker_two_upper_hue` | `180` | 挡板区间二色相上限 |  |
| `blocker_two_upper_saturation` | `10` | 挡板区间二饱和度上限 | 需注意不要覆盖光标范围过多 |
| `blocker_two_upper_value` | `245` | 挡板区间二明度上限 |  |
| `blocker_shape_min_width` | `4` | 挡板轮廓最小宽度 | 参考分辨率下的像素值；实际按窗口宽度缩放，判断不包含等于下限的轮廓 |
| `blocker_shape_max_width` | `20` | 挡板轮廓最大宽度 | 参考分辨率下的像素值；实际按窗口宽度缩放，判断不包含等于上限的轮廓 |
| `blocker_shape_min_height` | `18` | 挡板轮廓最小高度 | 参考分辨率下的像素值；实际按窗口高度缩放，判断不包含等于下限的轮廓 |
| `blocker_shape_max_height` | `100` | 挡板轮廓最大高度 | 参考分辨率下的像素值；实际按窗口高度缩放，判断不包含等于上限的轮廓 |

### `[backpack]` 背包清理

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `auto_clear_enabled` | `true` | 自动清理开关 | false 时满包停止待机，不自动出售 |
| `button_click_interval_seconds` | `2` | 按钮点击间隔秒数 | 网络或动画较慢时可适当增大 |
| `one_click_sale_left` | `0.87` | 一键出售按钮横向位置 | 相对游戏客户区宽度的比例 |
| `one_click_sale_top` | `0.92` | 一键出售按钮纵向位置 | 相对游戏客户区高度的比例 |
| `select_all_left` | `0.82` | 全选按钮横向位置 | 相对游戏客户区宽度的比例 |
| `select_all_top` | `0.92` | 全选按钮纵向位置 | 相对游戏客户区高度的比例 |
| `circle_check_left` | `0.92` | 圆形确认按钮横向位置 | 相对游戏客户区宽度的比例 |
| `circle_check_top` | `0.92` | 圆形确认按钮纵向位置 | 相对游戏客户区高度的比例 |
| `dialog_confirm_left` | `0.57` | 提示框确定按钮横向位置 | 相对游戏客户区宽度的比例 |
| `dialog_confirm_top` | `0.61` | 提示框确定按钮纵向位置 | 相对游戏客户区高度的比例 |
| `quit_backpack_left` | `0.1` | 退出背包按钮横向位置 | 相对游戏客户区宽度的比例 |
| `quit_backpack_top` | `0.05` | 退出背包按钮纵向位置 | 相对游戏客户区高度的比例 |

### `[time]` 时间控制

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `round_end_wait_time` | `4` | 每轮结束等待秒数 | 网络或结算动画较慢时可增大 |
| `fish_end_wait_time` | `4` | 钓鱼成功后等待秒数 | 等待结束动画完成后再点击画面 |
| `begin_fish_wait_time` | `4` | 程序启动等待秒数 | 用于切换并聚焦游戏窗口 |
| `loop_sleep_seconds` | `0.02` | 检测循环休眠秒数 | 越小响应越快但 CPU 占用越高 |
| `longest_keep_time` | `35` | 单次 QTE 最长秒数 | 防止识别异常时永久卡在 QTE 循环 |

### `[scale]` 分辨率缩放

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `reference_window_width` | `1152` | 参考窗口宽度 | 像素数量阈值及挡板宽度以此分辨率为基准 |
| `reference_window_height` | `648` | 参考窗口高度 | 像素数量阈值及挡板高度以此分辨率为基准 |

### `[ocr]` OCR 识别

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `enabled` | `true` | OCR 总开关 | 关闭后不会自动识别地点或背包已满提示 |
| `debug_once_on_start` | `true` | 启动时 OCR 调试开关 | 当前代码会读取该值，但尚未执行对应的一次性调试流程 |
| `auto_select_strategy` | `true` | 自动选择 QTE 策略 | OCR 识别地点失败时回退到手动选择 |
| `change_location_on_missing_time` | `false` | 缺少“时”字时自动换点 | 默认关闭；OCR 波动可能导致误触发 |
| `location_left_percent` | `11` | 地点 OCR 区域左边界 | 相对游戏客户区 |
| `location_top_percent` | `8` | 地点 OCR 区域上边界 | 相对游戏客户区 |
| `location_right_percent` | `28` | 地点 OCR 区域右边界 | 相对游戏客户区 |
| `location_bottom_percent` | `15` | 地点 OCR 区域下边界 | 相对游戏客户区 |
| `backpack_full_left_percent` | `30` | 背包已满 OCR 区域左边界 | 相对游戏客户区 |
| `backpack_full_top_percent` | `20` | 背包已满 OCR 区域上边界 | 相对游戏客户区 |
| `backpack_full_right_percent` | `65` | 背包已满 OCR 区域右边界 | 相对游戏客户区 |
| `backpack_full_bottom_percent` | `30` | 背包已满 OCR 区域下边界 | 相对游戏客户区 |
| `use_cls` | `false` | OCR 文字方向分类 | 开启会增加处理步骤；普通横向中文通常无需开启 |
| `det_model_path` | 空 | OCR 检测模型路径 | 留空使用 RapidOCR 内置模型；自定义路径建议放在项目目录内以便打包 |
| `cls_model_path` | 空 | OCR 方向分类模型路径 | `use_cls=false` 时通常无需设置 |
| `rec_model_path` | 空 | OCR 文字识别模型路径 | 留空使用 RapidOCR 内置模型 |
| `rec_keys_path` | 空 | OCR 字符字典路径 | 自定义识别模型时应使用与模型匹配的字典 |

## 可能遇到的问题

- [x] 识别不到鱼上钩了（识别感叹号来判断鱼是否上钩，深渊巨口地图没有感叹号的匹配度会莫名得高——已判断黄色像素数量
- [x] 背包满了（功能完成了，需要多次测试
- [x] 对于一些干扰QTE的操作容易失败（因为出现的概率少所以不太好测试
- [x] 不同分辨率和颜色范围没有测试过（懂代码的可以自行调整代码里的颜色范围
- [x] 冰霜海峡的锁定光标需要连续点击空格的没有实现
- [ ] 不同分辨率和颜色范围提取到了配置文件，暂时方案：提交测试的工具，可自行修改；最终方案：按照游戏分辨率和颜色范围自动生成配置文件（限于设备因素应该是实现不了了）
- [x] 深渊巨口地图黄色部分有时会消失（增加黄色部分判定时间还是增加判定蓝色部分？
- [x] 深渊巨口地图出现多个光标（增加对比度来判断真的光标？
- [x] 背包清理中途点击失误的处理：暂时重新再运行一遍背包清理操作，后面检测清理背包的每个阶段再进行操作

## 开发计划

地图：没有实现的默认用寒霜海峡钓鱼策略

+ 烟波湖：
+ 浅岸：
+ 寒霜海峡：
  + [x] 光标冰冻——判断qte条是否有红色像素
  + [x] 贝壳挡住光标——只要露出黄色部分都可以判断到
  + [x] 光标隐形——疯狂点击空格
+ 深渊巨口：
  + [x] 多个光标出现——把真实光标颜色的范围缩小（历史处理方式；当前仍取白色像素最多的一列，没有多候选真假判别或对应真实样本回归，不能视为所有多光标场景均已验证）
  + [x] ~~黄色部分消失，只有绿色部分~~
  + [x] 黄色部分消失，只要蓝色部分——当黄色部分检测不到时，开始检测蓝色部分
  + [x] 产生有红色数字的泡泡——把泡泡里的黄色屏蔽掉
  + [x] 产生隔板来反弹光标行动——识别光标然后把

- [x] 引入ocr来判断当前钓鱼地点，来执行不同的钓鱼策略。（如果引入ocr，打包体积会增大。好处是自动识别钓鱼策略和不用触发三次突发时间才清理背包
  - [ ] ocr 失败时回退相关功能，但不影响钓鱼功能

- [ ] 钓鱼结束后是否多次点击屏幕

## 开发指南

如果想自己开发新的地图钓鱼策略：

1. 在 `qte_strategy.py` 里继承 `BaseQTEStrategy` 类，在 `__init__` 初始化需要使用的变量，然后实现 `play_qte` 方法

2. 在 `main.py` 里的 `QTE_STRATEGIES_MAP` 增加刚新增的策略类

## 配置文件说明

程序从 `config.ini` 读取配置。下表中的“变量值”是仓库当前配置值，修改前建议保留一份可正常运行的配置。

- `*_percent` 使用 `0～100` 的百分比；`left/top/right/bottom` 分别表示区域的左、上、右、下边界。
- 背包点击坐标使用 `0～1` 的窗口比例，超出该范围可能点击到游戏窗口外。
- OpenCV HSV 中，Hue（色相）范围为 `0～180`，Saturation（饱和度）和 Value（明度）范围为 `0～255`。
- HSV 下限应小于或等于对应上限。颜色、坐标和像素阈值可能因分辨率、显示设置及游戏画面亮度而需要调整。

### `[hook]` 上钩检测

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `top_percent` | `25` | 感叹号区域上边界 | 相对游戏客户区 |
| `bottom_percent` | `36` | 感叹号区域下边界 | 相对游戏客户区 |
| `left_percent` | `49` | 感叹号区域左边界 | 相对游戏客户区 |
| `right_percent` | `51` | 感叹号区域右边界 | 相对游戏客户区 |
| `hook_lower_hue` | `20` | 上钩黄色色相下限 | 只用于感叹号黄色遮罩 |
| `hook_lower_saturation` | `35` | 上钩黄色饱和度下限 |  |
| `hook_lower_value` | `210` | 上钩黄色明度下限 |  |
| `hook_upper_hue` | `35` | 上钩黄色色相上限 | 夜间实测感叹号包含 H=31～34 的像素 |
| `hook_upper_saturation` | `120` | 上钩黄色饱和度上限 |  |
| `hook_upper_value` | `255` | 上钩黄色明度上限 |  |

### `[roi]` QTE 截图、颜色与挡板

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `top_percent` | `82` | QTE 整体区域上边界 | 相对游戏客户区 |
| `bottom_percent` | `90` | QTE 整体区域下边界 | 相对游戏客户区 |
| `left_percent` | `32` | QTE 整体区域左边界 | 相对游戏客户区 |
| `right_percent` | `65` | QTE 整体区域右边界 | 相对游戏客户区 |
| `time_top_percent` | `0` | 倒计时条上边界 | 相对 QTE 整体截图区域 |
| `time_bottom_percent` | `100` | 倒计时条下边界 | 相对 QTE 整体截图区域 |
| `time_left_percent` | `0` | 倒计时条左边界 | 相对 QTE 整体截图区域 |
| `time_right_percent` | `18` | 倒计时条右边界 | 相对 QTE 整体截图区域 |
| `qte_top_percent` | `50` | QTE 条上边界 | 相对 QTE 整体截图区域 |
| `qte_bottom_percent` | `97` | QTE 条下边界 | 相对 QTE 整体截图区域 |
| `qte_left_percent` | `22` | QTE 条左边界 | 相对 QTE 整体截图区域 |
| `qte_right_percent` | `100` | QTE 条右边界 | 相对 QTE 整体截图区域 |
| `time_lower_green_hue` | `65` | 倒计时绿色色相下限 |  |
| `time_lower_green_saturation` | `185` | 倒计时绿色饱和度下限 |  |
| `time_lower_green_value` | `210` | 倒计时绿色明度下限 |  |
| `time_upper_green_hue` | `75` | 倒计时绿色色相上限 |  |
| `time_upper_green_saturation` | `195` | 倒计时绿色饱和度上限 |  |
| `time_upper_green_value` | `255` | 倒计时绿色明度上限 |  |
| `time_lower_red_hue` | `170` | 倒计时红色色相下限 |  |
| `time_lower_red_saturation` | `155` | 倒计时红色饱和度下限 |  |
| `time_lower_red_value` | `240` | 倒计时红色明度下限 |  |
| `time_upper_red_hue` | `180` | 倒计时红色色相上限 |  |
| `time_upper_red_saturation` | `170` | 倒计时红色饱和度上限 |  |
| `time_upper_red_value` | `255` | 倒计时红色明度上限 |  |
| `yellow_lower_hue` | `20` | QTE 黄色色相下限 | 黄色区域按键判定 |
| `yellow_lower_saturation` | `125` | QTE 黄色饱和度下限 |  |
| `yellow_lower_value` | `220` | QTE 黄色明度下限 |  |
| `yellow_upper_hue` | `30` | QTE 黄色色相上限 |  |
| `yellow_upper_saturation` | `255` | QTE 黄色饱和度上限 |  |
| `yellow_upper_value` | `255` | QTE 黄色明度上限 |  |
| `red_lower_hue` | `170` | 破冰红色色相下限 | Frost 策略用于检测破冰提示 |
| `red_lower_saturation` | `100` | 破冰红色饱和度下限 |  |
| `red_lower_value` | `100` | 破冰红色明度下限 |  |
| `red_upper_hue` | `180` | 破冰红色色相上限 |  |
| `red_upper_saturation` | `255` | 破冰红色饱和度上限 |  |
| `red_upper_value` | `255` | 破冰红色明度上限 |  |
| `blue_lower_hue` | `95` | QTE 蓝色色相下限 | Abyss 策略在有效范围没有黄色时使用 |
| `blue_lower_saturation` | `105` | QTE 蓝色饱和度下限 |  |
| `blue_lower_value` | `255` | QTE 蓝色明度下限 |  |
| `blue_upper_hue` | `102` | QTE 蓝色色相上限 |  |
| `blue_upper_saturation` | `255` | QTE 蓝色饱和度上限 |  |
| `blue_upper_value` | `255` | QTE 蓝色明度上限 |  |
| `white_lower_hue` | `0` | 光标白色色相下限 | 用于定位 QTE 光标 |
| `white_lower_saturation` | `0` | 光标白色饱和度下限 | 饱和度范围过大会把挡板识别成光标 |
| `white_lower_value` | `240` | 光标白色明度下限 |  |
| `white_upper_hue` | `180` | 光标白色色相上限 | 白色低饱和时色相通常不稳定，因此覆盖完整色相范围 |
| `white_upper_saturation` | `10` | 光标白色饱和度上限 | 与挡板饱和度范围分离 |
| `white_upper_value` | `255` | 光标白色明度上限 |  |
| `blocker_one_lower_hue` | `0` | 挡板区间一色相下限 | 两组挡板 HSV 遮罩最终取并集 |
| `blocker_one_lower_saturation` | `25` | 挡板区间一饱和度下限 |  |
| `blocker_one_lower_value` | `230` | 挡板区间一明度下限 |  |
| `blocker_one_upper_hue` | `180` | 挡板区间一色相上限 |  |
| `blocker_one_upper_saturation` | `52` | 挡板区间一饱和度上限 |  |
| `blocker_one_upper_value` | `255` | 挡板区间一明度上限 |  |
| `blocker_two_lower_hue` | `0` | 挡板区间二色相下限 | 用于覆盖另一种亮度或透明状态 |
| `blocker_two_lower_saturation` | `0` | 挡板区间二饱和度下限 |  |
| `blocker_two_lower_value` | `200` | 挡板区间二明度下限 |  |
| `blocker_two_upper_hue` | `180` | 挡板区间二色相上限 |  |
| `blocker_two_upper_saturation` | `10` | 挡板区间二饱和度上限 | 需注意不要覆盖光标范围过多 |
| `blocker_two_upper_value` | `245` | 挡板区间二明度上限 |  |
| `blocker_shape_min_width` | `4` | 挡板轮廓最小宽度 | 参考分辨率下的像素值；实际按窗口宽度缩放，判断不包含等于下限的轮廓 |
| `blocker_shape_max_width` | `20` | 挡板轮廓最大宽度 | 参考分辨率下的像素值；实际按窗口宽度缩放，判断不包含等于上限的轮廓 |
| `blocker_shape_min_height` | `18` | 挡板轮廓最小高度 | 参考分辨率下的像素值；实际按窗口高度缩放，判断不包含等于下限的轮廓 |
| `blocker_shape_max_height` | `100` | 挡板轮廓最大高度 | 参考分辨率下的像素值；实际按窗口高度缩放，判断不包含等于上限的轮廓 |

### `[backpack]` 背包清理

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `auto_clear_enabled` | `true` | 自动清理开关 | false 时满包停止待机，不自动出售 |
| `button_click_interval_seconds` | `2` | 按钮点击间隔秒数 | 网络或动画较慢时可适当增大 |
| `one_click_sale_left` | `0.87` | 一键出售按钮横向位置 | 相对游戏客户区宽度的比例 |
| `one_click_sale_top` | `0.92` | 一键出售按钮纵向位置 | 相对游戏客户区高度的比例 |
| `select_all_left` | `0.82` | 全选按钮横向位置 | 相对游戏客户区宽度的比例 |
| `select_all_top` | `0.92` | 全选按钮纵向位置 | 相对游戏客户区高度的比例 |
| `circle_check_left` | `0.92` | 圆形确认按钮横向位置 | 相对游戏客户区宽度的比例 |
| `circle_check_top` | `0.92` | 圆形确认按钮纵向位置 | 相对游戏客户区高度的比例 |
| `dialog_confirm_left` | `0.57` | 提示框确定按钮横向位置 | 相对游戏客户区宽度的比例 |
| `dialog_confirm_top` | `0.61` | 提示框确定按钮纵向位置 | 相对游戏客户区高度的比例 |
| `quit_backpack_left` | `0.1` | 退出背包按钮横向位置 | 相对游戏客户区宽度的比例 |
| `quit_backpack_top` | `0.05` | 退出背包按钮纵向位置 | 相对游戏客户区高度的比例 |

### `[time]` 时间控制

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `round_end_wait_time` | `4` | 每轮结束等待秒数 | 网络或结算动画较慢时可增大 |
| `fish_end_wait_time` | `4` | 钓鱼成功后等待秒数 | 等待结束动画完成后再点击画面 |
| `begin_fish_wait_time` | `4` | 程序启动等待秒数 | 用于切换并聚焦游戏窗口 |
| `loop_sleep_seconds` | `0.02` | 检测循环休眠秒数 | 越小响应越快但 CPU 占用越高 |
| `longest_keep_time` | `35` | 单次 QTE 最长秒数 | 防止识别异常时永久卡在 QTE 循环 |

### `[scale]` 分辨率缩放

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `reference_window_width` | `1152` | 参考窗口宽度 | 像素数量阈值及挡板宽度以此分辨率为基准 |
| `reference_window_height` | `648` | 参考窗口高度 | 像素数量阈值及挡板高度以此分辨率为基准 |

### `[ocr]` OCR 识别

| 变量名 | 变量值 | 中文名 | 备注 |
| --- | ---: | --- | --- |
| `enabled` | `true` | OCR 总开关 | 关闭后不会自动识别地点或背包已满提示 |
| `debug_once_on_start` | `true` | 启动时 OCR 调试开关 | 当前代码会读取该值，但尚未执行对应的一次性调试流程 |
| `auto_select_strategy` | `true` | 自动选择 QTE 策略 | OCR 识别地点失败时回退到手动选择 |
| `change_location_on_missing_time` | `false` | 缺少“时”字时自动换点 | 默认关闭；OCR 波动可能导致误触发 |
| `location_left_percent` | `11` | 地点 OCR 区域左边界 | 相对游戏客户区 |
| `location_top_percent` | `8` | 地点 OCR 区域上边界 | 相对游戏客户区 |
| `location_right_percent` | `28` | 地点 OCR 区域右边界 | 相对游戏客户区 |
| `location_bottom_percent` | `15` | 地点 OCR 区域下边界 | 相对游戏客户区 |
| `backpack_full_left_percent` | `30` | 背包已满 OCR 区域左边界 | 相对游戏客户区 |
| `backpack_full_top_percent` | `20` | 背包已满 OCR 区域上边界 | 相对游戏客户区 |
| `backpack_full_right_percent` | `65` | 背包已满 OCR 区域右边界 | 相对游戏客户区 |
| `backpack_full_bottom_percent` | `30` | 背包已满 OCR 区域下边界 | 相对游戏客户区 |
| `use_cls` | `false` | OCR 文字方向分类 | 开启会增加处理步骤；普通横向中文通常无需开启 |
| `det_model_path` | 空 | OCR 检测模型路径 | 留空使用 RapidOCR 内置模型；自定义路径建议放在项目目录内以便打包 |
| `cls_model_path` | 空 | OCR 方向分类模型路径 | `use_cls=false` 时通常无需设置 |
| `rec_model_path` | 空 | OCR 文字识别模型路径 | 留空使用 RapidOCR 内置模型 |
| `rec_keys_path` | 空 | OCR 字符字典路径 | 自定义识别模型时应使用与模型匹配的字典 |

## 所使用的开源库

+ [mss](https://github.com/BoboTiG/python-mss/issues) —— —— 窗口截图
+ [dxcam](https://github.com/ra1nty/DXcam) —— 窗口截图
+ [opencv](https://github.com/opencv/opencv) —— 图像操作
+ [onnxruntime](https://github.com/microsoft/onnxruntime)
+ [rapidocr]() —— OCR支持
+ [pydirectinput](https://github.com/learncodebygaming/pydirectinput) —— 模拟操作
+ [pywin32](https://github.com/mhammond/pywin32) —— Windows API
+ [numpy](https://github.com/numpy/numpy)
