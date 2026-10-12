"""Real document navigation regression tests matching the live site's functions."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from test_app_settings import app_module


class PageHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        date = params.get('book_date', ['20261020'])[0]
        args = [date, '화', '2', 'IN', '0610', '', '']
        href = 'JavaScript:Book_Confirm(' + ','.join(json.dumps(x) for x in args) + ');'
        from html import escape
        times = ('No available times; please return at 12:00' if date == '20261031'
                 else '<a href="' + escape(href, quote=True) + '">06:10</a>')
        confirm = '<button class="btn_reOK">Reserve</button>' if 'book_time' in params else ''
        notice = "<script>alert('Date selection notice');</script>" if date == '20261013' else ''
        page = '''<!doctype html><meta charset="utf-8"><div id="time">TIMES</div>
<div id="confirm">CONFIRM</div><script>
function Date_Click(proc, date) {
 location.replace('/reserve01.asp?proc_div='+proc+'&book_date='+date);
}
function Book_Confirm(date, week, crs, name, time, amt, self) {
 location.replace('/reserve01.asp?' + new URLSearchParams({proc_div:'B',book_date:date,
 book_week:week,book_crs:crs,book_crs_name:name,book_time:time,green_amt:amt,self_div:self})+'#go_focus');
}
</script>NOTICE'''.replace('TIMES', times).replace('CONFIRM', confirm).replace('NOTICE', notice)
        data = page.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class BrowserNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), PageHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new')
        cls.driver = webdriver.Chrome(options=options)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.driver.get(f'http://127.0.0.1:{self.server.server_port}/reserve01.asp')
        self.logs = []
        self.bot = app_module.CastlexBot(threading.Event(), self.logs.append)
        self.bot.driver = self.driver
        self.bot.wait = WebDriverWait(self.driver, 5)
        self.bot._reserve_ready = True

    def test_full_navigation_and_same_date_reload(self):
        for _ in range(2):
            self.bot.select_date_js('20261020')
            self.assertIsNone(self.driver.execute_script('return window.__castlexChanged'))
            self.assertEqual(len(self.bot.get_available_slots('20261020')), 1)

    def test_confirmation_navigation_preserves_seven_arguments(self):
        self.bot.select_date_js('20261020')
        slot = self.bot.get_available_slots('20261020')[0]
        self.assertTrue(self.bot.select_time_js(slot))
        params = parse_qs(urlsplit(self.driver.current_url).query, keep_blank_values=True)
        for key, value in zip(('book_date', 'book_week', 'book_crs', 'book_crs_name',
                               'book_time', 'green_amt', 'self_div'), slot):
            self.assertEqual(params[key], [value])

    def test_wrong_navigation_target_not_accepted(self):
        self.bot.select_date_js('20261020')
        self.bot._expected_params['book_date'] = '20261031'
        self.assertFalse(self.bot._panel_changed(self.driver))

    def test_empty_page_records_site_notice(self):
        self.bot.select_date_js('20261031')
        self.assertEqual(self.bot.get_available_slots('20261031'), [])
        self.assertTrue(any('12:00' in log for log in self.logs))

    def test_date_notice_does_not_abort_navigation(self):
        self.bot.select_date_js('20261013')
        self.assertEqual(len(self.bot.get_available_slots('20261013')), 1)

    def test_confirmation_page_notice_does_not_abort_navigation(self):
        self.bot.select_date_js('20261013')
        slot = self.bot.get_available_slots('20261013')[0]
        self.assertTrue(self.bot.select_time_js(slot))


if __name__ == '__main__':
    unittest.main()
