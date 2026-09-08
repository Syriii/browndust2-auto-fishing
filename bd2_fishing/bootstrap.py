"""bootstrap：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging

from bd2_fishing.app.session import run_once
from bd2_fishing.infrastructure.diagnostics import logging as logging_setup

log = logging.getLogger(__name__)


def main() -> None:
    import sys

    from bd2_fishing.infrastructure.windows.window import enable_dpi_awareness

    enable_dpi_awareness()
    logging_setup.setup_logging()
    logging_setup.install_exception_hook()
    log.info(">>> 程序启动")
    from bd2_fishing.ui.window import launch

    launch(run_once, preview="--preview" in sys.argv)
