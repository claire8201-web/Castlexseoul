import unittest
from unittest.mock import Mock

from reservation_logic import classify_booking_message, parse_booking_link
import test_delayed_open


class ReservationFlowTests(unittest.TestCase):
    def setUp(self):
        fixture = test_delayed_open.DelayedOpenTests()
        fixture.setUp()
        self.bot = fixture.bot
        self.bot._reserve_ready = True
        self.bot.go_reserve_page = Mock()
        self.bot.select_time_js = Mock(return_value=True)
        self.in_slot = test_delayed_open.slot()
        self.out_slot = test_delayed_open.slot(course="OUT")
        self.bot.wait_for_available_times = Mock(return_value=[self.in_slot, self.out_slot])

    def run_bot(self, priorities=None):
        return self.bot.run_priorities_multi("real", priorities or [{"date": "20261010", "base_time": "12:20"}])

    def test_same_time_two_courses_and_fresh_list(self):
        self.bot.click_reserve_and_judge = Mock(side_effect=[("SLOT_TAKEN", "taken"), ("SUCCESS_TEXT", "ok")])
        self.bot.get_available_slots.return_value = [self.out_slot]
        result, successes = self.run_bot()
        self.assertEqual([c.args[0] for c in self.bot.select_time_js.call_args_list], [self.in_slot, self.out_slot])
        self.bot.get_available_slots.assert_called_once_with("20261010")
        self.bot.go_reserve_page.assert_not_called()
        self.assertEqual(len(successes), 1)

    def test_removed_candidates_not_attempted(self):
        self.bot.click_reserve_and_judge = Mock(return_value=("SLOT_TAKEN", "taken"))
        self.bot.get_available_slots.return_value = []
        self.run_bot()
        self.bot.select_time_js.assert_called_once_with(self.in_slot)

    def test_success_reopens_page_for_next_date(self):
        self.bot.wait_for_available_times.side_effect = lambda date: [test_delayed_open.slot(date)]
        self.bot.click_reserve_and_judge = Mock(return_value=("SUCCESS_TEXT", "ok"))
        result, successes = self.run_bot([{"date": d, "base_time": "12:20"}
                                          for d in ("20261010", "20261011")])
        self.assertEqual(result, "REAL_MULTI_SUCCESS(2)")
        self.bot.go_reserve_page.assert_called_once()

    def test_already_reserved_skips_repeated_date_and_continues_next(self):
        self.bot.click_reserve_and_judge = Mock(return_value=("ALREADY_RESERVED", "existing"))
        self.bot.wait_for_available_times.side_effect = lambda date: [test_delayed_open.slot(date)]
        result, successes = self.run_bot([{"date": d, "base_time": "12:20"}
                                          for d in ("20261010", "20261010", "20261011")])
        self.assertEqual(result, "EXISTING_RESERVATIONS(2)")
        self.assertEqual(successes, [])
        self.assertEqual(self.bot.select_time_js.call_count, 2)
        self.bot.get_available_slots.assert_not_called()

    def test_unknown_or_session_loss_stops_without_claiming_success(self):
        for status in ("UNKNOWN_RESULT", "SESSION_EXPIRED"):
            self.bot.click_reserve_and_judge = Mock(return_value=(status, "unknown"))
            result, successes = self.run_bot()
            self.assertEqual(result, status)
            self.assertEqual(successes, [])
            self.bot.get_available_slots.assert_not_called()

    def test_still_listed_failed_slot_not_repeated(self):
        self.bot.wait_for_available_times.return_value = [self.in_slot]
        self.bot.get_available_slots.return_value = [self.in_slot]
        self.bot.click_reserve_and_judge = Mock(return_value=("SLOT_TAKEN", "taken"))
        self.run_bot()
        self.bot.select_time_js.assert_called_once()

    def test_original_link_arguments_preserved(self):
        for course, code in (("IN", "2"), ("OUT", "1")):
            args = parse_booking_link(f"javascript:Book_Confirm('20261010','B','{code}','{course}','1221','special');", "20261010")
            self.assertEqual(args, ("20261010", "B", code, course, "1221", "special"))

    def test_invalid_or_stale_links_rejected(self):
        for href in ("Book_Confirm('20261011','B','2','IN','1221','')",
                     "Book_Confirm('20261010','B','2','IN','2461','')",
                     "Book_Confirm('20261010','B','2','IN','1221',evil())",
                     "Book_Confirm('20261010','B','2','IN','1221','');evil()"):
            with self.assertRaises(ValueError):
                parse_booking_link(href, "20261010")

    def test_live_seven_argument_link(self):
        href = "JavaScript:Book_Confirm('20261020','화','2', 'IN','0610','','');"
        self.assertEqual(parse_booking_link(href, "20261020"),
                         ("20261020", "화", "2", "IN", "0610", "", ""))

    def test_actual_log_messages_classified(self):
        messages = {
            "[당일 중복예약 제한]\n 고객님께서 이미 예약을 하셨기 때문에 추가 예약을 하실수 없습니다.": "ALREADY_RESERVED",
            "죄송합니다. 이미 다른분이 OUT 코스 / 13:17 예약을 하셨습니다.1": "SLOT_TAKEN",
            "위와 같이 예약을 하시겠습니까?": "CONFIRM",
            "예약이 정상적으로 처리되었습니다.": "SUCCESS_TEXT",
            "로그인 후 이용해 주세요": "SESSION_EXPIRED",
            "": "UNKNOWN_RESULT",
        }
        for text, expected in messages.items():
            self.assertEqual(classify_booking_message(text), expected)


if __name__ == "__main__":
    unittest.main()
