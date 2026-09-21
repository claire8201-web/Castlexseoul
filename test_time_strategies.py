import unittest

import test_delayed_open


class TimeStrategyTests(unittest.TestCase):
    def setUp(self):
        fixture = test_delayed_open.DelayedOpenTests()
        fixture.setUp()
        self.bot = fixture.bot
        self.times = ["1146", "1153", "1200", "1207", "1214", "1221"]

    def test_nearest_preserves_original_order_and_ties(self):
        self.assertEqual(self.bot.pick_times_by_windows(self.times, "12:00"),
                         ["1200", "1153", "1207", "1146", "1214", "1221"])

    def test_directional_preferences(self):
        self.assertEqual(self.bot.pick_times_by_windows(self.times, "12:00", "later"),
                         ["1200", "1207", "1214", "1221", "1153", "1146"])
        self.assertEqual(self.bot.pick_times_by_windows(self.times, "12:00", "earlier"),
                         ["1200", "1153", "1146", "1207", "1214", "1221"])

    def test_offset_two_uses_actual_slots(self):
        self.assertEqual(self.bot.pick_times_by_windows(self.times, "12:00", "offset", 2),
                         ["1214", "1207", "1153", "1146", "1200", "1221"])

    def test_missing_target_and_irregular_gaps(self):
        self.assertEqual(self.bot.pick_times_by_windows(["1158", "1231", "1247"], "12:00", "offset", 2),
                         ["1247", "1231", "1158"])

    def test_offsets_at_list_edges_fall_back_without_losing_slots(self):
        for offset in (1, 2, 10):
            for target in ("11:00", "13:00"):
                with self.subTest(offset=offset, target=target):
                    result = self.bot.pick_times_by_windows(self.times, target, "offset", offset)
                    self.assertEqual(set(result), set(self.times))
                    self.assertEqual(len(result), len(self.times))

    def test_window_limits_and_empty_lists(self):
        for strategy in ("nearest", "later", "earlier", "offset"):
            self.assertEqual(self.bot.pick_times_by_windows([], "12:00", strategy), [])
            result = self.bot.pick_times_by_windows(["0959", "1000", "1200", "1400", "1401"], "12:00", strategy)
            self.assertEqual(set(result), {"1000", "1200", "1400"})

    def test_strategy_is_used_by_booking_flow(self):
        from unittest.mock import Mock
        self.bot.go_reserve_page = Mock()
        self.bot.wait_for_available_times = Mock(return_value=self.times)
        self.bot.select_time_js = Mock(return_value=True)
        self.bot.click_reserve_and_judge = Mock()
        self.bot.run_priorities_multi("test", [{"date": "20261010", "base_time": "12:00"}],
                                      time_strategy="offset", time_offset=2)
        self.bot.select_time_js.assert_called_once_with("20261010", "1214")
        self.bot.click_reserve_and_judge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
