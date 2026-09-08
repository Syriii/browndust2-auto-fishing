# 依赖管理

[开发指南](../docs/development/guide.md)

pyproject.toml 是运行、构建和开发依赖的声明来源。windows-py312.lock.txt 从本机已验证的 Windows / CPython 3.12 环境生成，固定直接、间接依赖和构建工具，共 35 项。本轮新增固定版本 Ruff 作为开发工具，原运行依赖没有升级。

重建相同环境，在仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/windows-py312.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

调整依赖时先修改 pyproject，在目标 Windows Python 3.12 环境安装、验证，再执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/lock_environment.py
```

脚本追踪已安装依赖闭包、检查声明版本约束，并重写锁定清单；它不会安装或升级包。锁定文件只覆盖该平台和 Python 版本，不能视为跨平台锁。GitHub Actions 使用同一文件。
