"""bootstrap：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging

from bd2_fishing.infrastructure.diagnostics import logging as logging_setup

log = logging.getLogger(__name__)


def main() -> None:
    import sys
    from contextlib import nullcontext
    from pathlib import Path

    from bd2_fishing.infrastructure.paths import get_base_path
    from bd2_fishing.infrastructure.updates.transaction import installation_lock

    root = Path(get_base_path())
    frozen = getattr(sys, "frozen", False)
    preview = "--preview" in sys.argv
    try:
        with installation_lock(root) if frozen else nullcontext():
            if frozen and not preview and _recover_pending(root):
                return
            _desktop(preview)
    except Exception as exc:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, str(exc), "BD2 无法启动", 0x10)


def _recover_pending(root):
    import subprocess

    from bd2_fishing.infrastructure.updates.package import HELPER
    from bd2_fishing.infrastructure.updates.transaction import pending_job

    job = pending_job(root)
    if job is None:
        return False
    helper = job / HELPER
    if not helper.is_file():
        helper = root / HELPER
    subprocess.Popen(
        [str(helper), "--root", str(root), "--recover"],
        cwd=root,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return True


def _desktop(preview):
    from bd2_fishing.app.desktop import DesktopServices
    from bd2_fishing.app.session import run_once
    from bd2_fishing.app.startup import initialize_desktop
    from bd2_fishing.infrastructure.windows.window import enable_dpi_awareness

    enable_dpi_awareness()
    services = DesktopServices(read_only=preview)
    result = initialize_desktop(services) if not preview else {"messages": []}
    logging_setup.setup_logging()
    logging_setup.install_exception_hook()
    log.info("程序启动")
    from bd2_fishing.ui.window import launch

    services.startup_messages = result["messages"]
    try:
        launch(run_once, preview=preview, services=services)
    finally:
        logging.shutdown()
