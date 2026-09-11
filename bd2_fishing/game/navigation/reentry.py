"""150402 错误的专用退出重进；普通导航不自动确认返回码头。"""

import re
import time

from bd2_fishing.game.fishing.scene import FishingSceneReader
from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.game.navigation.voyage import NavigationFailed, prepare_voyage
from bd2_fishing.game.navigation.voyage_reading import VoyageReader
from bd2_fishing.infrastructure.windows import input as game_input
from bd2_fishing.infrastructure.windows.gdi import FeedbackCapture
from bd2_fishing.infrastructure.windows.window import WindowGuard
from bd2_fishing.runtime import control
from bd2_fishing.runtime.context import get_logger
from bd2_fishing.runtime.geometry import Rect

log = get_logger(__name__)


class StaminaReentry:
    def __init__(self, config, region, engine, origin, frames, metadata):
        try:
            self.origin = FishingLocation(origin)
        except (ValueError, TypeError) as exc:
            raise NavigationFailed("150402 恢复缺少原钓场，未退出游戏页面。") from exc
        if engine is None:
            raise NavigationFailed("150402 恢复需要 OCR，未执行退出。")
        self.config, self.region, self.engine = config, region, engine
        self.frames = frames
        self.button_bounds = None
        self.details = dict(status="checking", origin=str(self.origin), actions=[], samples=[])
        metadata["stamina_reentry"] = self.details
        self.fishing = FishingSceneReader(config, region)
        self.voyage = VoyageReader(engine)
        self.guard = WindowGuard("BrownDust II", region, require_foreground=True)

    def wait(self, camera, stage):
        """每阶段两帧确认、20 秒/81 次上限；所有 OCR 和输入均在 QTE 结束后。"""
        deadline = time.monotonic() + 20
        previous = None
        for _ in range(81):
            control.checkpoint()
            self.guard()
            frame = camera.grab()
            reading = self.read_stage(frame, stage) if frame is not None else None
            self.guard()
            stamp = time.monotonic()
            self.details["samples"].append(dict(stage=stage, matched=reading is not None, t=stamp))
            self.details["samples"] = self.details["samples"][-100:]
            if frame is not None:
                self.frames["reentry_latest.png"] = frame
            if reading is not None and previous == reading:
                self.frames[f"reentry_{stage}.png"] = frame
                return reading
            previous = reading
            if stamp >= deadline:
                break
            control.sleep(min(0.25, max(0, deadline - stamp)))
        raise NavigationFailed(f"150402 恢复未确认 {stage} 页面，未重复输入。")

    def read_stage(self, frame, stage):
        self.button_bounds = None
        scene = self.fishing.inspect(frame)
        if stage == "error":
            return self.read_error(frame, scene)
        if scene.panel_kind == "stamina_error":
            return None
        reading = self.voyage.inspect(frame)
        if stage == "closed":
            # 控件可能因游戏 Bug 消失，但必须读到钓场标题与更改入口。
            if (
                reading.page == "island"
                and reading.island in (None, str(self.origin))
                and scene.state not in {"qte", "panel", "blocked_dialog"}
            ):
                return ("island",)
        elif stage == "return":
            if (
                scene.panel_kind == "return_to_dock"
                and reading.page == "return_confirmation"
                and reading.action == "confirm_return"
                and reading.action_point is not None
            ):
                self.button_bounds = reading.action_bounds
                return reading.action_point
        elif stage == "dock" and reading.page == "dock":
            return ("dock",)
        return None

    def read_error(self, frame, scene):
        """模板只筛选外观，动作前必须读准完整错误码，避免相似数字误确认。"""
        if scene.panel_kind != "stamina_error":
            return None
        reading = self.voyage.inspect(frame)
        exact_code = any(
            item.score >= 0.85
            and re.search(r"error[:：]150402(?!\d)", re.sub(r"\s+", "", item.text), re.I)
            for item in reading.texts
        )
        if exact_code:
            # 模板和错误码共同确认的按钮文字内部；不外扩到整张弹窗。
            self.button_bounds = (458, 282, 489, 301)
            return (472, 292)
        return None

    def click(self, point, action):
        self.guard()
        if self.button_bounds is not None:
            left, top, right, bottom = self.button_bounds
            if not (0 <= left <= point[0] < right <= 945 and 0 <= top <= point[1] < bottom <= 532):
                raise NavigationFailed("恢复按钮范围无效，未执行点击。")
            bounds = Rect(*self.screen((left, top)), *self.screen((right, bottom)))
            actual = game_input.click_in_rect(bounds)
        else:
            actual = self.screen(point)
            game_input.click(*actual)
        self.details["actions"].append(dict(action=action, t=time.monotonic(), click_point=actual))

    def screen(self, point):
        x, y = point
        return (
            self.region.left + round(x * self.region.width / 945),
            self.region.top + round(y * self.region.height / 532),
        )

    def run(self):
        with control.use_input_guard(self.guard), FeedbackCapture(self.region) as camera:
            self.click(self.wait(camera, "error"), "close_150402")
            self.wait(camera, "closed")
            self.guard()
            game_input.press("esc")
            self.details["actions"].append(dict(action="escape", t=time.monotonic()))
            self.click(self.wait(camera, "return"), "return_to_dock")
            self.wait(camera, "dock")
        log.info("已返回码头，正在重新进入%s。", self.origin)
        arrived = prepare_voyage(self.config, self.region, self.engine, self.origin)
        if arrived != self.origin:
            raise NavigationFailed("150402 恢复未确认回到原钓场，未重新抛竿。")
        self.details["status"] = "arrived"


def reenter_after_stamina_error(observer):
    recovery = StaminaReentry(
        observer.config,
        observer.window,
        observer.engine,
        observer.current_location,
        observer.evidence_frames,
        observer.evidence_metadata,
    )
    log.warning("游戏出现 150402 错误，正在关闭提示、退出钓场并重新进入；本轮 QTE 证据保留。")
    try:
        recovery.run()
        observer.wait_until_idle()
        recovery.details["status"] = "resumed"
    except BaseException as exc:
        recovery.details.update(
            status="interrupted" if isinstance(exc, control.RunStopped) else "failed",
            error=str(exc),
        )
        raise
