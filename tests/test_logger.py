"""Run with: python3 -m unittest tests.test_logger"""

import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from app import poller as poller_module
from app import reading
from app.poller import Poller
from app.store import Store
from app.web import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "local-current.json")
NOW = 1_800_000_000


def sample(**values):
    return values


class ReadingTests(unittest.TestCase):
    def test_real_payload(self):
        with open(FIXTURE) as handle:
            values, device = reading.parse(json.load(handle))
        self.assertEqual(values["rco2"], 484.33)
        self.assertEqual(values["pm02Compensated"], 2.04)
        self.assertEqual(device["model"], "I-9PSL")

    def test_missing_is_none_never_zero(self):
        values, _ = reading.parse({"rco2": None, "pm02": 0})
        self.assertIsNone(values["rco2"])
        self.assertIsNone(values["atmp"])
        self.assertEqual(values["pm02"], 0.0)  # A real zero stays zero.

    def test_lenient_numbers(self):
        self.assertEqual(reading.number("12.5"), 12.5)
        self.assertIsNone(reading.number("n/a"))
        self.assertIsNone(reading.number(True))
        self.assertIsNone(reading.number(float("nan")))
        self.assertIsNone(reading.number(float("inf")))

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            reading.parse([1, 2])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "t.sqlite3")
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def on_card(self):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        finally:
            db.close()

    def test_samples_reach_the_card_only_on_flush(self):
        self.store.add(NOW, sample(rco2=500))
        self.assertEqual(self.on_card(), 0)
        self.store.flush()
        self.assertEqual(self.on_card(), 1)

    def test_history_sees_unflushed_and_flushed_samples(self):
        self.store.add(NOW - 300, sample(rco2=500))
        self.store.flush()
        self.store.add(NOW - 60, sample(rco2=700))
        history = self.store.history("day", NOW)
        self.assertEqual(len(history["rows"]), 2)

    def test_absent_sensor_stays_absent_through_a_bucket(self):
        self.store.add(NOW - 60, sample(rco2=None, pm02=4))
        self.store.add(NOW - 61, sample(rco2=None, pm02=6))
        self.store.flush()
        history = self.store.history("month", NOW)
        row = dict(zip(history["fields"], history["rows"][-1]))
        self.assertIsNone(row["rco2"])
        self.assertEqual(row["pm02"], 5)

    def test_average_skips_nulls_rather_than_counting_zero(self):
        self.store.add(NOW - 60, sample(rco2=800))
        self.store.add(NOW - 61, sample(rco2=None))
        self.store.flush()
        history = self.store.history("month", NOW)
        row = dict(zip(history["fields"], history["rows"][-1]))
        self.assertEqual(row["rco2"], 800)

    def test_an_hour_split_across_flushes_is_not_an_average_of_averages(self):
        hour = NOW // 3600 * 3600
        for i in range(3):
            self.store.add(hour + i, sample(rco2=100))
        self.store.flush()
        self.store.add(hour + 3, sample(rco2=500))
        self.store.flush()
        history = self.store.history("month", hour + 60)
        row = dict(zip(history["fields"], history["rows"][-1]))
        self.assertEqual(row["rco2"], 200)
        self.assertEqual(row["n"], 4)

    def test_rollup_is_rebuilt_for_a_database_that_lacks_one(self):
        self.store.add(NOW, sample(rco2=500))
        self.store.close()
        db = sqlite3.connect(self.path)
        db.execute("DROP TABLE hourly")
        db.commit()
        db.close()
        self.store = Store(self.path)
        self.assertEqual(len(self.store.history("year", NOW + 1)["rows"]), 1)

    def test_week_keeps_the_worst_minute_of_each_bucket(self):
        bucket_start = NOW // 900 * 900
        for i, voc in enumerate((100, 100, 400)):
            self.store.add(bucket_start + i * 60, sample(tvocIndex=voc))
        history = self.store.history("week", bucket_start + 300)
        row = dict(zip(history["fields"], history["rows"][-1]))
        self.assertEqual(row["tvocIndex"], 200)
        self.assertEqual(row["peak_tvocIndex"], 400)

    def test_empty_buckets_are_absent(self):
        self.store.add(NOW - 3 * 3600, sample(rco2=500))
        self.store.add(NOW - 60, sample(rco2=500))
        self.assertEqual(len(self.store.history("day", NOW)["rows"]), 2)

    def test_range_excludes_older_samples(self):
        self.store.add(NOW - 2 * 86400, sample(rco2=500))
        self.assertEqual(self.store.history("day", NOW)["rows"], [])
        self.assertEqual(len(self.store.history("week", NOW)["rows"]), 1)

    def test_latest_prefers_the_newest_of_either_table(self):
        self.assertIsNone(self.store.latest())
        self.store.add(NOW - 60, sample(rco2=500))
        self.store.flush()
        self.assertEqual(self.store.latest()[0], NOW - 60)
        self.store.add(NOW, sample(rco2=600))
        self.assertEqual(self.store.latest()[1]["rco2"], 600)

    def test_export_covers_both_tables_in_order_across_batches(self):
        self.store.add(NOW - 2, sample(rco2=1))
        self.store.flush()
        self.store.add(NOW - 1, sample(rco2=2))
        self.store.add(NOW, sample(rco2=3))
        rows = [row for batch in self.store.export(batch=2) for row in batch]
        self.assertEqual([row[0] for row in rows], [NOW - 2, NOW - 1, NOW])

    def test_samples_survive_a_reopen(self):
        self.store.add(NOW, sample(rco2=500))
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.latest()[1]["rco2"], 500)


class PollerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, "t.sqlite3"))
        self.clock = os.path.join(self.dir.name, "synchronized")

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_failure_keeps_the_last_reading_and_records_nothing(self):
        poller = Poller(self.store, "x", 60)
        with mock.patch.object(poller_module, "fetch", return_value={"rco2": 500}):
            self.assertTrue(poller.poll_once())
        with mock.patch.object(poller_module, "fetch", side_effect=OSError("down")):
            self.assertFalse(poller.poll_once())
        state = poller.snapshot()
        self.assertEqual(state["error"], "Can't reach the monitor.")
        self.assertEqual(state["values"]["rco2"], 500)
        self.assertEqual(len(self.store.history("day", state["ts"] + 1)["rows"]), 1)

    def test_sensors_are_never_polled_faster_than_once_a_minute(self):
        self.assertEqual(Poller(self.store, "x", 10).interval, 60)
        self.assertEqual(Poller(self.store, "x", 300).interval, 300)

    def test_garbage_is_an_error_not_a_crash(self):
        poller = Poller(self.store, "x", 60)
        with mock.patch.object(poller_module, "fetch", return_value="nope"):
            self.assertFalse(poller.poll_once())

    def test_no_recording_until_the_clock_is_set(self):
        poller = Poller(self.store, "x", 60, clock_file=self.clock)
        with mock.patch.object(poller_module, "fetch", return_value={"rco2": 500}):
            poller.poll_once()
            self.assertIsNone(self.store.latest())
            self.assertEqual(poller.snapshot()["values"]["rco2"], 500)  # Tiles still live.
            self.assertFalse(poller.snapshot()["clockSet"])
            open(self.clock, "w").close()
            poller.poll_once()
        self.assertEqual(self.store.latest()[1]["rco2"], 500)

    def test_tiles_are_restored_after_a_restart(self):
        self.store.add(NOW, sample(rco2=612))
        self.assertEqual(Poller(self.store, "x", 60).snapshot()["values"]["rco2"], 612)


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.store = Store(os.path.join(cls.dir.name, "t.sqlite3"))
        cls.store.add(NOW, sample(rco2=500))
        poller = Poller(cls.store, "monitor.local", 60)
        config = {
            "host": "monitor.local",
            "name": "Test",
            "bind": "127.0.0.1",
            "port": 0,
            "fahrenheit": True,
            "use_compensated": True,
        }
        cls.server = make_server(cls.store, poller, config)
        cls.base = "http://127.0.0.1:{}".format(cls.server.server_address[1])
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.store.close()
        cls.dir.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_current(self):
        status, body = self.get("/api/current")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["reading"]["rco2"], 500)

    def test_every_static_file_exists(self):
        for path in ("/", "/style.css", "/metrics.js", "/chart.js", "/app.js", "/icon.png", "/fonts/nunito.woff2"):
            self.assertEqual(self.get(path)[0], 200, path)

    def test_paths_never_reach_the_filesystem(self):
        for path in ("/../app/web.py", "/..%2f..%2fetc%2fpasswd", "/fonts/../index.html"):
            self.assertEqual(self.get(path)[0], 404, path)

    def test_unknown_range_is_refused(self):
        self.assertEqual(self.get("/api/history?range=forever")[0], 400)

    def test_csv_export(self):
        status, body = self.get("/api/export.csv")
        lines = body.decode().splitlines()
        self.assertEqual(status, 200)
        self.assertTrue(lines[0].startswith("timestamp,pm01"))
        self.assertTrue(lines[1].startswith("2027-01-15T08:00:00Z"))


if __name__ == "__main__":
    unittest.main()
