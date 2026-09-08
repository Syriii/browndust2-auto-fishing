"""用被阻塞的输出验证生产线程不等待磁盘，避免依赖机器速度的断言。"""

import logging
import threading
import unittest

from bd2_fishing.infrastructure.diagnostics.buffered_logging import BufferedHandler


class RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []
        self.entered = threading.Event()
        self.unblock = threading.Event()

    def emit(self, record):
        self.entered.set()
        self.unblock.wait(3)
        self.records.append((record, threading.get_ident()))


class BufferedLoggingTests(unittest.TestCase):
    def test_detail_backlog_reserves_space_for_result_and_error_records(self):
        sink = RecordingHandler()
        handler = BufferedHandler(sink, capacity=4)
        try:
            handler.handle(logging.makeLogRecord(dict(msg="blocked", levelno=logging.INFO)))
            self.assertTrue(sink.entered.wait(1))
            for _ in range(4):
                handler.handle(logging.makeLogRecord(dict(msg="detail", levelno=logging.DEBUG)))
            handler.handle(logging.makeLogRecord(dict(msg="important", levelno=logging.ERROR)))
            self.assertEqual(handler.dropped_records, 1)
        finally:
            sink.unblock.set()
            handler.close()
        self.assertIn("important", [record.getMessage() for record, _ in sink.records])

    def test_slow_sink_does_not_block_producer_and_overflow_is_reported(self):
        sink = RecordingHandler()
        handler = BufferedHandler(sink, capacity=1)
        record = logging.makeLogRecord(dict(msg="first", levelno=logging.INFO))
        try:
            handler.handle(record)
            self.assertTrue(sink.entered.wait(1))
            finished = threading.Event()

            def produce():
                handler.handle(logging.makeLogRecord(dict(msg="queued", levelno=logging.INFO)))
                handler.handle(logging.makeLogRecord(dict(msg="overflow", levelno=logging.INFO)))
                finished.set()

            producer = threading.Thread(target=produce)
            producer.start()
            self.assertTrue(finished.wait(1), "producer waited for the blocked output")
            producer.join(1)
            self.assertEqual(handler.dropped_records, 1)
        finally:
            sink.unblock.set()
            handler.close()
        messages = [r.getMessage() for r, _ in sink.records]
        self.assertIn("first", messages)
        self.assertIn("queued", messages)
        self.assertNotIn("overflow", messages)
        self.assertTrue(any("丢弃 1 条" in message for message in messages))
        self.assertTrue(all(tid != threading.get_ident() for _, tid in sink.records))

    def test_snapshot_keeps_round_and_exception_without_modifying_other_handlers_record(self):
        sink = RecordingHandler()
        handler = BufferedHandler(sink)
        values = ["original"]
        try:
            try:
                raise ValueError("evidence")
            except ValueError:
                import sys

                record = logging.makeLogRecord(
                    dict(
                        msg="message %s",
                        args=(values,),
                        levelno=logging.ERROR,
                        exc_info=sys.exc_info(),
                        round_id="round-a",
                    )
                )
            handler.handle(record)
            values.append("changed")
            self.assertEqual(record.msg, "message %s")
            self.assertEqual(record.args, (values,))
        finally:
            sink.unblock.set()
            handler.close()
        saved = sink.records[0][0]
        self.assertEqual(saved.getMessage(), "message ['original']")
        self.assertEqual(saved.round_id, "round-a")
        self.assertIn("ValueError: evidence", logging.Formatter().format(saved))

    def test_flush_and_close_drain_records_and_are_repeatable(self):
        sink = RecordingHandler()
        sink.unblock.set()
        handler = BufferedHandler(sink)
        handler.handle(logging.makeLogRecord(dict(msg="last", levelno=logging.INFO)))
        handler.flush()
        self.assertEqual(sink.records[0][0].msg, "last")
        handler.close()
        handler.close()
        self.assertFalse(handler._thread.is_alive())
