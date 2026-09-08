"""不同钓点的 QTE 图像识别与按键决策策略。"""

from __future__ import annotations

import configparser
import time

import cv2
import numpy as np

from bd2_fishing.game.fishing.tracing import trace_qte
from bd2_fishing.infrastructure import settings as settings
from bd2_fishing.infrastructure.windows import capture as capture_backend
from bd2_fishing.infrastructure.windows import input as pydirectinput
from bd2_fishing.perception import image as vision
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime import geometry as geometry
from bd2_fishing.runtime.context import get_logger
from bd2_fishing.runtime.geometry import Rect

log = get_logger(__name__)


DEFAULT_LOOP_SLEEP_SECONDS = 0.01


class BaseQTEStrategy:
    """提供 QTE 截图分区、颜色遮罩、光标定位和结束检测等公共能力。"""

    def __init__(self, config: configparser.ConfigParser, region: Rect) -> None:
        self.region = region
        self.qte_detail_log = config.getboolean("diagnostics", "qte_detail_log", fallback=False)
        self._feedback_config = config
        self._feedback_session = None
        self._decision_frame = None
        self._decision_captured_at = None
        self.feedback_enabled = config.getboolean(
            "diagnostics", "qte_feedback_enabled", fallback=True
        )
        self.pixel_threshold_scale = vision.build_pixel_threshold_scale(config, region)
        self.longest_keep_time = settings.read_config_int(config, "time", "longest_keep_time")
        self.fish_end_wait_time = settings.read_config_float(config, "time", "fish_end_wait_time")
        self.loop_sleep_seconds = config.getfloat(
            "time",
            "loop_sleep_seconds",
            fallback=DEFAULT_LOOP_SLEEP_SECONDS,
        )
        self.press_tolerance_pixels = geometry.scale_pixel_length(
            config.getint("roi", "qte_press_tolerance_pixels", fallback=4),
            self.pixel_threshold_scale.width_factor,
        )
        self.time_bar_score_threshold = geometry.scale_pixel_threshold(
            50,
            self.pixel_threshold_scale,
        )
        self.ice_trouble_pixel_threshold = geometry.scale_pixel_threshold(
            5,
            self.pixel_threshold_scale,
        )
        self.abyss_yellow_pixel_threshold = geometry.scale_pixel_threshold(
            300,
            self.pixel_threshold_scale,
        )

        self.white_range = vision.read_hsv_range(config, "roi", "white")
        self.yellow_range = vision.read_hsv_range(config, "roi", "yellow")
        self.time_green_range = vision.read_hsv_range_from_keys(
            config,
            "roi",
            lower_prefix="time_lower_green",
            upper_prefix="time_upper_green",
        )
        self.time_red_range = vision.read_hsv_range_from_keys(
            config,
            "roi",
            lower_prefix="time_lower_red",
            upper_prefix="time_upper_red",
        )
        self.roi_pos = vision.build_region_from_config(config, "roi", region)
        self.time_pos_tuples = (
            config.getint("roi", "time_top_percent"),
            config.getint("roi", "time_bottom_percent"),
            config.getint("roi", "time_left_percent"),
            config.getint("roi", "time_right_percent"),
        )
        self.qte_pos_tuples = (
            config.getint("roi", "qte_top_percent"),
            config.getint("roi", "qte_bottom_percent"),
            config.getint("roi", "qte_left_percent"),
            config.getint("roi", "qte_right_percent"),
        )
        log.info(
            ">>> QTE 像素阈值: "
            f"time_bar_score={self.time_bar_score_threshold}, "
            f"ice_trouble={self.ice_trouble_pixel_threshold}, "
            f"abyss_yellow={self.abyss_yellow_pixel_threshold}, "
            f"press_tolerance={self.press_tolerance_pixels}px"
        )

    def play_qte(self, sct: capture_backend.DxCameraCapture) -> None:
        raise NotImplementedError("子类必须实现 play_qte() 方法")

    def _start_feedback(self):
        if not self.feedback_enabled:
            return
        try:
            from bd2_fishing.game.fishing.feedback import FeedbackSession

            self._feedback_session = FeedbackSession(
                self._feedback_config, self.region, getattr(self, "catch_observer", None)
            )
            self._feedback_session.start()
        except Exception:
            log.exception("QTE 结果观察初始化失败；继续使用现有钓鱼策略")
            self._stop_feedback()

    def _stop_feedback(self):
        session, self._feedback_session = self._feedback_session, None
        self._decision_frame = None
        self._decision_captured_at = None
        if session is not None:
            try:
                session.close()
            except Exception:
                log.exception("QTE 结果观察结束失败；不改变本轮控制结果")

    def _press_qte(self, reason=None, **details):
        if self._feedback_session is not None:
            try:
                if reason is None:
                    self._feedback_session.begin_press()
                else:
                    decision = dict(
                        strategy=type(self).__name__,
                        reason=reason,
                        stage="before_input_call",
                        captured_at_monotonic=self._decision_captured_at,
                        capture_backend="control DXcam (BGR)",
                        frame_region=self.roi_pos.as_tuple(),
                        qte_crop_percent=self.qte_pos_tuples,
                        coordinate_space="QTE crop local pixels",
                        press_tolerance_pixels=self.press_tolerance_pixels,
                        **details,
                    )
                    self._feedback_session.begin_press(decision, self._decision_frame)
            except Exception:
                log.exception("QTE 按键观察记录失败；仍执行原按键调用")
        # 不改变驱动、按键时长、按键条件或原来的暂停参数。
        return pydirectinput.press("space")

    def _sleep_loop(self) -> None:
        run_control.sleep(self.loop_sleep_seconds)

    def _grab_qte_frames(self, sct: capture_backend.DxCameraCapture) -> np.ndarray | None:
        """截取完整 QTE 区域并转换为 OpenCV HSV 图像。"""
        frame = sct.grab(self.roi_pos)
        # 只保留当前检测帧引用；真正有按键尝试时由观察器复制，不新增截图。
        if self._feedback_session is not None:
            self._decision_frame = frame
            self._decision_captured_at = time.monotonic() if frame is not None else None
        if frame is None:
            return None
        frame_hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        return frame_hsv

    def _grab_day_frame(self, sct: capture_backend.DxCameraCapture) -> np.ndarray | None:
        """预留的昼夜区域截图入口；当前策略尚未启用。"""
        return None

    def _split_roi_and_time(self, frame_hsv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """从完整截图切出倒计时条和实际 QTE 条，返回顺序与调用方一致。"""
        h, w = frame_hsv.shape[:2]
        time_hsv = frame_hsv[
            h * self.time_pos_tuples[0] // 100 : h * self.time_pos_tuples[1] // 100,
            w * self.time_pos_tuples[2] // 100 : w * self.time_pos_tuples[3] // 100,
        ]
        qte_hsv = frame_hsv[
            h * self.qte_pos_tuples[0] // 100 : h * self.qte_pos_tuples[1] // 100,
            w * self.qte_pos_tuples[2] // 100 : w * self.qte_pos_tuples[3] // 100,
        ]
        return time_hsv, qte_hsv

    def _time_bar_masks(self, time_hsv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """生成倒计时条的绿色和红色遮罩，不做膨胀以保留真实像素数量。"""
        mask_green = vision.create_color_mask(
            self.time_green_range.lower,
            self.time_green_range.upper,
            time_hsv,
            is_dilate=False,
        )
        mask_red = vision.create_color_mask(
            self.time_red_range.lower,
            self.time_red_range.upper,
            time_hsv,
            is_dilate=False,
        )
        return mask_green, mask_red

    def _time_bar_visible(self, time_hsv: np.ndarray) -> bool:
        mask_green, mask_red = self._time_bar_masks(time_hsv)
        return self._time_bar_visible_from_masks(mask_green, mask_red)

    def _time_bar_visible_from_masks(self, mask_green: np.ndarray, mask_red: np.ndarray) -> bool:
        score = cv2.countNonZero(mask_red) + cv2.countNonZero(mask_green)
        return score > self.time_bar_score_threshold

    def _cursor_mask(self, roi_hsv: np.ndarray) -> np.ndarray:
        return vision.create_color_mask(
            self.white_range.lower,
            self.white_range.upper,
            roi_hsv,
            is_dilate=False,
        )

    def _find_cursor_x(self, roi_hsv: np.ndarray) -> int | None:
        mask_cursor = self._cursor_mask(roi_hsv)
        return self._find_cursor_x_from_mask(mask_cursor)

    def _find_cursor_x_from_mask(self, mask_cursor: np.ndarray) -> int | None:
        """使用白色像素最多的一列作为光标横坐标。"""
        col_sums = np.sum(mask_cursor, axis=0)
        if np.max(col_sums) <= 0:
            return None
        return int(np.argmax(col_sums))

    def _mask_column_has_color(self, mask: np.ndarray, x: int) -> bool:
        """检查整列及其左右容差窗口内是否有颜色，容忍光标在采样间隔内跨越色条。"""
        left = max(0, x - self.press_tolerance_pixels)
        right = min(mask.shape[1], x + self.press_tolerance_pixels + 1)
        return cv2.countNonZero(mask[:, left:right]) > 0

    def _finish_fishing(self) -> None:
        started = time.monotonic()
        catch_observer = getattr(self, "catch_observer", None)
        if catch_observer is not None:
            try:
                catch_observer.finish()
            except Exception as exc:
                from bd2_fishing.game.fishing.settlement_rules import CatchResult

                catch_observer.result = CatchResult(
                    "unknown", f"结算观察失败：{type(exc).__name__}"
                )
                log.exception("结算观察失败；不把 QTE 退出当作捕获成功")
        run_control.sleep(max(0, self.fish_end_wait_time - (time.monotonic() - started)))
        window_center_x, window_center_y = self.region.center
        pydirectinput.moveTo(window_center_x, window_center_y)
        run_control.sleep(0.2)
        pydirectinput.click()

    def _yellow_mask(self, roi_hsv: np.ndarray) -> np.ndarray:
        # 膨胀核随窗口宽度缩放：光标宽度随分辨率变大，核跟着变大才能填掉光标压住黄条挖出的洞。
        kernel_size = geometry.scale_pixel_length(
            7,
            self.pixel_threshold_scale.width_factor,
            minimum=3,
        )
        if kernel_size % 2 == 0:
            kernel_size += 1
        return vision.create_color_mask(
            self.yellow_range.lower,
            self.yellow_range.upper,
            roi_hsv,
            is_dilate=True,
            dilate_kernel_size=(kernel_size, kernel_size),
            dilate_iterations=2,
        )

    def _on_bar_disappeared(self, no_bar_frames: int) -> bool:
        """连续多帧看不到倒计时条时确认本轮结束，避免单帧闪烁误判。"""
        if no_bar_frames > 80:
            self._qte_trace.reason = "time_bar_disappeared"
            log.debug("倒计时条已消失，等待结算观察")
            self._finish_fishing()
            return True
        return False


class FrostStraitQTEStrategy(BaseQTEStrategy):
    """默认钓鱼点：只看黄色条，并处理破冰。"""

    def __init__(self, config: configparser.ConfigParser, region: Rect) -> None:
        super().__init__(config, region)
        self.red_range = vision.read_hsv_range(config, "roi", "red")

    @trace_qte
    def play_qte(self, sct: capture_backend.DxCameraCapture) -> None:
        no_bar_frames = 0
        qte_started = False
        loading_logged = False
        start_time = time.monotonic()

        while time.monotonic() - start_time < self.longest_keep_time:
            run_control.checkpoint()
            frames = self._grab_qte_frames(sct)
            if frames is None:
                self._qte_trace.observe("no_frame")
                self._sleep_loop()
                continue

            time_hsv, qte_hsv = self._split_roi_and_time(frames)
            time_green_mask, time_red_mask = self._time_bar_masks(time_hsv)
            if not self._time_bar_visible_from_masks(time_green_mask, time_red_mask):
                if not qte_started:
                    self._qte_trace.observe("loading")
                    if not loading_logged:
                        log.info(">>> 倒计时条尚未出现，等待 QTE 界面加载")
                        loading_logged = True
                    self._sleep_loop()
                    continue
                self._qte_trace.observe("no_time_bar")
                no_bar_frames += 1
                if self._on_bar_disappeared(no_bar_frames):
                    break
                self._sleep_loop()
                continue

            qte_started = True
            no_bar_frames = 0

            if self.solve_ice_trouble(qte_hsv):
                self._qte_trace.observe("ice_break")
                log.debug("已发送破冰尝试按键；效果尚未核实")
                self._sleep_loop()
                continue

            mask_yellow = self._yellow_mask(qte_hsv)
            cursor_mask = self._cursor_mask(qte_hsv)
            cursor_x = self._find_cursor_x_from_mask(cursor_mask)

            pressed = False
            check_x = None
            if cursor_x is None:
                self._press_qte("no_cursor_fallback", cursor_x=None, target="unspecified")
                pressed = True
            else:
                check_x = cursor_x
            if check_x is not None and self._mask_column_has_color(mask_yellow, check_x):
                self._press_qte(
                    "yellow_overlap", cursor_x=cursor_x, check_x=check_x, target="yellow"
                )
                pressed = True
            self._qte_trace.observe("tracking", cursor=cursor_x, pressed=pressed)
            self._sleep_loop()

    def solve_ice_trouble(self, roi_hsv: np.ndarray) -> bool:
        mask = cv2.inRange(roi_hsv, self.red_range.lower, self.red_range.upper)
        if cv2.countNonZero(mask) > self.ice_trouble_pixel_threshold:
            self._press_qte(
                "ice_break_attempt",
                target="ice",
                red_pixels=cv2.countNonZero(mask),
                red_threshold=self.ice_trouble_pixel_threshold,
            )
            run_control.sleep(0.05)
            return True
        return False


class AbyssMawQTEStrategy(BaseQTEStrategy):
    """处理深渊巨口的黄蓝条规则，并用挡板限制当前有效判定范围。"""

    def __init__(self, config: configparser.ConfigParser, region: Rect) -> None:
        super().__init__(config, region)
        self.blue_range = vision.read_hsv_range(config, "roi", "blue")
        self.blocker_one_range = vision.read_hsv_range(config, "roi", "blocker_one")
        self.blocker_two_range = vision.read_hsv_range(config, "roi", "blocker_two")
        self.blocker_ranges = [self.blocker_one_range, self.blocker_two_range]

        # 配置值以参考分辨率为基准；宽、高分别按窗口两个方向的倍率缩放。
        self.blocker_shape_min_width = geometry.scale_pixel_length(
            config.getint("roi", "blocker_shape_min_width", fallback=4),
            self.pixel_threshold_scale.width_factor,
        )
        self.blocker_shape_max_width = max(
            self.blocker_shape_min_width + 1,
            geometry.scale_pixel_length(
                config.getint("roi", "blocker_shape_max_width", fallback=20),
                self.pixel_threshold_scale.width_factor,
            ),
        )
        self.blocker_shape_min_height = geometry.scale_pixel_length(
            config.getint("roi", "blocker_shape_min_height", fallback=18),
            self.pixel_threshold_scale.height_factor,
        )
        self.blocker_shape_max_height = max(
            self.blocker_shape_min_height + 1,
            geometry.scale_pixel_length(
                config.getint("roi", "blocker_shape_max_height", fallback=100),
                self.pixel_threshold_scale.height_factor,
            ),
        )

    @trace_qte
    def play_qte(self, sct: capture_backend.DxCameraCapture) -> None:
        """黄色存在时优先命中黄色，否则在蓝色区域按键刷新下一轮。"""
        no_bar_frames = 0
        qte_started = False
        loading_logged = False
        start_time = time.monotonic()

        while time.monotonic() - start_time < self.longest_keep_time:
            run_control.checkpoint()
            frames = self._grab_qte_frames(sct)
            if frames is None:
                self._qte_trace.observe("no_frame")
                self._sleep_loop()
                continue

            time_hsv, qte_hsv = self._split_roi_and_time(frames)

            time_green_mask, time_red_mask = self._time_bar_masks(time_hsv)
            if not self._time_bar_visible_from_masks(time_green_mask, time_red_mask):
                if not qte_started:
                    self._qte_trace.observe("loading")
                    if not loading_logged:
                        log.info(">>> 倒计时条尚未出现，等待 QTE 界面加载")
                        loading_logged = True
                    self._sleep_loop()
                    continue
                self._qte_trace.observe("no_time_bar")
                no_bar_frames += 1
                if self._on_bar_disappeared(no_bar_frames):
                    break
                self._sleep_loop()
                continue

            qte_started = True
            no_bar_frames = 0
            cursor_mask = self._cursor_mask(qte_hsv)
            cursor_x = self._find_cursor_x_from_mask(cursor_mask)
            if cursor_x is None:
                self._qte_trace.observe("no_cursor")
                self._sleep_loop()
                continue

            yellow_mask = self._yellow_mask(qte_hsv)
            blue_mask = self._blue_mask(qte_hsv)
            blocker_rect = self._blocker_rect(qte_hsv, cursor_mask)

            left_x, right_x = self._active_range_from_blocker_rect(
                blocker_rect,
                cursor_x,
                yellow_mask.shape[1],
            )
            check_x = self._clamp_x_to_range(
                cursor_x,
                left_x,
                right_x,
            )

            yellow_pixels = self._mask_range_count(yellow_mask, left_x, right_x)
            pressed = False
            if yellow_pixels > self.abyss_yellow_pixel_threshold:
                if self._mask_column_has_color(yellow_mask, check_x):
                    self._press_qte(
                        "yellow_overlap",
                        cursor_x=cursor_x,
                        check_x=check_x,
                        target="yellow",
                        active_range=(left_x, right_x),
                        blocker_rect=blocker_rect,
                        yellow_pixels=yellow_pixels,
                        yellow_threshold=self.abyss_yellow_pixel_threshold,
                    )
                    pressed = True
            elif self._mask_column_has_color(blue_mask, check_x):
                self._press_qte(
                    "blue_fallback",
                    cursor_x=cursor_x,
                    check_x=check_x,
                    target="blue",
                    active_range=(left_x, right_x),
                    blocker_rect=blocker_rect,
                    yellow_pixels=yellow_pixels,
                    yellow_threshold=self.abyss_yellow_pixel_threshold,
                )
                pressed = True
            self._qte_trace.observe(
                "tracking",
                blocker=blocker_rect,
                cursor=cursor_x,
                yellow=yellow_pixels,
                active=(left_x, right_x),
                pressed=pressed,
            )

            self._sleep_loop()

    def _blue_mask(self, qte_hsv: np.ndarray) -> np.ndarray:
        return vision.create_color_mask(self.blue_range.lower, self.blue_range.upper, qte_hsv)

    def _blocker_mask(self, qte_hsv: np.ndarray) -> np.ndarray:
        """合并挡板在不同画面亮度下的多个 HSV 颜色区间。"""
        blocker_mask = vision.create_color_mask(
            self.blocker_ranges[0].lower,
            self.blocker_ranges[0].upper,
            qte_hsv,
            is_dilate=False,
        )
        for blocker_range in self.blocker_ranges[1:]:
            range_mask = vision.create_color_mask(
                blocker_range.lower,
                blocker_range.upper,
                qte_hsv,
                is_dilate=False,
            )
            blocker_mask = cv2.bitwise_or(blocker_mask, range_mask)
        return blocker_mask

    def _blocker_rect(
        self,
        qte_hsv: np.ndarray,
        cursor_mask: np.ndarray,
    ) -> tuple[int, int, int, int] | None:
        """先排除高亮光标，再从修补后的挡板遮罩中寻找候选矩形。"""
        kernel = np.ones((3, 3), np.uint8)
        # 轻微扩张可覆盖光标抗锯齿边缘，避免残留白边被识别成挡板。
        cursor_mask_for_overlap = cv2.dilate(cursor_mask, kernel, iterations=1)

        without_cursor_mask = qte_hsv.copy()
        # HSV 的零值代表黑色，不会落入当前挡板的高亮颜色范围。
        without_cursor_mask[cursor_mask_for_overlap > 0] = [0, 0, 0]
        blocker_mask = self._filtered_blocker_mask(self._blocker_mask(without_cursor_mask))
        blocker_rect = self._find_blocker(blocker_mask)
        return blocker_rect

    def _filtered_blocker_mask(self, blocker_mask: np.ndarray) -> np.ndarray:
        """用闭运算填补挡板内部孔洞，同时尽量保持外轮廓尺寸。"""
        # 核高大于核宽，更适合修补瘦高挡板纵向上的断裂。
        kernel = np.ones((6, 4), np.uint8)
        filtered_mask = cv2.morphologyEx(blocker_mask, cv2.MORPH_CLOSE, kernel)
        return filtered_mask

    def _find_blocker(self, closed_mask: np.ndarray) -> tuple[int, int, int, int] | None:
        """按轮廓宽高和长宽比筛选挡板，并返回首个匹配边界框。"""
        contours, _ = cv2.findContours(closed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)

            # 挡板应为瘦高矩形：宽高范围读取配置，比例用于排除形状相近的干扰。
            aspect_ratio = float(h) / w

            if (
                self.blocker_shape_min_width < w < self.blocker_shape_max_width
                and self.blocker_shape_min_height < h < self.blocker_shape_max_height
                and 2.0 < aspect_ratio < 7.0
            ):
                return x, y, w, h

        return None

    def _active_range_from_blocker(
        self,
        blocker_mask: np.ndarray,
        cursor_x: int,
    ) -> tuple[int, int]:
        """按挡板像素列选择光标所在一侧的有效范围（兼容旧调试逻辑）。"""
        width = blocker_mask.shape[1]
        blocker_columns = [
            index for index, value in enumerate(np.sum(blocker_mask, axis=0)) if value > 0
        ]
        if not blocker_columns:
            return 0, width - 1

        left_columns = [column for column in blocker_columns if column < cursor_x]
        right_columns = [column for column in blocker_columns if column > cursor_x]
        left_boundary = left_columns[-1] if left_columns else None
        right_boundary = right_columns[0] if right_columns else None

        if left_boundary is None:
            if right_boundary is None:
                return 0, width - 1
            return 0, max(0, right_boundary - 1)
        if right_boundary is None:
            return min(width - 1, left_boundary + 1), width - 1

        if cursor_x - left_boundary <= right_boundary - cursor_x:
            return min(width - 1, left_boundary + 1), width - 1
        return 0, max(0, right_boundary - 1)

    def _active_range_from_blocker_rect(
        self,
        blocker_rect: tuple[int, int, int, int] | None,
        cursor_x: int,
        mask_width: int,
    ) -> tuple[int, int]:
        """将挡板矩形当作边界，只保留光标当前能够活动的一侧。"""
        if blocker_rect is None:
            return 0, mask_width - 1

        x, _y, w, _h = blocker_rect
        blocker_left = max(0, x)
        blocker_right = min(mask_width - 1, x + w - 1)

        # 挡板在光标右边：只看最左边到挡板左侧
        if cursor_x < blocker_left:
            return 0, max(0, blocker_left - 1)

        # 挡板在光标左边：只看挡板右侧到最右边
        if cursor_x > blocker_right:
            return min(mask_width - 1, blocker_right + 1), mask_width - 1

        # 光标刚好落在挡板矩形内，兜底：按离哪边近来切
        blocker_center = (blocker_left + blocker_right) // 2
        if cursor_x <= blocker_center:
            return 0, max(0, blocker_left - 1)
        return min(mask_width - 1, blocker_right + 1), mask_width - 1

    def _mask_range_count(
        self,
        mask: np.ndarray,
        left_x: int,
        right_x: int,
    ) -> int:
        """统计闭区间 ``left_x..right_x`` 内的非零遮罩像素。"""
        return cv2.countNonZero(mask[:, left_x : right_x + 1])

    def _clamp_x_to_range(self, x: int, left_x: int, right_x: int) -> int:
        return max(left_x, min(x, right_x))
