"""Every monitor on the network, each with its own poller and SQLite file.

The room's own monitor is `home`: it is set at install, and it is what the screen
shows. Others are logged as they turn up, from mDNS, and stay once seen. A monitor
that vanishes must read as "no data", never be replaced by the next to answer.

mDNS adverts come from anything on the LAN, so only a well-formed name gets as far
as a file path or a URL, and `MAX_OTHERS` bounds what a flood of them can cost.
"""

import glob
import os
import re
import subprocess
import threading

from .poller import Poller
from .store import Store

HOME = "home"

# A monitor plugged in later shows up within this.
SCAN_SECONDS = 300
SCAN_TIMEOUT = 20

# Each one is a thread, a database and more writes to the card.
MAX_OTHERS = 7

# A reading older than this is not "now". The page's STALE_AFTER is the same.
STALE_AFTER = 300

_HOSTNAME = re.compile(r"airgradient_([0-9a-f]{6,32})\.local", re.IGNORECASE)
_FILENAME = re.compile(r"monitor-([0-9a-f]{6,32})\.sqlite3")


def serial_of(host):
    match = _HOSTNAME.fullmatch(host.strip())
    return match.group(1).lower() if match else None


def browse():
    """The serial of every monitor advertising on this network."""
    command = ["avahi-browse", "-rpt", "_airgradient._tcp"]
    try:
        output = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=SCAN_TIMEOUT,
            universal_newlines=True,
            errors="replace",
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return set()  # No avahi here, or it's stuck: nothing new this round.
    found = set()
    for line in output.splitlines():
        fields = line.split(";")
        if fields[0] == "=" and len(fields) > 6:
            found.add(serial_of(fields[6]))
    return found - {None}


class Monitor:
    def __init__(self, monitor_id, name, host, store, poller):
        self.id = monitor_id
        self.name = name
        self.host = host
        self.store = store
        self.poller = poller
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.poller.run, daemon=True)
        self.thread.start()


class Fleet:
    def __init__(self, host, name, db_path, interval=60, clock_file="", names=None, find=browse):
        self._folder = os.path.dirname(db_path) or "."
        self._interval = interval
        self._clock_file = clock_file
        self._names = names or {}
        self._find = find
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False
        self.home = self._open(HOME, name, host, db_path)
        self._monitors = {HOME: self.home}
        self._scanner = threading.Thread(target=self._run, daemon=True)

    def _open(self, monitor_id, name, host, path):
        store = Store(path)
        poller = Poller(store, host, self._interval, clock_file=self._clock_file)
        return Monitor(monitor_id, name, host, store, poller)

    def get(self, monitor_id):
        with self._lock:
            return self._monitors.get(monitor_id)

    def all(self):
        """The room's monitor first, then the others by name."""
        with self._lock:
            others = [m for m in self._monitors.values() if m is not self.home]
        return [self.home] + sorted(others, key=lambda m: m.name.lower())

    def _saved(self):
        # Seen before and known by their files, so one that's off today still
        # shows its history after a restart.
        paths = glob.glob(os.path.join(glob.escape(self._folder), "monitor-*.sqlite3"))
        matches = (_FILENAME.fullmatch(os.path.basename(path)) for path in paths)
        return {match.group(1) for match in matches if match}

    def scan(self):
        home = serial_of(self.home.host) or self.home.poller.snapshot()["device"].get("serialno")
        if not home:
            return  # Home is an address that hasn't answered: anything found might be it.
        for serial in sorted((self._saved() | set(self._find())) - {home.lower()}):
            if self.get(serial) is None:
                self._add(serial)

    def _add(self, serial):
        with self._lock:
            if len(self._monitors) > MAX_OTHERS:
                print("ignoring monitor {}: already logging the most".format(serial), flush=True)
                return
        monitor = self._open(
            serial,
            self._names.get(serial, "Monitor " + serial[-4:]),
            "airgradient_{}.local".format(serial),
            os.path.join(self._folder, "monitor-{}.sqlite3".format(serial)),
        )
        with self._lock:
            self._monitors[serial] = monitor
            if self._started:
                monitor.start()

    def _run(self):
        while not self._stop.is_set():
            # Finding other monitors is a bonus: failing must not touch the room's.
            try:
                self.scan()
            except Exception as error:
                print("monitor scan failed: {}".format(error), flush=True)
            self._stop.wait(SCAN_SECONDS)

    def start(self):
        with self._lock:
            self._started = True
        self.home.start()
        self._scanner.start()

    def stop(self):
        self._stop.set()
        monitors = self.all()
        for monitor in monitors:
            monitor.poller.stop()
        for monitor in monitors:
            if monitor.thread:
                monitor.thread.join(timeout=10)
            monitor.store.close()  # The clean-shutdown flush.

    def summary(self, monitor, now):
        state = monitor.poller.snapshot()
        return {
            "id": monitor.id,
            "name": monitor.name,
            "home": monitor is self.home,
            "live": bool(state["ts"]) and not state["error"] and now - state["ts"] <= STALE_AFTER,
        }
