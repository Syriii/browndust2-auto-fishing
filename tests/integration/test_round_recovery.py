"""轮次等待之后页面变化，不能使用旧的待机判定重抛。"""

import configparser
import unittest
from unittest.mock import Mock, patch

from bd2_fishing.app.fishing_task import FishingBot
from bd2_fishing.game.fishing import actions, settlement
from bd2_fishing.infrastructure import settings
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class RoundRecoveryTests(unittest.TestCase):
    def test_page_changed_during_round_wait_prevents_second_cast(self):
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        capture = Mock()
        capture.__enter__ = Mock(return_value=capture)
        capture.__exit__ = Mock(return_value=False)
        bot = FishingBot(config, Rect(0, 0, 945, 532), Mock(), capture_factory=lambda **kw: capture)
        bot.choose_strategy = Mock()
        bot.wait_for_bite = Mock()
        bot.should_change_location = Mock(return_value=False)
        with (
            patch("bd2_fishing.app.fishing_task.window.WindowGuard"),
            patch.object(control, "sleep"),
            patch.object(settlement, "CatchObserver"),
            patch.object(settlement, "run_observed_qte") as qte,
            patch.object(
                settlement, "confirm_ready_for_next_cast", side_effect=TimeoutError("changed")
            ) as check,
            patch.object(actions, "cast_rod") as cast,
        ):
            with self.assertRaisesRegex(TimeoutError, "changed"):
                bot.run()
        cast.assert_called_once()
        qte.assert_called_once()
        check.assert_called_once()

    def test_resume_evidence_failure_preserves_original_stop(self):
        observer = Mock()
        observer.wait_until_idle.side_effect = control.RunStopped("focus")
        observer.finalize.side_effect = OSError("disk")
        with patch.object(settlement, "CatchObserver", return_value=observer):
            with self.assertRaisesRegex(control.RunStopped, "focus"):
                settlement.confirm_ready_for_next_cast(Mock(), Mock())
