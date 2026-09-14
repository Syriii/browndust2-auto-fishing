# 开发脚本

[完整工具说明](../docs/development/tools.md) · [构建说明](../docs/development/releasing.md)

从仓库根目录用 `.venv/Scripts/python.exe` 运行，先按开发指南完成可编辑安装。

| 目录或脚本 | 用途 |
| --- | --- |
| benchmarks/ | 可重复离线局部基准，输出 .local/benchmarks |
| checks/ | UI 模拟与只读截图检查；截图工具需真实桌面，不能当作离线测试 |
| live/ | 真实钓鱼诊断、QTE 录制与一次清包，仅按实机任务授权执行 |
| build_release.py | 构建到 `dist/`，中间文件位于 `build/` |
| lock_environment.py | 生成 requirements 中的 Windows 依赖锁定清单 |

可复用实现放 bd2_fishing，此处保持参数解析与调用入口。默认配置和个人配置路径见[配置说明](../docs/user/configuration.md)。

2026-09-14 审查发现 `live/clean_backpack_once.py` 尚未启用前台窗口检查，也缺少统一异常释放；底层出售步骤缺逐步页面确认。不能将主界面的失焦保护视为所有实机脚本都已具备，问题和修复要求见[代码审查 R1/R2](../docs/development/code-review-2026-09-14.md)。离线审核不运行 `live/` 工具。
