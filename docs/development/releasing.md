# 构建与发布

[文档目录](../README.md) · [开发指南](guide.md) · [分支与版本约定](branching.md)

以下命令在仓库根目录执行。源码、候选构建、GitHub 发布和本机部署分别管理。

## 构建环境

Windows x64、Python 3.12，复用现有 .venv；首次创建环境后安装已验证的锁定清单：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/windows-py312.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

已有环境跳过创建步骤。依赖声明和锁定方式见[依赖管理](../../requirements/README.md)。

## 配置与 OCR 模型

构建读取 `bd2_fishing/resources/default.ini`，不读取个人 `.local/config.ini`。默认配置随包发布，首次运行便携版时在 EXE 旁生成 config/config.ini；已有用户配置优先。

默认使用 RapidOCR 包内置模型。default.ini 的 [ocr] 下 det_model_path、cls_model_path、rec_model_path、rec_keys_path 留空即可。构建自定义模型版本时，在这份发布默认配置填写路径，并将文件放在仓库内；构建脚本拒绝仓库外模型，避免产物依赖本机绝对路径。

## 构建与产物

Python 包安装和 wheel 构建的 egg-info 写入 `build/`，中间文件写入 `build/setuptools/`。setup.py 只配置这两个位置并自动创建目录；继续使用 pip/标准构建后端，不直接运行 setup.py 命令。

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -B scripts/build_release.py
```

需要保留 NVIDIA 相关二进制时使用 `--nvidia`。默认产物：

- `dist/BD2_AutoFishing/`：完整便携目录。
- `dist/BD2_AutoFishing-windows.zip`：分发 ZIP。
- `dist/BD2_AutoFishing-windows.zip.sha256`：分发包校验值。
- `dist/README.txt`：交付整理时补充当前包版本、使用方式与验证范围，构建脚本不自动生成。
- `build/pyinstaller/`、`build/specs/`：中间文件与 spec。

需要保留正在使用的旧候选包时，使用 `--output-dir dist/<新版本目录>`。
该选项仅允许项目 dist 内的路径；指定目录已有同名应用时拒绝覆盖，须另选目录。
EXE、运行库及 ZIP 均生成到该目录，不更新 deployment，也不复制个人配置和运行记录。

`dist/` 最终只保留一套当前交付产物，直接使用上述固定路径。独立候选子目录仅用于构建和验证，
选定最终包后将其内容整理到 dist 根目录，旧候选和附带运行记录归档到本机工作区的
`archive/builds/`；不要长期累积 candidate、ui、mechanisms、final 等目录。移动前确认程序退出，
检查数据和目标路径，移动后核对文件哈希。构建日志、校验报告放 `.local/maintenance/`。
此归档是交付整理步骤，构建脚本不会自动删除历史文件或更新 deployment。

窗口图标和 EXE 图标统一来自 `bd2_fishing/resources/icons/app.ico`。Python 包资源清单与 PyInstaller 均包含图标，缺失 ICO 时构建失败。

默认构建无控制台 Tk 图形版。脚本检查 init.tcl、tk.tcl 和 _tkinter.pyd，缺少任何一个即失败，不交付缺少界面的 ZIP。部分受限沙箱无法访问本机 Tcl 资源，应在正常 Windows 会话构建并验证。

构建后清理 OpenCV 的 FFmpeg 视频 DLL，因为项目没有使用 cv2.VideoCapture/VideoWriter；以后加入视频功能前须重新评估此步骤。

## 验证候选包

离线回归和 Tk 模拟检查分别运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/smoke_ui.py
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/smoke_updates.py
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/check_portable_package.py dist/BD2_AutoFishing --report .local/maintenance/package-check.json
```

包装核对包含全部 Python 模块、默认 INI、识别模板、3 个 OCR 模型、Tcl/Tk 和 ZIP 完整性。需要手动预览候选 EXE 时可运行：

```powershell
.\dist\BD2_AutoFishing\BD2_AutoFishing.exe --preview
```

预览不连接游戏、不保存设置。真实游戏验收另按任务范围安排，并先关闭其他钓鱼进程。离线回归、Tk 检查、构建成功和 EXE 实机验收是不同结论。

## GitHub 构建

推送分支或创建 PR 运行 ci.yml 的代码检查；合并 main 不自动创建版本。发布时按
[分支约定](branching.md)选择已验证提交，将版本和标签固定，再创建 GitHub Release。

`.github/workflows/build.yml` 在 Release 发布或手动触发时运行，使用 Windows + Python 3.12.4，安装 requirements 中的锁定环境和本项目，运行离线回归与 scripts/build_release.py，上传 `dist/BD2_AutoFishing-windows.zip` 及同名 `.zip.sha256` 校验文件。发布 Release 时必须同时附加这两项，tag 采用与 pyproject 版本一致的 `v主.次.修订`。

本地构建不自动提交、推送或发布。若使用自定义模型，文件也必须存在于远程检出内容中。

发布操作顺序：

1. 在短期分支完成版本号、CHANGELOG、实现与必要验证，创建 PR，CI 通过后合并 main。
2. 在 GitHub Releases 创建发布，选择该 main 提交，新建与 pyproject 一致的标签并填写本版说明。
3. 发布正式 Release，等待 Build Release Package 成功上传完整 ZIP 与校验文件。
4. 实际下载验证 SHA-256、包内版本与文件清单，并检查旧版本发现更新、当前版本无更新。
5. 在状态文档记录结果及实机覆盖范围；后续文档合并不会重建已发布附件。

当前 v0.2.0 已完成以上发布链路，结果见[开发状态](status.md)。下一次发布使用新版本号与新标签，不移动已发布标签或覆盖旧附件。

发布后检查 Actions 的 Build Release Package 成功，并确认 Release 的 Assets 同时包含
Windows ZIP 和同名 SHA-256 文件。附件尚未上传时更新器会提示缺少兼容包；失败时先查 Actions
日志，不将“已创建 Release 页面”当作发布完成。发布说明明确实机覆盖范围，后续纯文档修改无需重发 EXE。

## 本机部署

本机工作区的用户版本位于外层 `deployment/`。仅明确要求部署时执行；普通构建只生成源码 `dist/`。

1. 确认目标程序退出，将旧 EXE、_internal 和配置备份到本机 archive 中带时间戳的目录。
2. 优先通过新版程序导入候选 ZIP 更新；旧版首次迁移时成套包含主 EXE、更新助手、_internal 与 manifest，保留用户配置、日志和证据。
3. 核对部署文件与构建产物哈希，再按授权范围验收。

deployment 是维护者本机约定，不是普通用户需要建立的目录。GitHub 发布不等于本机部署；递归移动或删除前核对解析后的绝对路径，使用 PowerShell 原生文件命令。

## 新版更新协议

构建版本取自 pyproject.toml；助手独立 onefile，主程序保持 onedir。程序目录不携带个人配置；生成 manifest.json 后再压缩 ZIP，并生成 ZIP SHA-256。所有运行文件纳入清单，更新时自动处理过期依赖。首次迁移旧版和手动 ZIP 导入见[使用说明](../user/updating.md)，事务约束见[设计](../design/portable-update.md)。
