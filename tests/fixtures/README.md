# 测试样本目录

此目录保存离线回归使用的原始截图和元数据；运行时匹配模板位于 [game/fishing/assets](../../bd2_fishing/game/fishing/assets/README.md)。真实诊断日志和完整录制留在本地 `.local/diagnostics/`（旧记录已归入本机 archive）。

| 样本 | 用途 |
| --- | --- |
| 下方 `night_*.png` | 夜间上钩黄色阈值的真实正负例 |
| [hook_small_window/](hook_small_window/README.md) | 小窗口等待上钩与遮挡排查 |
| [catch_result/](catch_result/README.md) | 奖励结算与疑似逃脱判断 |
| [qte_feedback/manifest.json](qte_feedback/manifest.json) | QTE 反馈字样及逐帧回归样本 |

## 夜间上钩识别回归样本

这些文件仅包含 23×76 像素的检测区域，无需连接游戏即可运行测试。

- `night_hook_178.png`：2026-09-07 15:53 实测保存的峰值原图，旧范围识别 178 像素，新范围识别 249 像素。
- `night_hook_183.png`：同次实测下一份诊断中的峰值原图，旧范围 183，新范围 233。
- `night_without_hook.png`：用户提供的夜间 QTE 截图中相同检测区域，不含上钩感叹号，新范围识别 0 像素。

原图均未缩放或调色。新范围仅将 H 上限从 30 改到 35，其余 HSV 条件和像素数量阈值不变。
