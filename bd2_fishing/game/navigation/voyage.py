"""码头、选岛、启航的有界导航；每次动作以新读数确认，不自动购买。"""

import threading
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from bd2_fishing.game.fishing.scene import FishingSceneReader
from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.game.navigation.voyage_reading import VoyageReader, VoyageReading
from bd2_fishing.infrastructure import paths
from bd2_fishing.infrastructure.diagnostics import bundle_writer
from bd2_fishing.infrastructure.windows import input as game_input
from bd2_fishing.infrastructure.windows.gdi import FeedbackCapture
from bd2_fishing.infrastructure.windows.window import WindowGuard
from bd2_fishing.runtime import control
from bd2_fishing.runtime.context import get_logger
from bd2_fishing.runtime.geometry import Rect

log = get_logger(__name__)


class NavigationFailed(RuntimeError):
    """无法确认下一步时保留现场，不继续点击。"""


class VoyageNavigator:
    def __init__(self, config, region, engine, target=None, *, change_from_island=False):
        self.config, self.region = config, region
        self.target = str(target) if target is not None else None
        self.reader = VoyageReader(engine)
        self.fishing = FishingSceneReader(config, region)
        self.guard = WindowGuard("BrownDust II", region, require_foreground=True)
        self.details = dict(status="checking", target=self.target, samples=[], actions=[])
        self.frames = {}
        self.visited = []
        self.pans = 0
        self.pending = None
        # 显式换点从第一帧开始取证，出发前拒识也要保留现场。
        self.active = change_from_island
        self.selected = None
        self.change_from_island = change_from_island

    def observe(self, camera):
        control.checkpoint()
        self.guard()
        frame = camera.grab()
        self.guard()
        if frame is None:
            return None, None
        self.frames["latest.png"] = frame
        scene = self.fishing.inspect(frame)
        state = scene.state
        if state == "blocked_dialog":
            if scene.panel_kind == "return_to_dock":
                reading = VoyageReading(page="return_confirmation")
            elif scene.panel_kind == "stamina_error":
                raise NavigationFailed("游戏出现 150402 错误；本次普通导航不处理错误退出重进。")
            else:
                reading = self.reader.inspect(frame)
                if reading.page != "travel_confirmation":
                    reading = VoyageReading(page="travel_confirmation")
            self.details["samples"].append(asdict(reading))
            self.details["samples"] = self.details["samples"][-80:]
            return frame, reading
        if state in ("waiting", "qte", "panel") or (
            state == "idle" and not self.change_from_island
        ):
            return frame, state
        if state == "idle" and self.pending and self.pending[0] in ("sail", "confirm_travel"):
            return frame, state
        reading = self.reader.inspect(frame)
        if reading.page == "island" and state != "idle":
            reading = replace(reading, action=None, action_point=None, action_bounds=None)
        self.guard()
        self.details["samples"].append(asdict(reading))
        self.details["samples"] = self.details["samples"][-80:]
        return frame, reading

    def run(self, camera):
        deadline = time.monotonic() + 75
        previous = None
        for _ in range(150):
            if time.monotonic() >= deadline:
                raise NavigationFailed("航海导航超时，已保存现场；请检查当前页面。")
            frame, reading = self.observe(camera)
            if reading is None:
                control.sleep(0.2)
                continue
            if isinstance(reading, str):
                return self._finish_navigation(reading)
            if not self.active and reading.page == "unknown":
                return None  # 原有未知页面、结算和启动接续仍由 prepare_start 处理。
            self.active = True
            self.frames.setdefault("first.png", frame)
            if reading.page == "return_confirmation":
                raise NavigationFailed(
                    "当前是返回码头确认框；返回会移除消耗品效果，请手动取消或处理。"
                )
            if self._waiting_for_transition(reading):
                control.sleep(0.25)
                continue
            signature = (reading.page, reading.island, reading.action)
            if signature != previous:
                previous = signature
                control.sleep(0.25)
                continue
            if reading.page in ("unknown", "loading"):
                control.set_status("等待航海页面加载")
                control.sleep(0.25)
                continue
            self.act(reading, frame)
            previous = None
            control.sleep(0.35)
        raise NavigationFailed("航海页面观察达到上限，已停止并保存现场。")

    def _finish_navigation(self, state):
        """已有钓鱼画面可直接交接；导航后的到达还必须对应启航动作。"""
        if not self.active:
            return None
        if self.pending and self.pending[0] in ("sail", "confirm_travel") and state != "panel":
            self.details.update(status="arrived", next_state=state, island=self.selected)
            log.info("已进入%s，交接钓鱼页面识别。", self.selected)
            return FishingLocation(self.selected)
        raise NavigationFailed("导航中出现钓鱼或弹窗画面，未确认启航结果，已保存现场。")

    def _waiting_for_transition(self, reading):
        if self.pending is None:
            return False
        action, before, started = self.pending
        if action == "sail" and reading.page == "travel_confirmation":
            return False
        changed = (action in ("start_fishing", "change_island") and reading.page == "map") or (
            action == "select_island"
            and reading.page == "map"
            and reading.island is not None
            and reading.island != before
        )
        if changed:
            self.pending = None
            return False
        if time.monotonic() - started > (40 if action in ("sail", "confirm_travel") else 10):
            raise NavigationFailed("导航操作后未确认页面变化，已停止；不会重复点击同一按钮。")
        return True

    def act(self, reading, frame):
        if len(self.details["actions"]) >= 16:
            raise NavigationFailed("选岛搜索已达到操作上限，请确认目标岛屿是否可见。")
        if reading.page == "dock" and reading.action == "start_fishing":
            self._click(reading.action_point, "start_fishing", reading, frame)
            log.info("已识别码头，打开钓鱼地区选择。")
        elif reading.page == "map":
            self._select_or_sail(reading, frame)
        elif reading.page == "island":
            if not self.change_from_island or reading.action != "change_island":
                raise NavigationFailed("未确认可换图的待机状态，不点击更改或船锚。")
            self._click(reading.action_point, "change_island", reading, frame)
            log.info("已确认更改按钮，打开选岛地图。")
        elif reading.page == "travel_confirmation":
            self._confirm_travel(reading, frame)

    def _confirm_travel(self, reading, frame):
        target = self.target or reading.island
        if (
            target not in {item.value for item in FishingLocation}
            or reading.island != target
            or reading.action != "confirm_travel"
        ):
            raise NavigationFailed("换岛确认中的目的地未确认或与目标不符，未点击确认。")
        if not self.config.getboolean("navigation", "confirm_island_change", fallback=True):
            raise NavigationFailed("已关闭自动确认换岛，请手动处理当前确认框。")
        self.target = self.selected = target
        self._click(reading.action_point, "confirm_travel", reading, frame)
        log.info("已确认前往%s，等待进入钓场。", target)

    def _select_or_sail(self, reading, frame):
        target = self.target or reading.island
        if target is None:
            raise NavigationFailed("未读到选中岛屿，请在设置中选择目标钓场。")
        if target not in {item.value for item in FishingLocation}:
            raise NavigationFailed(f"已识别{target}，但尚无对应钓鱼策略，未启航。")
        self.target = target
        if reading.island == target:
            if reading.license_state == "required":
                raise NavigationFailed(f"{target}需要购买进入许可证，请手动处理；程序未购买。")
            if reading.action != "sail" or reading.license_state != "available":
                raise NavigationFailed("未确认启航按钮，已停止，不点击购买或未知按钮。")
            self.selected = target
            self._click(reading.action_point, "sail", reading, frame)
            log.info("已确认%s与启航按钮，正在进入钓场。", target)
            return
        for marker in reading.markers:
            if marker.selected or any(
                abs(marker.x - x) < 22 and abs(marker.y - y) < 22 for x, y in self.visited
            ):
                continue
            self.visited.append((marker.x, marker.y))
            self._click((marker.x, marker.y), "select_island", reading, frame)
            return
        if self.pans >= 2:
            raise NavigationFailed(f"拖动地图后仍未找到{target}，已保存现场。")
        self._remember("pan_map", frame)
        # 两次反向拖动覆盖两侧，每次之后重新识别，旧圆标坐标全部失效。
        start, end = ((180, 190), (510, 190)) if self.pans == 0 else ((570, 190), (110, 190))
        self.guard()
        game_input.drag_between(self._screen(start), self._screen(end), duration=0.6)
        self.pans += 1
        self.visited.clear()
        control.sleep(0.5)

    def _screen(self, point):
        x, y = point
        return self.region.left + round(x * self.region.width / 945), self.region.top + round(
            y * self.region.height / 532
        )

    def _remember(self, action, frame):
        index = len(self.details["actions"])
        self.details["actions"].append(dict(action=action, t=time.monotonic()))
        # 最大 16 次操作；只保留最初六步及最新现场，后台编码不进入 QTE。
        if index < 6:
            self.frames[f"before_{index:02d}_{action}.png"] = frame

    def _click(self, point, action, reading, frame):
        if point is None:
            raise NavigationFailed("缺少已确认按钮位置，未执行点击。")
        self._remember(action, frame)
        self.guard()
        bounds = reading.action_bounds if action == reading.action else None
        if bounds is not None:
            left, top, right, bottom = bounds
            if not (0 <= left <= point[0] < right <= 945 and 0 <= top <= point[1] < bottom <= 532):
                raise NavigationFailed("按钮范围无效或与定位不符，未执行点击。")
            screen_bounds = Rect(*self._screen((left, top)), *self._screen((right, bottom)))
            actual = game_input.click_in_rect(screen_bounds)
        else:
            actual = self._screen(point)
            game_input.click(*actual)
        self.details["actions"][-1].update(click_point=actual, reference_bounds=bounds)
        self.pending = (action, reading.island, time.monotonic())

    def save(self):
        if not self.active:
            return
        done = threading.Event()
        metadata = dict(
            navigation=self.details,
            evidence_id=uuid.uuid4().hex,
            event="voyage_navigation",
            saved_at_unix=time.time(),
            window_region=self.region.as_tuple(),
        )
        accepted = bundle_writer.submit(
            Path(paths.get_diagnostics_path()) / "navigation",
            self.config.getint("diagnostics", "failure_max_events", fallback=100),
            metadata,
            dict(self.frames),
            done,
        )
        if not accepted or not done.wait(timeout=5):
            log.warning("导航证据队列已满或尚未写完，请保留诊断日志。")


def prepare_voyage(config, region, engine, target=None, *, change_from_island=False):
    navigator = VoyageNavigator(
        config, region, engine, target, change_from_island=change_from_island
    )
    try:
        with control.use_input_guard(navigator.guard), FeedbackCapture(region) as camera:
            return navigator.run(camera)
    except BaseException as exc:
        navigator.details.update(
            status="interrupted" if isinstance(exc, control.RunStopped) else "failed",
            error=str(exc),
        )
        raise
    finally:
        navigator.save()
