# 便携发布与更新设计

2026-09-10：以完整 ZIP 作为唯一分发/更新载体，借鉴 MAA 的本地包导入体验。首次解压，之后在线下载或文件选择共用准备、校验与事务更新。无安装器、系统服务或注册表依赖；不实施单文件主程序，不做 OTA。

## 职责边界

| 位置 | 职责 |
| --- | --- |
| `ui/updates.py` | 更新与存储窗口、主线程状态、后台结果队列、待机维护调度 |
| `app/updates.py` | 在线/本地包用例、版本限制、准备更新助手、重启交接 |
| `app/startup.py` | 配置导入、补齐、修复与首次环境报告 |
| `infrastructure/updates/package.py` | 清单协议、路径约束、ZIP 解压及逐文件 SHA-256 |
| `infrastructure/updates/github.py` | 固定官方仓库的正式 Release 查询、有界 HTTPS 下载 |
| `infrastructure/updates/transaction.py` | 安装实例锁、旧文件备份、替换、恢复日志与回滚 |
| `infrastructure/updates/runner.py` | 独立更新进程入口，主进程退出后执行并重启待机 |
| `infrastructure/maintenance.py` | 日志/证据保留及整份更新事务缓存清理 |
| `scripts/build_release.py` | 主程序 onedir、助手 onefile、manifest 与 ZIP/校验文件生成 |

不改变 game、runtime 的输入控制与 QTE 时序。UI 只通过 app 服务访问更新/维护实现。

## 数据所有权

只允许清单管理主 EXE、更新助手和 `_internal/` 内文件。`manifest.json` 由更新事务独立提交。配置、数据、日志、截图和未知个人文件不允许出现在包内程序清单，也不在旧文件删除范围。

没有旧清单的过渡目录仅接管已知 EXE、助手和 `_internal`。有清单时按旧清单减去新清单删除过期依赖，不采用全目录清空白名单。路径检查拒绝穿越、Windows ADS/设备名、大小写重复 ZIP 项及符号链接/目录联接。

## 更新生命周期

1. 待机查 GitHub 最新正式 Release，比较三段数字版本；缺少兼容 ZIP/校验文件时明确提示。
2. 下载至独立 `cache/updates/<uuid>`；本地文件选择从同一步开始校验。在线包额外校验 Release 的 ZIP SHA-256。
3. 按清单手动解压至 `stage`，限制 ZIP 条目数量、总解压体积及清单大小；核对每个文件大小及 SHA-256，拒绝夹带数据。相同版本允许修复，禁止降级。
4. 用户确认重启后，写 pending 指针，启动缓存中的独立助手。主程序持有安装锁直至退出；助手等待该锁，不在任务中替换。
5. 助手再次校验 stage；先备份所有受影响旧文件，写恢复日志，再替换、删除旧依赖、提交 manifest、校验完整安装。
6. 异常时恢复已备份文件，移除本次新增文件；恢复失败保留日志。成功或恢复后清除 pending、写结果，再启动主程序待机。
7. 断电/终止导致 pending 留存时，下次启动优先交给缓存助手恢复。主程序无法打开时可手动运行根目录助手。恢复是尽力操作，不承诺磁盘损坏等情形一定成功。

助手使用独立 onefile，运行时解压自己的小型标准库到临时目录；主程序运行库长期放 `_internal`。这笔启动成本不进入钓鱼循环。复制助手至 cache 后运行，避免助手自身和主依赖被占用。

## 验证边界

离线测试必须覆盖文件保留、过期依赖删除、损坏/非法包、被占用文件、部分替换失败、进程中断恢复、配置幂等、锁互斥、保留策略和网络失败。EXE 验证需在隔离目录进行，不覆盖现用 deployment、不启动游戏任务。

公开 GitHub Release 的下载链路需要发布符合新协议的资产后再验收；本地构建不等于已发布。第一版未实现拖放、自动静默安装、增量更新或包签名。

参考：[MAA 手动更新说明](https://docs.maa.plus/zh-cn/manual/introduction/others.html#手动更新)、[MAA 更新助手](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/src/MaaUpdater/main.cpp)、[GitHub Releases API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)。
