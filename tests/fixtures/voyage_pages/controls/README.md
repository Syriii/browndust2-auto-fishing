# 岛屿导航控件与确认框

2026-09-11 用户补图与源码实测帧，均按原样保存。尺寸、来源、用户解释与 SHA-256 见 [manifest.json](manifest.json)。这些图片没有标题栏，不能套用上级目录七张图的标题栏裁剪。

| 原图 | 语义与当前识别 |
| --- | --- |
| [island_navigation_controls.png](island_navigation_controls.png) | 左上“更改”直接进入地图；识别岛屿名和按钮，执行前另须确认待机。右上船锚是退出入口 |
| [return_to_dock_confirmation.png](return_to_dock_confirmation.png) | 返回码头；独立识别为返回确认，禁止作为结算关闭或自动换岛确认 |
| [travel_consumables_confirmation.png](travel_consumables_confirmation.png) | 12:14 源码点击深渊巨口启航后的原帧；前往钓鱼地区、目的地、消耗品失效提示与确认按钮 |
| [travel_confirmation_user.png](travel_confirmation_user.png) | 用户补图并明确授权：普通换岛确认可直接确认；作为另一尺寸的 OCR 回归，不用于生成模板 |

两类弹窗的标题、正文分别生成小范围灰度模板，来源和裁剪见运行时 [assets/README.md](../../../../bd2_fishing/game/fishing/assets/README.md)。原始整图不改写。快速分类只区分弹窗；换岛目的地与确认位置仍由导航 OCR 核对，不把模板命中当作点击授权。

当前源码默认在目标一致时确认换岛一次并等待到达；返回码头仍保留现场并提示。两者均提示移除消耗品效果，不推断物品返还。许可证购买是另一类动作，仍不自动执行。


`island_day_name_unreadable.png` 来自 13:03:09 源码初始化原帧。待机、使用时间、更改均正常，OCR 将岛名误读为“正特兰蒂斯”。回归要求岛名为未知且更改入口可识别；执行器仍须另行确认待机，进入地图后重新核对目标，不为此误读添加猜测别名。


## 返回码头补充样本

[return_to_dock_user_holdout.png](return_to_dock_user_holdout.png) 为用户另行提供的 938×524 原图，未生成或调整运行时模板。现有模板识别为 `return_to_dock`，航海 OCR 可定位蓝色确认按钮；专用恢复的返回阶段可使用这张同类提示作为回归依据。

用户明确说明：这不是游戏 Bug 完整处理过程的截图，仅假定 Bug 后 Esc 的返回提示相同。仍缺少关闭 150402 后、Esc 前以及实际退出重进全过程的原帧。因此样本通过只证明返回框识别，不证明游戏 Bug 恢复实测成功。普通导航仍不自动确认返回，仅既有 150402 专用恢复上下文使用此动作。
