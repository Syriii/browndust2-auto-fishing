"""真实 150302 叠层提示、独立时刻与反例；不连接游戏。"""

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

import cv2

from bd2_fishing.app.ocr_setup import build_ocr_engine
from bd2_fishing.game.fishing.notices import confirm_exhausted_notice
from bd2_fishing.game.fishing.scene import FishingSceneReader
from bd2_fishing.infrastructure.settings import read_ini
from bd2_fishing.runtime.geometry import Rect

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/catch_result"


class ExhaustedNoticeImages(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = read_ini(str(ROOT / "bd2_fishing/resources/default.ini"))
        cls.engine = build_ocr_engine(cls.config)

    def test_real_notice_and_holdout_override_underlying_close_hint(self):
        for name in ("notice_150302_20260913.png", "notice_150302_holdout_20260913.png"):
            for width, height in ((945, 532), (1192, 666), (1280, 720)):
                with self.subTest(name=name, size=(width, height)):
                    frame = cv2.resize(cv2.imread(str(FIXTURES / name)), (width, height))
                    reader = FishingSceneReader(self.config, Rect(0, 0, width, height))
                    reading = reader.inspect(frame)
                    self.assertEqual(
                        (reading.state, reading.panel_kind), ("panel", "exhausted_notice")
                    )
                    observer = SimpleNamespace(
                        engine=self.engine,
                        evidence_frames={"resume_latest.png": frame},
                        evidence_metadata={},
                    )
                    self.assertTrue(confirm_exhausted_notice(observer))

    def test_existing_panels_and_other_error_are_not_notice(self):
        paths = [
            *FIXTURES.glob("*.png"),
            *(ROOT / "tests/fixtures/voyage_pages/errors").glob("*.png"),
        ]
        for path in paths:
            if path.name in {"notice_150302_20260913.png", "notice_150302_holdout_20260913.png"}:
                continue
            with self.subTest(name=path.name):
                frame = cv2.imread(str(path))
                height, width = frame.shape[:2]
                reader = FishingSceneReader(self.config, Rect(0, 0, width, height))
                self.assertNotEqual(reader.inspect(frame).panel_kind, "exhausted_notice")

    def test_both_text_and_confirm_are_required(self):
        for left, top, right, bottom in ((390, 236, 555, 274), (448, 272, 499, 311)):
            frame = cv2.imread(str(FIXTURES / "notice_150302_20260913.png"))
            frame[top:bottom, left:right] = 0
            reader = FishingSceneReader(self.config, Rect(0, 0, 945, 532))
            self.assertNotEqual(reader.inspect(frame).panel_kind, "exhausted_notice")
