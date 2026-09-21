import importlib.util
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("castlex_app", Path(__file__).with_name("castlexseoul_v8.1.0.py"))
app_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_module)


class AppSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        for target, value in [("BASE_DIR", self.temp.name),
                              ("CONFIG_FILE", str(Path(self.temp.name) / "user_config.json")),
                              ("CREDENTIALS_FILE", str(Path(self.temp.name) / "credentials.enc.json"))]:
            patcher = patch.object(app_module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def create_app(self, config=None):
        with patch.object(app_module, "load_config", return_value=config or {}):
            return app_module.App(self.root)

    def test_old_config_defaults_and_both_date_formats(self):
        app = self.create_app({"prio": {"1": {"enabled": True, "date": "20261010", "time": "12:00"},
                                              "2": {"enabled": True, "date": "2026-10-11", "time": "12:30"}}})
        self.assertEqual(app._selected_time_strategy(), "nearest")
        self.assertEqual(app.time_offset_var.get(), "2")
        self.assertEqual(app.prio_date[0].get(), "2026-10-10")
        self.assertEqual(app.prio_date[1].get(), "2026-10-11")

    def test_five_minute_inputs_preserve_endpoints(self):
        times = app_module.build_time_options()
        self.assertEqual(times[0], "05:00")
        self.assertEqual(times[-1], "17:30")
        self.assertIn("12:20", times)
        self.assertIn("12:25", times)
        self.assertIn("12:40", times)
        self.assertEqual(len(times), len(set(times)))

    def test_settings_round_trip_and_run_config(self):
        app = self.create_app()
        app.id_var.set("test-user")
        app.pw_var.set("test-password")
        app.time_strategy_var.set(app_module.TIME_STRATEGIES["offset"])
        app.time_offset_var.set("3")
        app._on_strategy_change()
        self.assertEqual(str(app.offset_spin.cget("state")), "readonly")
        app.prio_time[0].set("12:25")
        app.prio_date[0].set_date("2026-10-10")
        app._save_ui_config()
        saved = app_module.load_config()
        self.assertEqual(saved["time_strategy"], "offset")
        self.assertEqual(saved["time_offset"], 3)
        self.assertEqual(saved["prio"]["1"]["time"], "12:25")
        self.assertNotIn("test-password", json.dumps(saved))
        run = app._build_run_config()
        self.assertEqual(run["time_strategy"], "offset")
        self.assertEqual(run["time_offset"], 3)
        self.assertEqual(run["priorities"][0], {"date": "20261010", "base_time": "12:25"})

    def test_log_is_persisted_and_secrets_redacted(self):
        app = self.create_app()
        app._log_secrets = ("fake-secret",)
        app.log("candidate 2: 1221 fake-secret")
        app._tick_log()
        log = Path(app.log_path).read_text(encoding="utf-8")
        self.assertIn("candidate 2: 1221 [REDACTED]", log)
        self.assertNotIn("fake-secret", log)

    def test_log_write_failure_does_not_stop_app(self):
        app = self.create_app()
        app.log_path = str(Path(self.temp.name) / "missing" / "log.txt")
        app.log("candidate 1")
        app._tick_log()
        self.assertIsNone(app.log_path)
        self.assertIn("candidate 1", app.log_text.get("1.0", "end"))

    def test_stop_does_not_allow_parallel_restart(self):
        app = self.create_app()
        app._set_running(True)
        app.on_stop()
        self.assertTrue(app.stop_event.is_set())
        self.assertEqual(str(app.btn_start.cget("state")), "disabled")

    def test_controls_fit_window(self):
        app = self.create_app()
        self.root.deiconify()
        self.root.update()
        for widget in (app.strategy_combo, app.offset_spin, app.btn_start, app.btn_stop):
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())
        self.assertLess(app.strategy_combo.winfo_rooty() + app.strategy_combo.winfo_height(),
                        app.btn_start.winfo_rooty())
        self.root.withdraw()


if __name__ == "__main__":
    unittest.main()
