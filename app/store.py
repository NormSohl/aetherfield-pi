"""The log: one SQLite file on the SD card, written gently.

New samples go to an in-memory table and reach the card every `FLUSH_SECONDS`.
That costs at most one flush interval of data on a power cut, and turns 1,440
commits a day into 288. Queries read both tables, so a chart never waits for a
flush. Nothing is ever averaged away or dropped: a year of minute samples is
about 50 MB, the card has room for decades.

Charts bucket at query time, except that averaging a year of minutes takes
seconds on a Pi 3 while holding the store's lock. So each flush also refreshes
`hourly`, a rollup the Month and Year charts read instead. Those two can lag the
newest samples by one flush, which nothing at their scale can show.
"""

import sqlite3
import threading

from .reading import FIELDS

FLUSH_SECONDS = 300

HOUR = 3600
DAY = 24 * HOUR

# Range -> (seconds shown, seconds per chart point). Buckets of an hour or more
# read `hourly`. Year is one point a day: finer than that, the daily CO2 cycle
# draws as a solid block on a small panel instead of a trend.
RANGES = {
    "day": (DAY, 120),
    "week": (7 * DAY, 900),
    "month": (30 * DAY, HOUR),
    "year": (365 * DAY, DAY),
}

# The kiosk's week charts plot the worst minute in each bucket: a 15-minute
# average would flatten the short spike a spray session makes, which is the
# thing the chart is there to show.
PEAK_FIELDS = ("pm02", "pm02Compensated", "rco2", "tvocIndex")

_COLUMNS = ", ".join(FIELDS)
_PEAKS = ", ".join("MAX({0})".format(name) for name in PEAK_FIELDS)
_MARKS = ", ".join("?" for _ in FIELDS)
_AVERAGES = ", ".join("AVG({0})".format(name) for name in FIELDS)
_REAL_COLUMNS = ", ".join(name + " REAL" for name in FIELDS)
_SCHEMA = "ts INTEGER PRIMARY KEY, " + _REAL_COLUMNS


class Store:
    def __init__(self, path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS samples ({})".format(_SCHEMA))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS hourly (ts INTEGER PRIMARY KEY, n INTEGER, {})".format(
                _REAL_COLUMNS
            )
        )
        if self._db.execute("SELECT 1 FROM hourly LIMIT 1").fetchone() is None:
            self._rollup(0)
        self._db.execute("ATTACH DATABASE ':memory:' AS mem")
        self._db.execute("CREATE TABLE mem.pending ({})".format(_SCHEMA))

    def _rollup(self, since):
        # Recomputed from the samples, whole hours at a time, so an hour split
        # across two flushes is averaged once rather than as an average of
        # averages.
        self._db.execute(
            "INSERT OR REPLACE INTO hourly SELECT ts / 3600 * 3600, COUNT(*), {} "
            "FROM samples WHERE ts >= ? GROUP BY ts / 3600".format(_AVERAGES),
            (since // 3600 * 3600,),
        )

    def add(self, ts, values):
        row = [int(ts)] + [values.get(name) for name in FIELDS]
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO mem.pending (ts, {}) VALUES (?, {})".format(
                    _COLUMNS, _MARKS
                ),
                row,
            )

    def flush(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                oldest = self._db.execute("SELECT MIN(ts) FROM mem.pending").fetchone()[0]
                self._db.execute("INSERT OR REPLACE INTO samples SELECT * FROM mem.pending")
                self._db.execute("DELETE FROM mem.pending")
                if oldest is not None:
                    self._rollup(oldest)
                self._db.execute("COMMIT")
            except sqlite3.Error:
                self._db.execute("ROLLBACK")
                raise

    def latest(self):
        """The newest sample as (ts, values), or None. Used to fill the tiles
        straight after a restart, before the first poll answers."""
        query = (
            "SELECT ts, {0} FROM (SELECT ts, {0} FROM mem.pending "
            "UNION ALL SELECT ts, {0} FROM (SELECT ts, {0} FROM samples ORDER BY ts DESC LIMIT 1)) "
            "ORDER BY ts DESC LIMIT 1"
        ).format(_COLUMNS)
        with self._lock:
            row = self._db.execute(query).fetchone()
        return (row[0], dict(zip(FIELDS, row[1:]))) if row else None

    def history(self, range_name, now):
        """One row per bucket that has samples; empty buckets stay absent.

        AVG skips NULLs and is NULL when a bucket has no values at all, so an
        absent sensor stays absent instead of pulling the average toward zero.
        """
        seconds, bucket = RANGES[range_name]
        start = now - seconds
        if bucket >= 3600:
            query = (
                "SELECT ts / :b * :b + :b / 2, SUM(n), {averages} FROM hourly "
                "WHERE ts >= :start GROUP BY ts / :b ORDER BY 1"
            ).format(averages=_AVERAGES)
            fields = ["t", "n"] + list(FIELDS)
        else:
            query = (
                "SELECT ts / :b * :b + :b / 2, COUNT(*), {averages}, {peaks} FROM ("
                "SELECT ts, {columns} FROM samples WHERE ts >= :start "
                "UNION ALL SELECT ts, {columns} FROM mem.pending WHERE ts >= :start"
                ") GROUP BY ts / :b ORDER BY 1"
            ).format(averages=_AVERAGES, peaks=_PEAKS, columns=_COLUMNS)
            fields = ["t", "n"] + list(FIELDS) + ["peak_" + name for name in PEAK_FIELDS]
        with self._lock:
            rows = self._db.execute(query, {"b": bucket, "start": start}).fetchall()
        return {
            "start": start,
            "now": now,
            "bucket": bucket,
            "fields": fields,
            "rows": [[round(v, 2) if isinstance(v, float) else v for v in row] for row in rows],
        }

    def export(self, batch=2000):
        """Every sample, oldest first, as a generator of row batches. Takes the
        lock per batch, so a full export can't stall the poller or the page."""
        last = -1
        while True:
            query = (
                "SELECT ts, {0} FROM (SELECT ts, {0} FROM samples WHERE ts > ? "
                "UNION ALL SELECT ts, {0} FROM mem.pending WHERE ts > ?) ORDER BY ts LIMIT ?"
            ).format(_COLUMNS)
            with self._lock:
                rows = self._db.execute(query, (last, last, batch)).fetchall()
            if not rows:
                return
            last = rows[-1][0]
            yield rows

    def close(self):
        self.flush()
        with self._lock:
            self._db.close()
