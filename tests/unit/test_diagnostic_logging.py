import configparser
import io
import logging
import unittest
from unittest.mock import Mock, patch

import numpy as np

from bd2_fishing.game.fishing import qte as qte_strategy
from bd2_fishing.game.fishing.tracing import QTETrace, trace_qte
from bd2_fishing.infrastructure import settings as settings
from bd2_fishing.infrastructure.ocr.engine import route_rapidocr_logs
from bd2_fishing.perception.ocr import get_result_from_ocr
from bd2_fishing.perception.tracing import ocr_log_context
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.geometry import Rect


class OCRLoggingTests(unittest.TestCase):
    def test_original_warning_reaches_project_file_handler_with_context(self):
        vendor = logging.getLogger("RapidOCR")
        original = (vendor.handlers[:], vendor.filters[:], vendor.propagate, vendor.level)
        root = logging.getLogger()
        # StringIO 替代项目文件流；验证 propagate 路径不会丢失原始警告。
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root.addHandler(handler)
        try:
            route_rapidocr_logs()
            route_rapidocr_logs()
            vendor.setLevel(logging.INFO)
            with ocr_log_context("背包满提示", Rect(-100, 10, 200, 80), True):
                vendor.warning("The text detection result is empty")
            vendor.warning("unrelated warning")
            lines = stream.getvalue().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("场景=背包满提示 ROI=(-100, 10, 200, 80) 允许无文字=True", lines[0])
            self.assertIn("The text detection result is empty", lines[0])
            self.assertIn("未指定场景", lines[1])
            self.assertIn("unrelated warning", lines[1])
        finally:
            root.removeHandler(handler)
            vendor.handlers, vendor.filters, vendor.propagate, vendor.level = original

    def test_optional_empty_and_required_empty_keep_different_severity(self):
        capture = Mock(grab=Mock(return_value=np.zeros((4, 8, 3), dtype=np.uint8)))
        engine = Mock(detect_and_recognize=Mock(return_value=[]))
        for optional, purpose, level in (
            (True, "背包满提示", logging.DEBUG),
            (False, "钓场地点", logging.WARNING),
        ):
            with (
                self.subTest(optional=optional),
                self.assertLogs("bd2_fishing.perception.ocr", level="DEBUG") as logs,
            ):
                self.assertEqual(
                    get_result_from_ocr(
                        capture, engine, Rect(0, 0, 8, 4), purpose=purpose, expected_empty=optional
                    ),
                    [],
                )
            self.assertEqual(logs.records[-1].levelno, level)
            self.assertIn(f"场景={purpose}", logs.output[-1])
            self.assertIn("文本数=0", logs.output[-1])
            self.assertIn("耗时毫秒=", logs.output[-1])

    def test_no_new_frame_is_not_reported_as_ocr_failure(self):
        engine = Mock()
        with self.assertLogs("bd2_fishing.perception.ocr", level="DEBUG") as logs:
            self.assertIsNone(
                get_result_from_ocr(Mock(grab=Mock(return_value=None)), engine, Rect(0, 0, 8, 4))
            )
        self.assertIn("OCR 无新图", logs.output[0])
        engine.detect_and_recognize.assert_not_called()

    def test_ocr_exception_retains_traceback_and_capture_error_still_propagates(self):
        capture = Mock(grab=Mock(return_value=np.zeros((4, 8, 3), dtype=np.uint8)))
        engine = Mock(detect_and_recognize=Mock(side_effect=RuntimeError("model failure")))
        with self.assertLogs("bd2_fishing.perception.ocr", level="ERROR") as logs:
            self.assertIsNone(get_result_from_ocr(capture, engine, Rect(0, 0, 8, 4)))
        self.assertIsNotNone(logs.records[0].exc_info)
        self.assertIn("model failure", logs.output[0])
        capture.grab.side_effect = OSError("capture failed")
        with (
            self.assertLogs("bd2_fishing.perception.ocr", level="ERROR"),
            self.assertRaises(OSError),
        ):
            get_result_from_ocr(capture, engine, Rect(0, 0, 8, 4))


class QTELoggingTests(unittest.TestCase):
    def test_both_real_strategies_keep_press_and_end_behavior(self):
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        config.set(
            "diagnostics", "qte_feedback_enabled", "false"
        )  # 离线控制流程测试禁止真实截图线程。
        frame = np.zeros((24, 300, 3), dtype=np.uint8)
        mask = np.full((24, 300), 255, dtype=np.uint8)
        for strategy_class in (
            qte_strategy.FrostStraitQTEStrategy,
            qte_strategy.AbyssMawQTEStrategy,
        ):
            with (
                self.subTest(strategy=strategy_class.__name__),
                patch("builtins.print"),
                patch.object(qte_strategy.pydirectinput, "press") as press,
                self.assertLogs("bd2_fishing.game.fishing.tracing", level="DEBUG") as logs,
            ):
                strategy = strategy_class(config, Rect(0, 0, 1152, 648))
                strategy._grab_qte_frames = Mock(return_value=frame)
                strategy._split_roi_and_time = Mock(return_value=(frame, frame))
                strategy._time_bar_masks = Mock(return_value=(mask, mask))
                strategy._time_bar_visible_from_masks = Mock(side_effect=[True] + [False] * 81)
                strategy._cursor_mask = Mock(return_value=mask)
                strategy._find_cursor_x = Mock(return_value=20)
                strategy._start_feedback = Mock()  # 明确禁止离线检查连接真实采集器。
                strategy._yellow_mask = Mock(return_value=mask)
                strategy._sleep_loop = Mock()
                strategy._finish_fishing = Mock()
                strategy.play_qte(Mock())
                press.assert_called_once_with("space")
                strategy._finish_fishing.assert_called_once()
            self.assertIn("原因=time_bar_disappeared", logs.output[-1])
            self.assertIn("'tracking': 1", logs.output[-1])
            self.assertIn("'no_time_bar': 81", logs.output[-1])

    def test_repeated_rectangles_are_counted_and_changes_survive_summary(self):
        clock = Mock(return_value=0)
        with (
            patch("bd2_fishing.game.fishing.tracing.time.monotonic", clock),
            self.assertLogs("bd2_fishing.game.fishing.tracing", level="DEBUG") as logs,
        ):
            trace = QTETrace()
            for _ in range(100):
                trace.observe("tracking", blocker=(260, 0, 5, 24), cursor=100)
            self.assertEqual(len([r for r in logs.records if "QTE 控制采样" in r.getMessage()]), 0)
            clock.return_value = 5
            trace.observe("tracking", blocker=(187, 0, 8, 24), cursor=120, pressed=True)
            trace.reason = "time_bar_disappeared"
            trace.close()
        summaries = [r.getMessage() for r in logs.records if "QTE 控制采样" in r.getMessage()]
        self.assertEqual(len(summaries), 1)
        self.assertIn("'tracking': 101", summaries[0])
        self.assertIn("'blocker_changes': 2", summaries[0])
        self.assertIn("挡板x范围=(187, 260)", summaries[0])
        self.assertIn("原因=time_bar_disappeared", logs.output[-1])

    def test_detailed_samples_are_debug_only_and_off_by_default(self):
        with self.assertLogs("bd2_fishing.game.fishing.tracing", level="DEBUG") as logs:
            default = QTETrace()
            default.observe("tracking", blocker=(1, 0, 5, 24))
            detailed = QTETrace(detailed=True)
            detailed.observe("tracking", blocker=(2, 0, 5, 24))
        details = [record for record in logs.records if "QTE 逐帧" in record.getMessage()]
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].levelno, logging.DEBUG)
        self.assertIn("(2, 0, 5, 24)", details[0].getMessage())
        changes = [record for record in logs.records if "QTE 挡板变化" in record.getMessage()]
        self.assertEqual(len(changes), 2)  # 默认也保留位置变化，不只保留汇总。

    def test_cancellation_and_exception_flush_last_partial_window(self):
        class Strategy:
            qte_detail_log = False
            roi_pos = Rect(0, 0, 300, 30)
            longest_keep_time = 35

            @trace_qte
            def play(self, error):
                self._qte_trace.observe("no_frame")
                raise error

        for error, reason in (
            (run_control.RunStopped(), "cancelled"),
            (ValueError("bad mask"), "exception:ValueError"),
        ):
            strategy = Strategy()
            with (
                self.subTest(reason=reason),
                self.assertLogs("bd2_fishing.game.fishing.tracing", level="DEBUG") as logs,
            ):
                with self.assertRaises(type(error)):
                    strategy.play(error)
            self.assertIn("'no_frame': 1", logs.output[-2])
            self.assertIn("原因=" + reason, logs.output[-1])
            self.assertIsNone(strategy._qte_trace)

    def test_timeout_is_warning_instead_of_normal_completion(self):
        with self.assertLogs("bd2_fishing.game.fishing.tracing", level="WARNING") as logs:
            trace = QTETrace()
            trace.close()
        self.assertIn("原因=longest_keep_time", logs.output[0])


if __name__ == "__main__":
    unittest.main()
