# 离线回归

| 目录 | 范围 |
| --- | --- |
| unit/ | 抛竿提示、重试、上钩、QTE 反馈与决策证据等局部规则 |
| integration/ | 任务生命周期、取消与输入、窗口适配、诊断、工具和包装协作，使用模拟依赖 |
| fixtures/ | 真实识别样本，来源和用途见目录内 README |
| support.py | 仓库、包默认配置与样本路径 |

从仓库根目录执行全部离线回归，不连接游戏或发送真实输入：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
```

需要缩小范围可运行 `-m unittest tests.unit.test_night_hook -v`。测试不以 .local/config.ini 的个人参数为基准，需要写配置时使用临时目录。Tk 模拟检查位于 scripts/checks/smoke_ui.py，真实游戏采样位于 scripts/live/。
