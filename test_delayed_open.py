import ast
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock


# Load the bot without importing GUI, browser or credential dependencies.
source = Path(__file__).with_name("castlexseoul_v8.1.0.py")
tree = ast.parse(source.read_text(encoding="utf-8-sig"))
bot_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CastlexBot")


class DelayedOpenTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.clock = Mock()
        self.clock.monotonic.side_effect = lambda: self.now
        namespace = dict(threading=threading, time=self.clock,
                         EMPTY_TIMES_TIMEOUT_SECONDS=90.0,
                         EMPTY_TIMES_RETRY_SECONDS=2.0)
        exec(compile(ast.Module(body=[bot_node], type_ignores=[]), str(source), "exec"), namespace)
        self.event = Mock()
        self.event.is_set.return_value = False
        self.event.wait.side_effect = self.advance
        self.bot = namespace["CastlexBot"](self.event, Mock())
        self.bot.select_date_js = Mock()
        self.bot.get_available_times_hhmm = Mock()

    def advance(self, seconds):
        self.now += seconds

    def test_open_times_have_no_added_delay(self):
        self.bot.get_available_times_hhmm.return_value = ["1200"]
        self.assertEqual(self.bot.wait_for_available_times("20261010"), ["1200"])
        self.event.wait.assert_not_called()
        self.bot.select_date_js.assert_not_called()

    def test_opens_after_thirty_seconds(self):
        self.bot.get_available_times_hhmm.side_effect = lambda: ["1221"] if self.now >= 30 else []
        self.assertEqual(self.bot.wait_for_available_times("20261010"), ["1221"])
        self.assertEqual(self.now, 30)
        self.assertTrue(all(call.args == ("20261010",) for call in self.bot.select_date_js.call_args_list))

    def test_empty_date_times_out(self):
        self.bot.get_available_times_hhmm.return_value = []
        self.assertEqual(self.bot.wait_for_available_times("20261010"), [])
        self.assertEqual(self.now, 90)

    def test_stop_during_wait_prevents_another_request(self):
        self.bot.get_available_times_hhmm.return_value = []
        self.event.wait.side_effect = lambda seconds: setattr(self.event.is_set, "return_value", True)
        with self.assertRaises(RuntimeError):
            self.bot.wait_for_available_times("20261010")
        self.bot.select_date_js.assert_not_called()

    def test_modes_resume_after_delay_and_preserve_submit_guard(self):
        for mode, safe, expected in [("test", False, "TEST_MULTI_OK"),
                                     ("real", True, "SAFE_MULTI_OK"),
                                     ("real", False, "REAL_MULTI_SUCCESS")]:
            with self.subTest(mode=mode, safe=safe):
                self.now = 0
                self.bot.go_reserve_page = Mock()
                self.bot.select_time_js = Mock(return_value=True)
                self.bot.click_reserve_and_judge = Mock(return_value=("SUCCESS_TEXT", "OK"))
                self.bot.get_available_times_hhmm.side_effect = lambda: ["1221"] if self.now >= 30 else []
                result, successes = self.bot.run_priorities_multi(
                    mode, [{"date": "20261010", "base_time": "12:20"}], safe)
                self.assertTrue(result.startswith(expected))
                self.assertEqual(len(successes), 1)
                self.bot.select_time_js.assert_called_once_with("20261010", "1221")
                self.assertEqual(self.bot.click_reserve_and_judge.call_count, int(mode == "real" and not safe))

    def test_timeout_continues_to_next_priority(self):
        self.bot.go_reserve_page = Mock()
        self.bot.select_time_js = Mock(return_value=True)
        self.bot.get_available_times_hhmm.side_effect = lambda: ["1221"] if self.now >= 92 else []
        result, successes = self.bot.run_priorities_multi("test", [
            {"date": "20261010", "base_time": "12:20"},
            {"date": "20261011", "base_time": "12:20"}])
        self.assertEqual(result, "TEST_MULTI_OK(1)")
        self.assertEqual(successes[0][0], "20261011")

    def test_browser_error_is_not_treated_as_empty(self):
        self.bot.get_available_times_hhmm.side_effect = RuntimeError("session lost")
        with self.assertRaisesRegex(RuntimeError, "session lost"):
            self.bot.wait_for_available_times("20261010")
        self.event.wait.assert_not_called()


if __name__ == "__main__":
    unittest.main()
