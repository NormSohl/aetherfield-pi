"""Fills a database with a deterministic year of minute samples, for looking at
the charts and timing queries without waiting a year. Not used in production.

    python3 tests/seed_demo.py demo.sqlite3
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import Store  # noqa: E402

DAY = 86400


def values(ts):
    # A pure function of the clock, with a story in it (as in Aetherfield's
    # DemoSource): CO2 climbing while the room is shut, and a spray session
    # every few days. Band colouring shows nothing if everything is green.
    hour = (ts % DAY) / 3600
    night = max(0, math.cos((hour - 4) / 24 * 2 * math.pi))
    session = math.exp(-(((hour - 22) / 0.4) ** 2)) if (ts // DAY) % 3 == 0 else 0
    wobble = math.sin(ts / 1711) + math.sin(ts / 4177)
    pm = 3 + 1.2 * wobble + 42 * session
    return {
        "pm01": pm * 0.7,
        "pm02": pm,
        "pm02Compensated": pm * 0.9,
        "pm10": pm * 1.2,
        "rco2": 520 + 620 * night + 25 * wobble,
        "atmp": 20.5 + 1.5 * math.sin(ts / DAY * 2 * math.pi),
        "rhum": 48 + 5 * math.sin(ts / 30000),
        "tvocIndex": 95 + 300 * session + 8 * wobble,
        "noxIndex": 1 + 30 * session,
        "wifi": -60,
    }


def main(path):
    store = Store(path)
    now = int(time.time())
    # Holes on purpose: a one-off outage, so the chart has a real gap to show.
    for i, ts in enumerate(range(now - 365 * DAY, now, 60)):
        if now - 14 * 3600 < ts < now - 11 * 3600:
            continue
        store.add(ts, values(ts))
        if i % 5000 == 0:
            store.flush()
    store.close()


if __name__ == "__main__":
    main(sys.argv[1])
