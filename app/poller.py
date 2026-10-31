"""Polls the monitor once a minute and hands samples to the store."""

import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request

from . import reading
from .store import FLUSH_SECONDS

# A monitor that has dropped off the Wi-Fi must fail fast: this timeout is what
# the poll cadence actually depends on.
REQUEST_TIMEOUT = 6


def fetch(host):
    url = "http://{}/measures/current".format(host)
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def describe(error):
    if isinstance(error, urllib.error.HTTPError) and error.code == 404:
        return "Not found. This usually means older firmware: 3.0.10+ serves /measures/current."
    if isinstance(error, urllib.error.HTTPError):
        return "The monitor answered with HTTP {}.".format(error.code)
    if isinstance(error, (urllib.error.URLError, OSError)):
        return "Can't reach the monitor."
    return "The monitor sent something unreadable."


class Poller:
    def __init__(self, store, host, interval, clock_file=""):
        self.store = store
        self.host = host
        self.interval = interval
        self.clock_file = clock_file
        self._lock = threading.Lock()
        self._state = {"ts": None, "values": None, "device": {}, "error": None}
        self._stop = threading.Event()
        restored = store.latest()
        if restored:
            self._state["ts"], self._state["values"] = restored

    def clock_is_set(self):
        """A Pi has no battery clock. Until NTP answers it runs from the time
        of its last shutdown, and samples stamped then would land in the past
        and overwrite real ones. Live tiles are fine; recording has to wait."""
        return not self.clock_file or os.path.exists(self.clock_file)

    def snapshot(self):
        with self._lock:
            return dict(self._state, clockSet=self.clock_is_set())

    def poll_once(self):
        try:
            values, device = reading.parse(fetch(self.host))
        except (OSError, ValueError, http.client.HTTPException) as error:
            with self._lock:
                self._state["error"] = describe(error)
            return False

        now = int(time.time())
        if self.clock_is_set():
            self.store.add(now, values)
        with self._lock:
            self._state.update(
                ts=now,
                values=values,
                device=dict(self._state["device"], **device),
                error=None,
            )
        return True

    def run(self):
        next_flush = time.monotonic() + FLUSH_SECONDS
        while not self._stop.is_set():
            started = time.monotonic()
            # A full or failing card must not stop the display. Samples stay in
            # memory and the next flush tries again.
            try:
                self.poll_once()
                if time.monotonic() >= next_flush:
                    self.store.flush()
                    next_flush = time.monotonic() + FLUSH_SECONDS
            except Exception as error:
                print("poll failed: {}".format(error), flush=True)
            self._stop.wait(max(0, self.interval - (time.monotonic() - started)))

    def stop(self):
        self._stop.set()
