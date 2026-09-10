"""面向用户的日志不暴露诊断参数，同时保留维护证据与有界投递。"""

import logging
import sys
import unittest
from unittest.mock import Mock

from bd2_fishing.perception.tracing import OCRContextFilter, ocr_log_context
from bd2_fishing.runtime.context import fishing_round, get_logger
from bd2_fishing.runtime.geometry import Rect
from bd2_fishing.ui.logs import UILogHandler


class UILogTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(self.id())
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.handler = UILogHandler()
        self.logger.addHandler(self.handler)

    def tearDown(self):
        self.logger.removeHandler(self.handler)
        self.handler.close()

    def test_round_id_and_parameters_are_only_in_diagnostic_view(self):
        with fishing_round("sample-123"):
            get_logger(self.logger.name).warning(
                "像素=%d", 99, extra={"user_message": "等待上钩超时，正在恢复。"}
            )
            get_logger(self.logger.name).info("第 %d 轮 · 开始钓鱼", 2)
        first, second = self.handler.drain()
        self.assertIn("△ 注意", first.display())
        self.assertNotIn("99", first.message)
        self.assertIn("像素=99", first.display(True))
        self.assertIn("sample-123", first.display(True))
        self.assertEqual(second.message, "第 2 轮 · 开始钓鱼")
        self.assertNotIn("sample-123", second.display())

    def test_traceback_hidden_from_normal_view_and_original_record_unchanged(self):
        try:
            raise ValueError("technical detail")
        except ValueError:
            record = self.logger.makeRecord(
                self.logger.name, logging.ERROR, __file__, 1, "识别失败", (), sys.exc_info()
            )
        self.handler.handle(record)
        entry = self.handler.drain()[0]
        self.assertEqual(entry.message, "识别失败")
        self.assertNotIn("Traceback", entry.display())
        self.assertIn("ValueError: technical detail", entry.display(True))
        self.assertIsNone(record.exc_text)
        self.assertIsNotNone(record.exc_info)

    def test_diagnostic_storm_cannot_displace_progress_or_warning(self):
        for i in range(650):
            self.logger.debug("采样=%d", i)
        self.logger.info("等待上钩")
        self.logger.warning("窗口发生变化")
        entries = self.handler.drain(1000)
        self.assertEqual(self.handler.skipped, 150)
        self.assertEqual(len(entries), 502)
        self.assertEqual(
            [e.message for e in entries if e.level >= logging.INFO], ["等待上钩", "窗口发生变化"]
        )

    def test_emit_does_not_format_and_drain_is_bounded(self):
        formatter = Mock(wraps=self.handler.formatter)
        self.handler.setFormatter(formatter)
        for _ in range(5):
            self.logger.info("等待上钩")
        formatter.format.assert_not_called()
        self.assertEqual(len(self.handler.drain(2)), 2)
        self.assertEqual(self.handler.messages.qsize(), 3)
        self.assertEqual(formatter.format.call_count, 2)

    def test_malformed_message_does_not_stop_drain(self):
        self.logger.info("%d", "bad argument")
        self.logger.info("后续进展")
        entries = self.handler.drain()
        self.assertEqual(len(entries), 2)
        self.assertIn("格式有误", entries[0].message)
        self.assertEqual(entries[1].message, "后续进展")

    def test_equal_timestamps_keep_arrival_order_across_both_queues(self):
        for level in (logging.DEBUG, logging.INFO, logging.WARNING):
            record = self.logger.makeRecord(
                self.logger.name, level, __file__, 1, "%d", (level,), None
            )
            record.created = 1.0
            self.handler.handle(record)
        self.assertEqual(
            [e.level for e in self.handler.drain()], [logging.DEBUG, logging.INFO, logging.WARNING]
        )

    def test_full_ui_queue_does_not_remove_file_handler_copy(self):
        other = Mock(spec=logging.Handler)
        other.level = logging.DEBUG
        self.logger.addHandler(other)
        try:
            for _ in range(1502):
                self.logger.info("运行进展")
            self.assertEqual(self.handler.skipped, 2)
            self.assertEqual(other.handle.call_count, 1502)
        finally:
            self.logger.removeHandler(other)

    def test_optional_empty_ocr_warning_is_diagnostic_but_other_warnings_remain_visible(self):
        context_filter = OCRContextFilter()
        self.logger.addFilter(context_filter)
        try:
            with ocr_log_context("背包提示", Rect(0, 0, 10, 10), True):
                self.logger.warning("The text detection result is empty")
                self.logger.warning("Unexpected warning")
                self.logger.error("The text detection result is empty")
            self.assertEqual(self.handler.messages.qsize(), 2)
            self.assertEqual(self.handler.diagnostics.qsize(), 1)
            entries = self.handler.drain()
            self.assertTrue(entries[0].diagnostic_only)
            self.assertEqual(entries[0].level, logging.WARNING)
            self.assertIn("ROI=", entries[0].diagnostic)
            self.assertFalse(entries[1].diagnostic_only)
            self.assertFalse(entries[2].diagnostic_only)
        finally:
            self.logger.removeFilter(context_filter)
