# 构建与发布

[文档目录](../README.md) · [开发指南](guide.md)

以下命令在仓库根目录执行。源码、候选构建、GitHub 发布和本机部署分别管理。

## 构建环境

Windows、Python 3.12，复用现有 .venv；首次安装使用已验证的锁定清单：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements/windows-py312.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

依赖声明和锁定方式见[依赖管理](../../requirements/README.md)。本轮未升级依赖。

## 配置与 OCR 模型

构建读取 `bd2_fishing/resources/default.ini`，不读取个人 `.local/config.ini`。默认配置随包发布，首次运行便携版时在 EXE 旁生成 config.ini；已有用户配置优先。

默认使用 RapidOCR 包内置模型。default.ini 的 [ocr] 下 det_model_path、cls_model_path、rec_model_path、rec_keys_path 留空即可。构建自定义模型版本时，在这份发布默认配置填写路径，并将文件放在仓库内；构建脚本拒绝仓库外模型，避免产物依赖本机绝对路径。

## 构建与产物

Python 包安装和 wheel 构建的 egg-info 写入 `build/`，中间文件写入 `build/setuptools/`。setup.py 只配置这两个位置并自动创建目录；继续使用 pip/标准构建后端，不直接运行 setup.py 命令。

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -B scripts/build_release.py
```

需要保留 NVIDIA 相关二进制时使用 `--nvidia`。默认产物：

- `dist/BD2_AutoFishing/`：完整便携目录。
- `dist/BD2_AutoFishing-windows.zip`：分发 ZIP。
- `build/pyinstaller/`、`build/specs/`：中间文件与 spec。

默认构建无控制台 Tk 图形版。脚本检查 init.tcl、tk.tcl 和 _tkinter.pyd，缺少任何一个即失败，不交付缺少界面的 ZIP。部分受限沙箱无法访问本机 Tcl 资源，应在正常 Windows 会话构建并验证。

构建后清理 OpenCV 的 FFmpeg 视频 DLL，因为项目没有使用 cv2.VideoCapture/VideoWriter；以后加入视频功能前须重新评估此步骤。

## 验证候选包

离线回归和 Tk 模拟检查分别运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -B scripts/checks/smoke_ui.py
```

包装核对包含全部 Python 模块、默认 INI、识别模板、3 个 OCR 模型、Tcl/Tk 和 ZIP 完整性。需要手动预览候选 EXE 时可运行：

```powershell
.\dist\BD2_AutoFishing\BD2_AutoFishing.exe --preview
```

预览不连接游戏、不保存设置。真实游戏验收另按任务范围安排，并先关闭其他钓鱼进程。离线回归、Tk 检查、构建成功和 EXE 实机验收是不同结论。

## GitHub 构建

`.github/workflows/build.yml` 在 Release 发布或手动触发时运行，使用 Windows + Python 3.12.4，安装 requirements 中的锁定环境和本项目，运行离线回归与 scripts/build_release.py，上传 `dist/BD2_AutoFishing-windows.zip`。发布 Release 时附加该 ZIP。

本地构建不自动提交、推送或发布。若使用自定义模型，文件也必须存在于远程检出内容中。

## 本机部署

本机工作区的用户版本位于外层 `deployment/`。仅明确要求部署时执行；普通构建只生成源码 `dist/`。

1. 确认目标程序退出，将旧 EXE、_internal 和配置备份到本机 archive 中带时间戳的目录。
2. 用候选便携目录的 EXE 与 _internal 成套替换；保留用户配置及日志，仅迁移必要配置项。
3. 核对部署文件与构建产物哈希，再按授权范围验收。

本次目录整理只将旧部署迁入 deployment，未升级它。递归移动或删除前核对解析后的绝对路径，使用 PowerShell 原生文件命令。
