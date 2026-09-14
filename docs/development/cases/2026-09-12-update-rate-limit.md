# 更新查询 HTTP 403 修复

用户持续遇到 HTTP Error 403: rate limit exceeded。旧 github.latest_release 每次直接请求匿名 REST API，没有缓存和退避；启动回调把更新与存储维护异常混为一条提示。

0.3.6 查询官方 releases/latest 的 HEAD 跳转，严格核对仓库及三段正式版本标签，构造固定版本附件地址，更新下载与解包校验不变。持久缓存保存在 cache/release-check.json，只保存标签和时间，不缓存任意下载域名。成功缓存一小时，手动刷新至少一分钟，限流尊重响应头，默认一小时，其他联网失败五分钟。缓存读写失败不会阻断成功查询；内存仍保存本进程冷却。

维护回调独立保存 storage_error 和 update_error：清理失败不妨碍查询，查询失败不声称清理失败。冷却命中记 INFO，不重复 WARN；详细异常放 DEBUG。未查到高于本机测试版本的正式版不再声称当前是正式最新版。

515 项完整离线测试、36 项更新专项、Ruff/格式/架构与隐藏更新窗口通过。真实网络通过修复后的 ReleaseChecker 访问官方 latest：200，落到 v0.3.1。随后新建实例并手动检查，读取缓存，总计只有一次请求，没有 API 调用。结果见 .local/maintenance/update-403-20260912/live-result.json。没有游戏操作，也没有安装远程发布包。

官方参考：
- https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases
- https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api

不能保证 GitHub 网站或国内网络始终可用；网站也返回限流时冷却后再检查，仍提供手动 ZIP 更新入口。
