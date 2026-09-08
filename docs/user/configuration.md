# 配置说明

[文档目录](../README.md) · [使用指南](usage.md)

## 位置与保存

源码运行读取 `.local/config.ini`；便携版读取 EXE 旁的 `config.ini`；普通 wheel 安装读取用户主目录下 `BD2_AutoFishing/config.ini`。配置不存在时，[settings.py](../../bd2_fishing/infrastructure/settings.py) 从唯一的[默认配置资源](../../bd2_fishing/resources/default.ini)生成。路径不随终端当前目录变化。本次已将原源码 config.ini 原样移入 .local，保留个人取值和注释。

点击开始时保存界面管理的选项并应用到本次任务；保存保留其他配置项及注释。已有配置中的明确取值优先于新版本默认值。手动修改后，在下一次启动任务时应用。

## 常用开关

| 配置项 | 当前默认值 | 含义 |
| --- | --- | --- |
| `[app] location` | 自动识别 | 页面启动时选中的钓场 |
| `[app] prevent_sleep` | `false` | 仅运行期间保持唤醒 |
| `[backpack] auto_clear_enabled` | `true` | 满包后自动出售；关闭则满包停止 |
| `[ocr] enabled` | `true` | OCR 总开关，影响地点及满包等文字判断 |
| `[diagnostics] qte_detail_log` | `false` | 逐帧诊断写入文件，不刷页面 |
| `[diagnostics] failure_max_events` | `100` | 各类失败证据分别保留的最大数量 |
| `[diagnostics] max_events` | `10` | 成功结算证据的最大数量 |

## 各配置段用途

| 配置段 | 配置内容 | 坐标或单位 |
| --- | --- | --- |
| `[hook]` | 等待上钩感叹号 ROI、黄色 HSV 范围 | ROI 为客户区百分比 |
| `[roi]` | QTE 总区域、倒计时与色条裁剪、颜色范围、挡板尺寸和按键容差 | 总区域为客户区百分比；子区域相对总区域；尺寸与容差为参考分辨率像素 |
| `[backpack]` | 自动清包、按钮坐标、点击间隔 | 按钮为客户区比例，间隔为秒 |
| `[time]` | 开始、结束等待，QTE 持续上限及循环节流 | 秒 |
| `[scale]` | 像素阈值缩放使用的参考窗口尺寸 | 像素 |
| `[ocr]` | OCR 开关、自动钓场选择、识别区域、自定义模型 | 区域为客户区百分比 |
| `[app]` | 页面初始钓场与电源选项 | 见常用开关 |
| `[diagnostics]` | 可选逐帧日志与必要取证的保留数量 | 数量为诊断包 |

完整键名、默认值及注释以 [default.ini](../../bd2_fishing/resources/default.ini) 为准；代码直接读取这份资源，不再重复维护缺省配置字符串。截图沿用 BGR 格式，再转换到 OpenCV HSV，不能套用 RGB 色值。

## 识别调整

先区分等待上钩与 QTE 阶段，再核对对应 ROI、客户区大小、缩放及坐标。夜间上钩黄色色相上限为 35，已有正负例回归；不要只凭另一时刻的 QTE 图或一条超时日志改阈值。

`[ocr] change_location_on_missing_time` 默认关闭，控制未识别到“时”时是否切换钓场。修改 ROI 或颜色前，先保存[同次诊断证据](diagnostics.md)，避免把遮挡、无新帧或阶段变化误认为阈值错误。

## OCR 模型

`[ocr]` 下 `det_model_path`、`cls_model_path`、`rec_model_path` 和 `rec_keys_path` 留空时使用 RapidOCR 包内置模型。源码自定义相对路径以仓库根目录解析；便携包内资源从 PyInstaller 资源目录解析。

需要打包自定义模型时，文件必须放在仓库内，详见[构建与发布](../development/releasing.md)。
