# Fishing Voyage 入口与地图原始样本

2026-09-11 用户先后提供七张截图及页面说明。所有 PNG 均原样复制，947 × 564，包含 Windows 标题栏和边框；未裁剪、缩放或调色。来源文件名、尺寸和 SHA-256 见 [manifest.json](manifest.json)。

这七张图已用于 `tests/integration/test_voyage_navigation.py` 的真实 OCR 和图像回归，运行时不会加载测试图片。详细依据、源码导航与实测范围见[入口、选岛与许可证](../../../docs/reference/voyage-navigation.md)。

| 编号 | 原图 | 用户说明 |
| --- | --- | --- |
| 1 | [01_loading.png](01_loading.png) | 加载过场 |
| 2 | [02_dock.png](02_dock.png) | 码头，开始钓鱼进入地图 |
| 3 | [03_map_yanbo.png](03_map_yanbo.png) | 选中烟波湖，启航进入钓鱼 |
| 4 | [04_map_shallow_panned.png](04_map_shallow_panned.png) | 拖动地图，选中浅岸，左侧可见锁定岛屿 |
| 5 | [05_sky_before_license.png](05_sky_before_license.png) | 天空岛未解锁，推荐等级红色，需要购买许可证 |
| 6 | [06_sky_after_license.png](06_sky_after_license.png) | 用户购买后，图标和按钮变化，推荐等级仍为红色 |
| 7 | [07_atlantis_fish_unlocks.png](07_atlantis_fish_unlocks.png) | 亚特兰蒂斯；黑色剪影为未解锁的鱼，彩色图标为已解锁的鱼 |

图 7 人工核对为 3 行 × 5 列，共 15 格，其中第 3 行第 4、5 列为未解锁剪影，其余 13 格为已解锁图标。格位按从上到下、从左到右计数，从 1 开始；这是参考标注，不是识别程序测试结果。解锁条件和具体鱼名尚未由此图确认。

图 5 是用户目前无法重新取得的购买前状态，必须保留，不能被图 6 或后续录制覆盖。该购买由用户完成，本次只归档，不重现购买。

另有两张[岛屿导航控件与返回确认图](controls/README.md)，单独保存用户裁切范围及元数据，不能套用上表七张整窗图的客户区裁剪。

截图的整窗尺寸不等于游戏客户区尺寸。七张图的客户区为 `(left=1, top=31, right=946, bottom=563)`，半开区间，得到 945×532；与本次原生窗口客户区尺寸及控件位置核对一致。测试在内存中裁剪，原图保持不变。
