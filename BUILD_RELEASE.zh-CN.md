# 构建与发布

## 1. 准备 OCR 模型文件

默认情况下，项目使用 `rapidocr` Python 包内置打包的模型。

如果你想使用内置模型，请在 `config.ini` 中保持以下键为空：

- `det_model_path`
- `cls_model_path`
- `rec_model_path`
- `rec_keys_path`

如果你之后想切换为自己准备的、兼容 RapidOCR 的 ONNX 模型，请在 `[ocr]` 段中填写这些路径。

注意：自定义模型文件必须放在项目目录内（不能使用项目外的绝对路径），否则构建脚本会报错中止，以保证发布包在其他机器上也能正常使用。

## 2. 安装构建环境

安装构建环境：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

## 3. 本地构建

```powershell
python build_release.py
```

如果你需要打包包含 NVIDIA 相关二进制的 GPU 版本：

```powershell
python build_release.py --nvidia
```

本地产物如下：

- `dist/BD2_AutoFishing/`
- `dist/BD2_AutoFishing-windows.zip`

默认构建无控制台的 Tk 图形版，并包含 Tcl/Tk 运行库。构建前应确认当前 Python 能创建 Tk 窗口；部分受限沙箱不能访问原生 Tcl 资源，需在正常 Windows 会话构建。源码与发布版均使用页面按钮启停。

PyInstaller 完成后，构建脚本会自动删除 OpenCV 的 FFmpeg 视频 DLL，因为本项目没有使用
`cv2.VideoCapture` 或 `cv2.VideoWriter`。如果以后增加视频输入或输出功能，需要先移除该清理步骤。

## 4. 本地测试

运行：

```powershell
.\dist\BD2_AutoFishing\BD2_AutoFishing.exe
```

请确认：

- OCR 日志输出正常
- 打包后的程序能够正确找到 `config.ini`
- 打包后的程序能够正常初始化 RapidOCR 内置模型
- 页面默认待机，开始/停止按钮控制单个任务；新版本的真实启停测试必须先关闭旧版本
- `--preview` 参数只启动模拟界面，不连接游戏、不保存设置，可用于候选包检查
- `python tools/smoke_ui.py` 使用实际 Tk 控件和模拟任务，检查按钮、日志筛选及布局；不会发送游戏输入

## 5. 发布到 GitHub

推送提交后，创建并发布一个 GitHub Release（工作流在 Release 发布时自动触发）。也可以不发布 Release，直接在 GitHub 的 Actions 页面手动触发该工作流。

注意：

- GitHub Actions 会自动打包 `rapidocr` 的内置模型数据
- 如果你之后切换回自己本地的模型文件，这些文件也必须存在于仓库检出内容中

工作流（`.github/workflows/build.yml`）在 Windows + Python 3.12.4 环境下自动执行以下步骤：

- 安装 `requirements.txt` 中的依赖和 PyInstaller
- 运行 `python build_release.py`
- 上传 `dist/BD2_AutoFishing-windows.zip` 作为构建产物
- 发布 Release 时将该 zip 附加到 Release
