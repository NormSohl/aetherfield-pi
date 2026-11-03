"""Every monitor on the network, each with its own poller and SQLite file.

The monitor on screen is `home`: it is set at install or on the settings screen.
Names belong to monitors, not places: these move around a shop, so the screen says
which device it's showing, and a name follows its monitor. Others are logged as they turn up, from mDNS, and
stay until removed. A monitor that vanishes must read as "no data", never be
replaced by the next to answer. Nothing here ever deletes readings: removing a
monitor sets its file aside, and it picks up again if the monitor returns.

A choice made on the screen lives in `settings.json` beside the databases, because
the service can't write /etc/default. It wins over `AG_HOST`. History belongs to
the monitor, not the room, so changing rooms mixes nothing.

mDNS adverts come from anything on the LAN, so only a well-formed name gets as far
as a file path or a URL, and `MAX_OTHERS` bounds what a flood of them can cost.
"""

import glob
import json
import os
import re
import sqlite3
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

# What fits under the gear.
MAX_NAME = 24

# A reading older than this is not "now". The page's STALE_AFTER is the same.
STALE_AFTER = 300

_HOSTNAME = re.compile(r"airgradient_([0-9a-f]{6,32})\.local", re.IGNORECASE)
_FILENAME = re.compile(r"monitor-([0-9a-f]{6,32})\.sqlite3")
_SERIAL = re.compile(r"[0-9a-f]{6,32}")
_SQLITE_SUFFIXES = ("", "-wal", "-shm")


def serial_of(host):
    match = _HOSTNAME.fullmatch(host.strip())
    return match.group(1).lower() if match else None


def valid_name(name):
    return isinstance(name, str) and len(name) <= MAX_NAME and all(ord(c) >= 32 for c in name)


def hostname_of(serial):
    return "airgradient_{}.local".format(serial)


def browse():
    """The serial of every monitor advertising on this network."""
    command = ["avahi-browse", "-rpt", "_airgradient._tcp"]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=SCAN_TIMEOUT,
            universal_newlines=True,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print("avahi-browse failed: {}".format(error), flush=True)
        return set()
    if result.returncode:
        print("avahi-browse failed: {}".format(result.stderr.strip()), flush=True)
    found = set()
    for line in result.stdout.splitlines():
        fields = line.split(";")
        if fields[0] == "=" and len(fields) > 6:
            found.add(serial_of(fields[6]))
    return found - {None}


class Monitor:
    def __init__(self, monitor_id, host, path, store, poller):
        self.id = monitor_id
        self.host = host
        self.path = path
        self.store = store
        self.poller = poller
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.poller.run, daemon=True)
        self.thread.start()


class Fleet:
    def __init__(self, host, db_path, interval=60, clock_file="", names=None, find=browse):
        self._folder = os.path.dirname(db_path) or "."
        self._interval = interval
        self._clock_file = clock_file
        self._names = names or {}
        self._find = find
        self._lock = threading.Lock()
        self._scan_lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False
        self.found = None  # Serials seen on the network by the last scan.
        self._settings = self._load()
        if self._settings.get("home"):
            self._adopt(db_path, serial_of(host) or self._settings.get("was"))
            host = hostname_of(self._settings["home"])
            db_path = self._path(self._settings["home"])
        self.home = self._open(HOME, host, db_path)
        self._monitors = {HOME: self.home}
        self._scanner = threading.Thread(target=self._run, daemon=True)

    def _path(self, serial):
        return os.path.join(self._folder, "monitor-{}.sqlite3".format(serial))

    def _settings_path(self):
        return os.path.join(self._folder, "settings.json")

    def _load(self):
        try:
            with open(self._settings_path()) as handle:
                saved = json.load(handle)
        except (OSError, ValueError):
            return {}
        if not isinstance(saved, dict):
            return {}
        settings = {
            key: saved[key]
            for key in ("home", "was")
            if isinstance(saved.get(key), str) and _SERIAL.fullmatch(saved[key])
        }
        names = saved.get("names")
        if isinstance(names, dict):
            settings["names"] = {
                serial: name
                for serial, name in names.items()
                if _SERIAL.fullmatch(serial) and valid_name(name)
            }
        return settings

    def _save(self):
        temporary = self._settings_path() + ".tmp"
        with open(temporary, "w") as handle:
            json.dump(self._settings, handle)
        os.replace(temporary, self._settings_path())

    def serial(self, monitor):
        return self.home_serial() if monitor is self.home else monitor.id

    def name_of(self, monitor):
        serial = self.serial(monitor)
        if not serial:
            return "AirGradient"
        saved = self._settings.get("names", {}).get(serial)
        return saved or self._names.get(serial) or "AirGradient " + serial[-4:]

    def rename(self, monitor, name):
        """An empty name goes back to the default. False if it can't be saved."""
        serial = self.serial(monitor)
        if not serial:
            return False
        with self._lock:
            names = self._settings.setdefault("names", {})
            if name:
                names[serial] = name
            else:
                names.pop(serial, None)
            self._save()
        return True

    def _adopt(self, db_path, serial):
        # The file `AG_DB` names holds the install's monitor. Once another is
        # chosen it becomes an ordinary monitor, under its own name.
        if not serial or os.path.exists(self._path(serial)) or not os.path.exists(db_path):
            return
        self._move(db_path, self._path(serial))

    def _open(self, monitor_id, host, path):
        store = Store(path)
        poller = Poller(store, host, self._interval, clock_file=self._clock_file)
        return Monitor(monitor_id, host, path, store, poller)

    def get(self, monitor_id):
        with self._lock:
            return self._monitors.get(monitor_id)

    def all(self):
        """The one on screen first, then the others by name."""
        with self._lock:
            others = [m for m in self._monitors.values() if m is not self.home]
        return [self.home] + sorted(others, key=lambda m: self.name_of(m).lower())

    def _saved(self):
        # Seen before and known by their files, so one that's off today still
        # shows its history after a restart.
        paths = glob.glob(os.path.join(glob.escape(self._folder), "monitor-*.sqlite3"))
        matches = (_FILENAME.fullmatch(os.path.basename(path)) for path in paths)
        return {match.group(1) for match in matches if match}

    def home_serial(self):
        serial = serial_of(self.home.host) or self.home.poller.snapshot()["device"].get("serialno")
        return serial.lower() if serial else None

    def scan(self):
        with self._scan_lock:
            self.found = set(self._find())
            home = self.home_serial()
            if not home:
                return  # An address that hasn't answered: anything found might be it.
            for serial in sorted((self._saved() | self.found) - {home}):
                if self.get(serial) is None:
                    self._add(serial)

    def choose_room(self, monitor):
        """Saves `monitor` as this room's. Applied by a restart, which the
        caller arranges: every poller and file is simply reopened."""
        with self._lock:
            was = self.home_serial()
            self._settings["home"] = monitor.id
            if was:
                self._settings["was"] = was
            self._save()

    def forget(self, monitor):
        """Takes another monitor off the list and stops polling it. Its file is
        kept, under a name the startup scan skips."""
        with self._scan_lock:
            with self._lock:
                self._monitors.pop(monitor.id, None)
            monitor.poller.stop()
            if monitor.thread:
                monitor.thread.join(timeout=10)
            try:
                monitor.store.close()
            except sqlite3.Error as error:
                print("closing {} failed: {}".format(monitor.id, error), flush=True)
            self._move(monitor.path, self._set_aside(monitor.id))

    def _set_aside(self, serial):
        return os.path.join(self._folder, "removed-{}.sqlite3".format(serial))

    @staticmethod
    def _move(source, target):
        for suffix in _SQLITE_SUFFIXES:
            if os.path.exists(source + suffix):
                os.replace(source + suffix, target + suffix)

    def _add(self, serial):
        with self._lock:
            if len(self._monitors) > MAX_OTHERS:
                print("ignoring monitor {}: already logging the most".format(serial), flush=True)
                return
        if not os.path.exists(self._path(serial)):
            self._move(self._set_aside(serial), self._path(serial))  # It's back.
        monitor = self._open(
            serial,
            hostname_of(serial),
            self._path(serial),
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
            # The clean-shutdown flush. One bad file must not cost the others theirs.
            try:
                monitor.store.close()
            except sqlite3.Error as error:
                print("closing {} failed: {}".format(monitor.id, error), flush=True)

    def summary(self, monitor, now):
        state = monitor.poller.snapshot()
        return {
            "id": monitor.id,
            "serial": self.serial(monitor),
            "name": self.name_of(monitor),
            "home": monitor is self.home,
            "live": bool(state["ts"]) and not state["error"] and now - state["ts"] <= STALE_AFTER,
        }
