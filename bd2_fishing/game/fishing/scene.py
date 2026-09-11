"""钓鱼页面统一只读识别；启动与恢复共用，不在实时 QTE 循环执行。"""

from dataclasses import dataclass, field

from bd2_fishing.game.fishing.dialogs import FishingDialogReader
from bd2_fishing.game.fishing.page import FishingPageReader
from bd2_fishing.game.fishing.panels import SettlementPanelReader
from bd2_fishing.game.fishing.scene_signals import SceneSignals
from bd2_fishing.runtime.geometry import Rect


@dataclass(frozen=True)
class SceneReading:
    state: str
    panel_kind: str | None = None
    panel_scores: dict = field(default_factory=dict)
    idle_scores: dict = field(default_factory=dict)
    waiting_scores: dict = field(default_factory=dict)
    qte_signals: dict = field(default_factory=dict)


class FishingSceneReader:
    def __init__(self, config, window):
        self.window = window
        self.dialogs = FishingDialogReader()
        self.idle = FishingPageReader(window, config)
        self.panels = SettlementPanelReader(window)
        local = Rect(0, 0, window.width, window.height)
        self.signals = SceneSignals(config, local, local)

    def inspect(self, frame):
        if frame is None or frame.shape[:2] != (self.window.height, self.window.width):
            return SceneReading("unavailable")
        blocked, dialog_scores = self.dialogs.inspect(frame)
        if blocked:
            return SceneReading("blocked_dialog", panel_kind=blocked, panel_scores=dialog_scores)
        panel = self.panels.is_open(frame)
        if panel:
            kind, scores = self.panels.inspect(frame, close_visible=True)
            return SceneReading("panel", panel_kind=kind, panel_scores=scores)
        idle, scores = self.idle.inspect(frame)
        if idle:
            return SceneReading("idle", idle_scores=scores)
        waiting, waiting_scores = self.idle.inspect_waiting(frame, scores)
        if waiting:
            return SceneReading("waiting", idle_scores=scores, waiting_scores=waiting_scores)
        _, signals = self.signals.inspect(frame)
        # 启动接管要求计时条、目标区和实际亮光标同时存在。
        # 未见光标或目标时仍可由已运行的 QTE 处理，但不能凭颜色首次接管。
        pixels = signals.get("pixels", {})
        active = (
            signals.get("qte_active", False)
            and signals.get("bright_cursor_x") is not None
            and bool(pixels.get("blue", 0) or pixels.get("yellow", 0))
        )
        return SceneReading(
            "qte" if active else "unrecognized", idle_scores=scores, qte_signals=signals
        )
