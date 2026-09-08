import threading
import unittest
from unittest.mock import Mock, patch

from bd2_fishing.app import service as runtime_service
from bd2_fishing.game.fishing import actions as fishing_actions
from bd2_fishing.infrastructure.windows import input as controlled_input
from bd2_fishing.runtime import control as run_control


class RunControlTests(unittest.TestCase):
    def test_cancel_interrupts_long_wait(self):
        entered, finished = threading.Event(), threading.Event()
        control = run_control.RunControl()

        def work():
            with run_control.use_control(control):
                entered.set()
                try:
                    run_control.sleep(60)
                except run_control.RunStopped:
                    finished.set()

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(1))
        control.stop(lambda: None)
        self.assertTrue(finished.wait(1))
        thread.join(1)

    def test_stop_prevents_later_input_and_releases_pressed_keys(self):
        entered = threading.Event()
        control = run_control.RunControl()
        release = Mock()
        with (
            patch.object(
                controlled_input._input, "keyDown", side_effect=lambda *a, **k: entered.set()
            ),
            patch.object(controlled_input._input, "keyUp") as key_up,
        ):

            def work():
                try:
                    with run_control.use_control(control):
                        fishing_actions.cast_rod()
                except run_control.RunStopped:
                    pass

            thread = threading.Thread(target=work, daemon=True)
            thread.start()
            self.assertTrue(entered.wait(1))
            control.stop(release)
            thread.join(1)
            self.assertFalse(thread.is_alive())
            release.assert_called_once()
            key_up.assert_not_called()  # 已退出原流程，由统一清理释放按键。
            with run_control.use_control(control), self.assertRaises(run_control.RunStopped):
                controlled_input.press("space")

    def test_release_bypasses_failsafe_and_restores_setting(self):
        with (
            patch.object(controlled_input._input, "keyUp") as up,
            patch.object(controlled_input._input, "mouseUp") as mouse_up,
        ):
            before = controlled_input._input.FAILSAFE
            controlled_input.release_inputs()
            self.assertEqual([call.args[0] for call in up.call_args_list], ["space", "up", "t"])
            mouse_up.assert_called_once_with(_pause=False)
            self.assertEqual(controlled_input._input.FAILSAFE, before)

    def test_cancellation_is_not_swallowed_as_ocr_error(self):
        self.assertFalse(issubclass(run_control.RunStopped, Exception))


class TaskControllerTests(unittest.TestCase):
    def make_controller(self):
        entered = threading.Event()
        calls = []

        def work():
            calls.append(1)
            entered.set()
            run_control.sleep(60)

        controller = runtime_service.TaskController(work, Mock())
        self.addCleanup(controller.close)
        return controller, entered, calls

    def test_idle_repeated_start_stop_and_restart(self):
        controller, entered, calls = self.make_controller()
        controller.stop()
        self.assertIsNone(controller.worker)
        controller.start()
        self.assertTrue(entered.wait(1))
        for _ in range(20):
            controller.start()
        self.assertFalse(controller.control.stopped.is_set())
        self.assertEqual(len(calls), 1)
        controller.stop()
        controller.worker.join(1)
        self.assertFalse(controller.running)
        controller.stop()
        self.assertEqual(len(calls), 1)
        entered.clear()
        controller.start()
        self.assertTrue(entered.wait(1))
        self.assertEqual(len(calls), 2)

    def test_stopping_native_call_cannot_spawn_duplicate_worker(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def native_call():
            calls.append(1)
            entered.set()
            release.wait(2)

        controller = runtime_service.TaskController(native_call, Mock())
        try:
            controller.start()
            self.assertTrue(entered.wait(1))
            original = controller.worker
            controller.stop()
            controller.start()
            self.assertIs(controller.worker, original)
            self.assertEqual(calls, [1])
        finally:
            release.set()
            controller.close()

    def test_failure_returns_to_idle_and_can_restart(self):
        target = Mock(side_effect=RuntimeError("capture failed"))
        controller = runtime_service.TaskController(target, Mock())
        with self.assertLogs("bd2_fishing.app.service", level="ERROR"):
            controller.start()
            controller.worker.join(1)
            controller.start()
            controller.worker.join(1)
        self.assertEqual(target.call_count, 2)
        self.assertFalse(controller.worker.is_alive())
        controller.close()


if __name__ == "__main__":
    unittest.main()
