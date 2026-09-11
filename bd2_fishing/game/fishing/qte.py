"""不同钓点的 QTE 图像识别与按键决策策略。"""

from __future__ import annotations

import configparser
import time
from dataclasses import asdict

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.blockers import BlockerDetector, active_range_for_blocker
from bd2_fishing.game.fishing.mechanics.blue_target import read_blue_target
from bd2_fishing.game.fishing.mechanics.policy import MechanismPolicy
from bd2_fishing.game.fishing.mechanics.regions import read_mechanism_regions
from bd2_fishing.game.fishing.pointer import read_pointer
from bd2_fishing.game.fishing.recovery import (
    RoundObservationError,
    check_unconfirmed_limit,
    close_confirmed_panel,
)
from bd2_fishing.game.fishing.tracing import QTEControlTimeout, trace_qte
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
        self._pointer_reading = None
        self._mechanism_policy = MechanismPolicy()
        self._green_release_pending = False
        self._green_input_started_at = None
        self._mechanism_regions = None
        # 维护取证是正常运行能力；旧配置开关不再关闭失败及结算观察。
        self.feedback_enabled = True
        self.pixel_threshold_scale = vision.build_pixel_threshold_scale(config, region)
        self.longest_keep_time = settings.read_config_int(config, "time", "longest_keep_time")
        self.fish_end_wait_time = settings.read_config_float(config, "time", "fish_end_wait_time")
        self.loop_sleep_seconds = settings.bounded_float(
            config, "time", "loop_sleep_seconds", DEFAULT_LOOP_SLEEP_SECONDS, 0.001, 0.1
        )
        self.qte_hold_seconds = settings.bounded_float(
            config, "time", "qte_hold_seconds", 0.1, 0.005, 0.5
        )
        self.qte_settle_seconds = settings.bounded_float(
            config, "time", "qte_settle_seconds", 0.2, 0, 1
        )
        self.press_tolerance_pixels = geometry.scale_pixel_length(
            config.getint("roi", "qte_press_tolerance_pixels", fallback=4),
            self.pixel_threshold_scale.width_factor,
        )
        self.time_bar_score_threshold = geometry.scale_pixel_threshold(
            50,
            self.pixel_threshold_scale,
        )
        self.red_obstruction_pixel_threshold = geometry.scale_pixel_threshold(
            5,
            self.pixel_threshold_scale,
        )
        self.yellow_source_min_pixels = max(
            5, geometry.scale_pixel_threshold(8, self.pixel_threshold_scale)
        )
        self._yellow_source_pixels = 0
        self._yellow_source_mask = None
        self._yellow_aim_decision = None
        self.abyss_yellow_pixel_threshold = geometry.scale_pixel_threshold(
            300,
            self.pixel_threshold_scale,
        )

        self.white_range = vision.read_hsv_range(config, "roi", "white")
        self.yellow_range = vision.read_hsv_range(config, "roi", "yellow")
        self.blue_range = vision.read_hsv_range(config, "roi", "blue")
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
        log.debug(
            ">>> QTE 像素阈值: "
            f"time_bar_score={self.time_bar_score_threshold}, "
            f"red_obstruction={self.red_obstruction_pixel_threshold}, "
            f"abyss_yellow={self.abyss_yellow_pixel_threshold}, "
            f"press_tolerance={self.press_tolerance_pixels}px"
        )

    @trace_qte
    def play_qte(self, sct: capture_backend.DxCameraCapture) -> None:
        self._mechanism_policy = MechanismPolicy()
        no_bar_frames = 0
        observer = getattr(self, "catch_observer", None)
        qte_started = observer is not None and observer.evidence_metadata.get("resumed_qte") is True
        loading_logged = False
        start_time = time.monotonic()

        while time.monotonic() - start_time < self.longest_keep_time:
            run_control.checkpoint()
            frames = self._grab_qte_frames(sct)
            if frames is None:
                self._release_green_on_missing_frame()
                self._mechanism_policy.targets.invalidate()
                self._qte_trace.observe("no_frame")
                self._sleep_loop()
                continue

            time_hsv, qte_hsv = self._split_roi_and_time(frames)
            time_green_mask, time_red_mask = self._time_bar_masks(time_hsv)
            if not self._time_bar_visible_from_masks(time_green_mask, time_red_mask):
                self._release_green_on_missing_frame()
                self._mechanism_policy.targets.invalidate()
                if not qte_started:
                    self._qte_trace.observe("loading")
                    if not loading_logged:
                        log.debug("倒计时条尚未出现，等待 QTE 界面加载")
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

            cursor_x = self._find_cursor_x(qte_hsv)
            handled, regions = self._mechanism_step(qte_hsv, cursor_x)
            if handled:
                self._mechanism_policy.targets.invalidate()
                self._sleep_loop()
                continue
            if cursor_x is None:
                self._mechanism_policy.targets.invalidate()
                self._qte_trace.observe("no_cursor")
                self._sleep_loop()
                continue
            self._track_targets(qte_hsv, cursor_x, regions)
            self._sleep_loop()
        else:
            self._on_control_timeout(sct)

    def _track_targets(self, qte_hsv, cursor_x, regions):
        raise NotImplementedError("子类必须提供地点目标识别")

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
        # 先释放绿色长按，再等待观察线程封存；异常、取消和超时均经过此处。
        try:
            if self._mechanism_policy.green.held or self._green_release_pending:
                self._mechanism_policy.green.release("green_interrupted")
                self._release_green_key()
        finally:
            self._close_feedback()

    def _close_feedback(self):
        session, self._feedback_session = self._feedback_session, None
        self._decision_frame = None
        self._decision_captured_at = None
        if session is not None:
            try:
                session.close()
            except Exception:
                log.exception("QTE 结果观察结束失败；不改变本轮控制结果")

    def _mechanism_step(self, qte_hsv, cursor):
        """识别同一控制帧，由纯策略仲裁，再同步执行唯一动作。"""
        regions = read_mechanism_regions(qte_hsv, margin=max(3, self.press_tolerance_pixels + 2))
        self._mechanism_regions = regions
        decision = self._mechanism_policy.observe(regions, cursor, time.monotonic())
        if decision.action == "normal":
            self._cache_first_mechanisms(regions)
            return False, regions
        if decision.action == "press":
            self._cache_first_mechanisms(regions)
            self._press_qte(
                decision.reason,
                cursor_x=cursor,
                check_x=cursor,
                target="bubble",
                bubble_span=decision.bubble_span,
            )
            self._cache_mechanism_frame("bubble_press.png")
            self._qte_trace.observe("bubble_press", cursor=cursor, pressed=True)
            log.info("已尝试单次命中泡泡球，等待游戏反馈。")
            return True, regions
        if decision.action == "down":
            # 原生调用报错也可能已经部分执行，退出路径仍必须尝试释放。
            self._green_release_pending = True
            pydirectinput.qte_key_down()
            self._green_input_started_at = time.monotonic()
            self._cache_mechanism_frame("green_start.png")
        elif decision.action == "up":
            # 先释放，取证线程或异常不能延迟 keyUp。
            self._release_green_key()
            released_at = time.monotonic()
            self._cache_mechanism_frame("green_release.png")
            if self._feedback_session is not None:
                try:
                    self._feedback_session.begin_press(
                        dict(
                            strategy=type(self).__name__,
                            frame_region=self.roi_pos.as_tuple(),
                            qte_crop_percent=self.qte_pos_tuples,
                            capture_backend="control DXcam (BGR)",
                            stage="after_release_call",
                            reason=decision.reason,
                            action_kind="green_hold",
                            hold_decided_at_monotonic=decision.started_at,
                            hold_started_at_monotonic=self._green_input_started_at,
                            release_recorded_at_monotonic=released_at,
                            input_timestamp_stage="native_call_returned",
                            result_window_anchor="release",
                            captured_at_monotonic=self._decision_captured_at,
                        ),
                        self._decision_frame,
                        pressed_at=released_at,
                    )
                except Exception:
                    log.exception("绿色动作观察记录失败；按键已释放")
            if decision.reason != "green_release_inside":
                raise RuntimeError(f"绿色长按已释放并停止：{decision.reason}")
        self._cache_first_mechanisms(regions)
        self._qte_trace.observe(decision.reason)
        return True, regions

    def _cache_first_mechanisms(self, regions):
        for name, present in (
            ("green", regions.green_present),
            ("purple", bool(regions.purple_spans)),
            ("red", bool(regions.red_spans)),
            ("bubble", bool(regions.bubble_spans)),
        ):
            if present:
                self._cache_mechanism_frame(f"mechanism_first_{name}.png", first_only=True)

    def _cache_mechanism_frame(self, name, *, first_only=False):
        """每轮最多三张首次机制图及两张动作图；复用帧，仅缓存、不编码写盘。"""
        observer = getattr(self, "catch_observer", None)
        if observer is None or self._decision_frame is None:
            return
        try:
            if not first_only or name not in observer.evidence_frames:
                observer.evidence_frames[name] = self._decision_frame.copy()
                metadata = getattr(observer, "evidence_metadata", None)
                if isinstance(metadata, dict):
                    metadata.setdefault("mechanism_frames", {})[name] = dict(
                        captured_at_monotonic=self._decision_captured_at,
                        frame_region=self.roi_pos.as_tuple(),
                        qte_crop_percent=self.qte_pos_tuples,
                        capture_backend="control DXcam (BGR)",
                    )
        except Exception:
            log.exception("机制代表帧缓存失败；不改变输入决策")

    def _release_green_key(self):
        # 与纯决策状态分开：只有原生释放成功才清除待释放标记，失败时 finally 会重试。
        self._green_release_pending = True
        pydirectinput.qte_key_up()
        self._green_release_pending = False

    def _release_green_on_missing_frame(self):
        decision = self._mechanism_policy.invalidate_observation()
        if decision.action == "up":
            self._release_green_key()
            raise RuntimeError("绿色长按期间画面不可用，已释放并停止")

    @staticmethod
    def _blue_evidence(target, reading):
        if target != "blue" or reading is None:
            return {}
        return dict(
            blue_visible_spans=reading.visible_spans,
            blue_safe_spans=reading.safe_spans,
            blue_repaired_cursor_gap=reading.repaired_cursor_gap,
            blue_boundary_policy="raw_columns_inset_no_tolerance",
        )

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
                        mechanism_regions=None
                        if self._mechanism_regions is None
                        else dict(
                            green_present=self._mechanism_regions.green_present,
                            purple_spans=self._mechanism_regions.purple_spans,
                            red_spans=self._mechanism_regions.red_spans,
                            bubble_spans=self._mechanism_regions.bubble_spans,
                        ),
                        configured_timing=dict(
                            loop_sleep_seconds=self.loop_sleep_seconds,
                            hold_seconds=self.qte_hold_seconds,
                            settle_seconds=self.qte_settle_seconds,
                        ),
                        pointer=None
                        if self._pointer_reading is None
                        else dict(
                            reason=self._pointer_reading.reason,
                            candidates=[
                                dict(x=p.x, brightness=p.brightness)
                                for p in self._pointer_reading.candidates
                            ],
                            minimum_brightness=200,
                            minimum_separation=12,
                        ),
                        **details,
                    )
                    self._feedback_session.begin_press(decision, self._decision_frame)
            except Exception:
                log.exception("QTE 按键观察记录失败；仍执行原按键调用")
        # 缺省沿用旧驱动时序；显式调整时使用可取消等待，不改全局 PAUSE。
        if (self.qte_hold_seconds, self.qte_settle_seconds) != (0.1, 0.2):
            return pydirectinput.press_qte(self.qte_hold_seconds, self.qte_settle_seconds)
        return pydirectinput.press("space")

    def _sleep_loop(self) -> None:
        run_control.sleep(self.loop_sleep_seconds)

    def _grab_qte_frames(self, sct: capture_backend.DxCameraCapture) -> np.ndarray | None:
        """截取完整 QTE 区域并转换为 OpenCV HSV 图像。"""
        frame = sct.grab(self.roi_pos)
        # 只保留当前检测帧引用；真正有按键尝试时由观察器复制，不新增截图。
        if self._feedback_session is not None or getattr(self, "catch_observer", None) is not None:
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
        self._pointer_reading = read_pointer(roi_hsv)
        return self._pointer_reading.x

    def _mask_column_has_color(self, mask: np.ndarray, x: int) -> bool:
        """检查整列及其左右容差窗口内是否有颜色，容忍光标在采样间隔内跨越色条。"""
        left = max(0, x - self.press_tolerance_pixels)
        right = min(mask.shape[1], x + self.press_tolerance_pixels + 1)
        return cv2.countNonZero(mask[:, left:right]) > 0

    def _finish_fishing(self) -> None:
        started = time.monotonic()
        catch_observer = getattr(self, "catch_observer", None)
        if catch_observer is None:
            raise RuntimeError("结算观察器不可用，已停止，未关闭页面或重新抛竿")
        if catch_observer is not None:
            try:
                catch_observer.finish()
            except Exception as exc:
                from bd2_fishing.game.fishing.settlement_rules import CatchResult

                catch_observer.result = CatchResult(
                    "unknown", f"结算观察失败：{type(exc).__name__}"
                )
                log.exception("结算观察失败；不把 QTE 退出当作捕获成功")
                if (
                    catch_observer.evidence_metadata.get("panel_open") is not True
                    and catch_observer.evidence_metadata.get("page_state") != "idle"
                ):
                    raise RoundObservationError("结算观察失败，未操作页面") from exc
            if (
                catch_observer.evidence_metadata.get("panel_open") is not True
                and catch_observer.evidence_metadata.get("page_state") != "idle"
            ):
                raise RoundObservationError("等待后仍未确认结算面板")
        check_unconfirmed_limit(self, catch_observer)
        run_control.sleep(max(0, self.fish_end_wait_time - (time.monotonic() - started)))
        page = catch_observer.inspect_current_page()
        if page == "idle":
            catch_observer.wait_until_idle()
            return
        if page != "panel":
            raise RoundObservationError("结算页面已变化，未发送关闭点击")
        close_confirmed_panel(self, catch_observer)

    def _on_control_timeout(self, sct) -> None:
        """期限后只读保存现场；释放 QTE 输入后由轮次边界检查恢复条件。"""
        run_control.checkpoint()
        observer = getattr(self, "catch_observer", None)
        details = dict(limit_seconds=self.longest_keep_time, state="capture_unavailable")
        try:
            frame = sct.grab(self.roi_pos)
            details["captured_at_monotonic"] = time.monotonic()
            details["capture_backend"] = "control DXcam (BGR)"
            details["frame_region"] = self.roi_pos.as_tuple()
            if frame is not None:
                if observer is not None:
                    observer.evidence_frames["timeout_control.png"] = frame.copy()
                time_hsv, _ = self._split_roi_and_time(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
                if self._time_bar_visible(time_hsv):
                    details["state"] = "qte_active"
                else:
                    details["state"] = "unrecognized_page"
                    if observer is not None:
                        # 无倒计时不等于已结算；使用现有面板/奖励识别补充判断，不发输入。
                        observer.finish()
                        if observer.evidence_metadata.get("panel_open"):
                            details["state"] = "settlement_visible"
                        elif observer.evidence_metadata.get("page_state") in {"idle", "waiting"}:
                            details["state"] = observer.evidence_metadata["page_state"]
        except Exception as exc:
            details["inspection_error"] = type(exc).__name__
        finally:
            if observer is not None:
                observer.evidence_metadata["control_timeout"] = details
        labels = {
            "capture_unavailable": "无法取得有效截图",
            "qte_active": "游戏倒计时条仍可见",
            "unrecognized_page": "未确认当前页面",
            "settlement_visible": "已看到结算面板，尚未关闭",
            "idle": "已看到钓鱼待机控件",
            "waiting": "已看到等待咬钩控件，不能重复抛竿",
        }
        raise QTEControlTimeout(
            f"QTE 控制达到 {self.longest_keep_time} 秒上限：{labels[details['state']]}；"
            "本轮未确认，等待恢复检查"
        )

    def _yellow_mask(self, roi_hsv: np.ndarray) -> np.ndarray:
        raw = cv2.inRange(roi_hsv, self.yellow_range.lower, self.yellow_range.upper)
        self._yellow_source_mask = raw
        self._yellow_source_pixels = cv2.countNonZero(raw)
        # 真实 M04/M06/M12/M14 仅有 1–4 个残色像素，膨胀后却被当成黄条。
        # 有效目标仍沿用原膨胀填孔；是否延后当前机会由中心偏好规则决定。
        if self._yellow_source_pixels < self.yellow_source_min_pixels:
            return np.zeros_like(raw)
        # 膨胀核随窗口宽度缩放：光标宽度随分辨率变大，核跟着变大才能填掉光标压住黄条挖出的洞。
        kernel_size = geometry.scale_pixel_length(
            7,
            self.pixel_threshold_scale.width_factor,
            minimum=3,
        )
        if kernel_size % 2 == 0:
            kernel_size += 1
        return cv2.dilate(raw, np.ones((kernel_size, kernel_size), np.uint8), iterations=2)

    def _blue_mask(self, qte_hsv: np.ndarray) -> np.ndarray:
        return vision.create_color_mask(
            self.blue_range.lower, self.blue_range.upper, qte_hsv, is_dilate=False
        )

    def _yellow_overlap(self, mask, cursor, regions, *, active_range=None):
        forbidden = regions.blocked.copy()
        for left, right in regions.bubble_spans:
            forbidden[left:right] = True
        if regions.green_present:
            forbidden[:] = True
        if active_range is not None:
            left, right = active_range
            forbidden[:left] = True
            forbidden[right + 1 :] = True
        self._yellow_aim_decision = self._mechanism_policy.targets.yellow_aim.observe(
            self._yellow_source_mask,
            cursor,
            time.monotonic(),
            overlap=self._mask_column_has_color(mask, cursor),
            forbidden=forbidden,
            loop_seconds=self.loop_sleep_seconds,
        )
        if self._yellow_aim_decision.reason == "prefer_center":
            self._qte_trace.observe("yellow_center_wait")
        elif self._yellow_aim_decision.reason == "obscured_yellow_source":
            self._qte_trace.observe("yellow_obscured_rejected")
            self._cache_mechanism_frame("yellow_obscured_rejected.png", first_only=True)
        return self._yellow_aim_decision.overlap

    def _yellow_evidence(self, target):
        if target != "yellow" or self._yellow_aim_decision is None:
            return {}
        return {"yellow_aim": asdict(self._yellow_aim_decision)}

    def _record_sparse_yellow(self):
        if 0 < self._yellow_source_pixels < self.yellow_source_min_pixels:
            self._qte_trace.observe("yellow_source_rejected")
            # 每轮仅缓存第一张小控制帧，封存时后台编码；不为诊断额外截图。
            self._cache_mechanism_frame("yellow_sparse_rejected.png", first_only=True)

    def _on_bar_disappeared(self, no_bar_frames: int) -> bool:
        """连续多帧看不到倒计时条时确认本轮结束，避免单帧闪烁误判。"""
        if no_bar_frames > 80:
            self._qte_trace.reason = "time_bar_disappeared"
            log.debug("倒计时条已消失，等待结算观察")
            self._finish_fishing()
            return True
        return False


class FrostStraitQTEStrategy(BaseQTEStrategy):
    """默认钓鱼点：优先黄色，持续无黄色时回退蓝区，避开红色遮挡。"""

    def __init__(self, config: configparser.ConfigParser, region: Rect) -> None:
        super().__init__(config, region)
        self.red_range = vision.read_hsv_range(config, "roi", "red")

    def _track_targets(self, qte_hsv, cursor_x, regions):
        ordinary_hsv = regions.ordinary_pixels(qte_hsv)
        yellow_mask = regions.mask_target(self._yellow_mask(ordinary_hsv))
        self._record_sparse_yellow()
        yellow_present = bool(cv2.countNonZero(yellow_mask))
        blue_target = None
        if not yellow_present:
            blue_mask = regions.mask_target(self._blue_mask(ordinary_hsv))
            blue_target = read_blue_target(blue_mask, cursor_x, blocked=regions.blocked)
        blocked = bool(regions.blocked[cursor_x]) or self._red_obstruction_at_cursor(
            qte_hsv, cursor_x
        )
        if blocked:
            self._qte_trace.observe(
                "mechanism_obstruction" if regions.blocked[cursor_x] else "red_obstruction"
            )
        target = self._mechanism_policy.targets.observe(
            yellow_present=yellow_present,
            yellow_overlap=self._yellow_overlap(yellow_mask, cursor_x, regions)
            if yellow_present
            else None,
            blue=blue_target,
            blocked=blocked,
        )
        if target is not None:
            self._press_qte(
                "yellow_overlap" if target == "yellow" else "blue_fallback",
                cursor_x=cursor_x,
                check_x=cursor_x,
                target=target,
                yellow_source_pixels=self._yellow_source_pixels,
                yellow_source_min_pixels=self.yellow_source_min_pixels,
                **self._yellow_evidence(target),
                **self._blue_evidence(target, blue_target),
            )
        self._qte_trace.observe("tracking", cursor=cursor_x, pressed=target is not None)

    def _red_obstruction_at_cursor(self, roi_hsv: np.ndarray, cursor_x: int) -> bool:
        mask = cv2.inRange(roi_hsv, self.red_range.lower, self.red_range.upper)
        if cv2.countNonZero(mask) <= self.red_obstruction_pixel_threshold:
            return False
        # 与目标掩膜使用相同量级的扩张，避免黄/蓝膨胀跨过遮挡边缘。
        margin = geometry.scale_pixel_length(7, self.pixel_threshold_scale.width_factor, minimum=3)
        left = max(0, cursor_x - margin - self.press_tolerance_pixels)
        right = min(mask.shape[1], cursor_x + margin + self.press_tolerance_pixels + 1)
        return cv2.countNonZero(mask[:, left:right]) > 0


class AbyssMawQTEStrategy(BaseQTEStrategy):
    """处理深渊巨口的黄蓝条规则，并用挡板限制当前有效判定范围。"""

    def __init__(self, config: configparser.ConfigParser, region: Rect) -> None:
        super().__init__(config, region)
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

        self._blocker_detector = BlockerDetector(
            self.blocker_ranges,
            min_width=self.blocker_shape_min_width,
            max_width=self.blocker_shape_max_width,
            min_height=self.blocker_shape_min_height,
            max_height=self.blocker_shape_max_height,
        )

    def _track_targets(self, qte_hsv, cursor_x, regions):
        ordinary_hsv = regions.ordinary_pixels(qte_hsv)
        yellow_mask = regions.mask_target(self._yellow_mask(ordinary_hsv))
        self._record_sparse_yellow()
        blue_mask = regions.mask_target(self._blue_mask(ordinary_hsv))
        blocker_rect = self._blocker_detector.read(qte_hsv, self._cursor_mask(qte_hsv))
        left_x, right_x = active_range_for_blocker(blocker_rect, cursor_x, yellow_mask.shape[1])
        check_x = max(left_x, min(cursor_x, right_x))
        if regions.blocked[check_x]:
            self._mechanism_policy.targets.invalidate()
            self._qte_trace.observe("mechanism_obstruction")
            return
        yellow_pixels = cv2.countNonZero(yellow_mask[:, left_x : right_x + 1])
        blue_target = read_blue_target(
            blue_mask, cursor_x, blocked=regions.blocked, active_range=(left_x, right_x)
        )
        yellow_present = yellow_pixels > self.abyss_yellow_pixel_threshold
        target = self._mechanism_policy.targets.observe(
            yellow_present=yellow_present,
            yellow_overlap=self._yellow_overlap(
                yellow_mask, check_x, regions, active_range=(left_x, right_x)
            )
            if yellow_present
            else None,
            blue=blue_target,
        )
        if target is not None:
            self._press_qte(
                "yellow_overlap" if target == "yellow" else "blue_fallback",
                cursor_x=cursor_x,
                check_x=check_x if target == "yellow" else cursor_x,
                target=target,
                active_range=(left_x, right_x),
                blocker_rect=blocker_rect,
                yellow_pixels=yellow_pixels,
                yellow_threshold=self.abyss_yellow_pixel_threshold,
                yellow_source_pixels=self._yellow_source_pixels,
                yellow_source_min_pixels=self.yellow_source_min_pixels,
                **self._yellow_evidence(target),
                **self._blue_evidence(target, blue_target),
            )
        self._qte_trace.observe(
            "tracking",
            blocker=blocker_rect,
            cursor=cursor_x,
            yellow=yellow_pixels,
            active=(left_x, right_x),
            pressed=target is not None,
        )
