"""独立 onefile 更新助手入口；不导入游戏、OCR 或主程序运行库。"""

import argparse
import ctypes
import json
import subprocess
import sys
from pathlib import Path

from bd2_fishing.infrastructure.updates.package import EXE
from bd2_fishing.infrastructure.updates.transaction import (
    apply_update,
    installation_lock,
    pending_job,
    rollback,
    write_json,
)


def run(root, *, recover=False):
    with installation_lock(root, timeout=60):
        job = pending_job(root)
        if job is None:
            raise RuntimeError("没有待处理的更新包")
        if recover:
            if (job / "journal.json").exists():
                phase = json.loads((job / "journal.json").read_text(encoding="utf8"))["phase"]
                rollback(root, job)
                message = (
                    "上次更新已完成，程序文件已保留。"
                    if phase == "complete"
                    else "已恢复中断的更新，请检查程序版本。"
                )
            else:
                message = "已取消尚未开始替换的更新，原程序保持不变。"
        else:
            apply_update(root, job)
            message = "版本更新完成，原有设置与运行数据已保留。"
        write_json(root / "cache/updates/result.json", dict(ok=True, message=message))
        (root / "cache/updates/pending.json").unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    root = (args.root or Path(sys.executable).parent).resolve()
    try:
        run(root, recover=args.recover or args.root is None)
        subprocess.Popen([str(root / EXE)], cwd=root)
    except Exception as exc:
        message = f"更新未完成：{exc}\n原配置与截图保留。可再次运行 BD2_Updater.exe 尝试恢复。"
        try:
            write_json(root / "cache/updates/result.json", dict(ok=False, message=message))
        except OSError:
            message += "\n无法写入更新结果，请检查磁盘空间和目录权限。"
        finally:
            ctypes.windll.user32.MessageBoxW(None, message, "BD2 更新", 0x10)


if __name__ == "__main__":
    main()
