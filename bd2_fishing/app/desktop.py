"""桌面页面使用的设置、地点选项与任务服务。"""

from pathlib import Path

from bd2_fishing.app.service import TaskController
from bd2_fishing.game.islands.catalog import FishingLocation as FishingLocation
from bd2_fishing.infrastructure import paths, settings


class DesktopServices:
    """隔离页面与配置文件、输入释放实现；构造时不操作游戏。"""

    def __init__(self, *, config_path=None, release_inputs=None):
        self.config_path = Path(config_path or Path(paths.get_base_path()) / "config.ini")
        self._release_inputs = release_inputs

    def load_settings(self):
        return settings.read_ini(str(self.config_path))

    def save_settings(self, updates):
        return settings.update_config_options(self.config_path, updates)

    def create_task(self, target, *, preview=False):
        if preview:

            def release():
                return None
        elif self._release_inputs is not None:
            release = self._release_inputs
        else:
            from bd2_fishing.infrastructure.windows.input import release_inputs

            release = release_inputs
        return TaskController(target, release)
