"""Offline Selenium integration tests; never contact the golf booking service."""
import threading
import time
import unittest
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

from test_app_settings import app_module


PAGE = """<!doctype html><meta charset="utf-8">
<div id="time"></div><div id="confirm"></div>
<script>
window.jQuery = {active:0};
window.slots = [ ['20261026','B','2','IN','1324','in-token'],
                 ['20261026','B','1','OUT','1324','out-token'] ];
window.calls = []; window.submitted = 0; window.outcome = 'success';
function Date_Click(type, date) {
  jQuery.active++;
  setTimeout(() => {
    document.querySelector('#confirm').innerHTML = '';
    const list = document.querySelector('#time');
    list.replaceChildren();
    for (const slot of slots) {
      const a = document.createElement('a');
      a.href = 'javascript:Book_Confirm(' + slot.map(x=>JSON.stringify(x)).join(',') + ');';
      a.textContent = slot[3] + ' ' + slot[4]; list.append(a);
    }
    // Empty responses still update the time panel.
    if (!slots.length) list.textContent = 'No slots';
    jQuery.active--;
  }, 150);
}
function Book_Confirm(...args) {
  calls.push(args); jQuery.active++;
  setTimeout(() => {
    document.querySelector('#confirm').innerHTML = '<button class="btn_reOK">Reserve</button>';
    document.querySelector('.btn_reOK').onclick = () => {
      if (!confirm('위와 같이 예약을 하시겠습니까?')) return;
      submitted++;
      if (outcome === 'taken') {
        alert('죄송합니다. 이미 다른분이 OUT 코스 / 13:24 예약을 하셨습니다.1');
        slots = slots.filter(x => x[3] !== args[3]); outcome = 'success';
      } else if (outcome === 'existing') {
        alert('[당일 중복예약 제한] 이미 예약을 하셨기 때문에 추가 예약을 하실수 없습니다.');
      } else if (outcome === 'success') alert('예약이 정상적으로 처리되었습니다.');
    };
    jQuery.active--;
  }, 150);
}
</script>"""


class BrowserReservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        cls.driver = webdriver.Chrome(options=options)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()

    def setUp(self):
        self.driver.get("data:text/html;charset=utf-8," + quote(PAGE))
        self.bot = app_module.CastlexBot(threading.Event(), lambda msg: None)
        self.bot.driver = self.driver
        self.bot.wait = WebDriverWait(self.driver, 5)
        self.bot._reserve_ready = True
        self.priorities = [{"date": "20261026", "base_time": "13:24"}]

    def test_both_courses_preserve_all_arguments(self):
        self.bot.select_date_js("20261026")
        slots = self.bot.get_available_slots("20261026")
        self.assertEqual(len(slots), 2)
        for slot in slots:
            self.assertTrue(self.bot.select_time_js(slot))
            self.assertEqual(self.driver.execute_script("return calls[calls.length-1]"), list(slot))

    def test_failed_in_refreshes_then_out_succeeds(self):
        self.driver.execute_script("outcome='taken'")
        result, successes = self.bot.run_priorities_multi("real", self.priorities)
        self.assertEqual(result, "REAL_MULTI_SUCCESS(1)")
        self.assertEqual(len(successes), 1)
        self.assertEqual(self.driver.execute_script("return calls.map(x=>x[3])"), ["IN", "OUT"])
        self.assertEqual(self.driver.execute_script("return submitted"), 2)

    def test_existing_reservation_stops_date(self):
        self.driver.execute_script("outcome='existing'")
        result, successes = self.bot.run_priorities_multi("real", self.priorities)
        self.assertEqual(result, "EXISTING_RESERVATIONS(1)")
        self.assertEqual(successes, [])
        self.assertEqual(self.driver.execute_script("return submitted"), 1)

    def test_test_mode_does_not_submit(self):
        result, successes = self.bot.run_priorities_multi("test", self.priorities)
        self.assertEqual(result, "TEST_MULTI_OK(1)")
        self.assertEqual(self.driver.execute_script("return submitted"), 0)

    def test_empty_response_does_not_reuse_previous_slots(self):
        self.bot.select_date_js("20261026")
        self.assertEqual(len(self.bot.get_available_slots("20261026")), 2)
        self.driver.execute_script("slots=[]")
        self.bot.select_date_js("20261026")
        self.assertEqual(self.bot.get_available_slots("20261026"), [])

    def test_missing_result_is_not_success(self):
        self.driver.execute_script("outcome='silent'")
        result, successes = self.bot.run_priorities_multi("real", self.priorities)
        self.assertEqual(result, "UNKNOWN_RESULT")
        self.assertEqual(successes, [])
        self.assertEqual(self.driver.execute_script("return submitted"), 1)


if __name__ == "__main__":
    unittest.main()
