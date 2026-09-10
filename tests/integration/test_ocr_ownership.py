"""共享 OCR 引擎的跨轮互斥；不加载模型或连接游戏。"""

import configparser
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from bd2_fishing.game.fishing.settlement import CatchObserver
from bd2_fishing.infrastructure.ocr.engine import OCRBusyError, RapidOCREngine
from bd2_fishing.infrastructure.settings import DEFAULT_CONFIG_CONTENT
from bd2_fishing.runtime.control import RunControl, RunStopped, use_control
from bd2_fishing.runtime.geometry import Rect


def make_engine(backend):
    module = SimpleNamespace(
        EngineType=SimpleNamespace(ONNXRUNTIME="offline"), RapidOCR=Mock(return_value=backend)
    )
    with (
        patch.dict(sys.modules, {"rapidocr": module}),
        patch("bd2_fishing.infrastructure.ocr.engine.route_rapidocr_logs"),
    ):
        return RapidOCREngine()


class OCROwnershipTests(unittest.TestCase):
    def test_old_round_keeps_engine_exclusive_until_native_call_returns(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def backend(image, **flags):
            calls.append(flags)
            entered.set()
            if not release.wait(3):
                raise TimeoutError("offline gate timed out")
            return dict(txts=["17"], scores=[0.99], boxes=[])

        engine = make_engine(backend)
        config = configparser.ConfigParser()
        config.read_string(DEFAULT_CONFIG_CONTENT)
        region = Rect(0, 0, 875, 492)
        old, new = (CatchObserver(engine, config, region) for _ in range(2))
        frame = np.zeros((143, 350, 3), np.uint8)
        worker = threading.Thread(target=old.observe_timer, args=(frame, 1), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            old.stop_observing()
            # 新一轮及页面识别不能绕过旧一轮仍在持有的引擎。
            with self.assertLogs("bd2_fishing.game.fishing.settlement", level="WARNING"):
                new.observe_timer(frame, 2)
            for operation in (
                lambda: engine.detect(frame),
                lambda: engine.recognize(frame),
                lambda: engine.detect_and_recognize(frame),
                lambda: engine.recognize_region(frame, left=0, top=0, right=20, bottom=20),
            ):
                with self.assertRaises(OCRBusyError):
                    operation()
            self.assertEqual(len(calls), 1)
            self.assertFalse(new.readings)
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(old.readings)  # 旧轮封存后，迟到结果不回写。
        new.observe_timer(frame, 3)
        self.assertEqual(new.readings[-1][1], 17)
        result = engine.detect_and_recognize(frame)
        self.assertEqual(result[0].text, "17")
        self.assertEqual([call["use_det"] for call in calls], [False, False, True])

    def test_native_and_payload_errors_release_engine_for_retry(self):
        frame = np.zeros((20, 20, 3), np.uint8)
        for failure in (OSError("native error"), RunStopped("cancelled")):
            with self.subTest(failure=type(failure).__name__):
                backend = Mock(side_effect=[failure, None])
                engine = make_engine(backend)
                with self.assertRaises(type(failure)):
                    engine.recognize(frame)
                self.assertIsNone(engine.recognize(frame))
        engine = make_engine(Mock(return_value=None))
        with patch.object(engine, "_extract_payload", side_effect=ValueError("bad payload")):
            with self.assertRaises(ValueError):
                engine.recognize(frame)
        self.assertIsNone(engine.recognize(frame))

    def test_cancelled_caller_never_enters_native_engine(self):
        backend = Mock(return_value=None)
        engine = make_engine(backend)
        control = RunControl()
        control.stopped.set()
        with use_control(control), self.assertRaises(RunStopped):
            engine.recognize(np.zeros((20, 20, 3), np.uint8))
        backend.assert_not_called()
        self.assertIsNone(engine.recognize(np.zeros((20, 20, 3), np.uint8)))
