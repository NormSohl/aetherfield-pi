"""The internal web server: a JSON API and the dashboard page.

Anyone on the LAN can read. Changing anything takes a request from this machine,
which in practice is the kiosk's own browser: the makerspace's Wi-Fi must not be
able to swap the room's monitor.
"""

import csv
import io
import ipaddress
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import network
from .fleet import HOME
from .reading import FIELDS
from .store import RANGES

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

# An allowlist, not a directory mapping: this listens on the LAN, and no path a
# client sends ever reaches the filesystem.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/metrics.js": ("metrics.js", "text/javascript; charset=utf-8"),
    "/chart.js": ("chart.js", "text/javascript; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/keyboard.js": ("keyboard.js", "text/javascript; charset=utf-8"),
    "/icon.png": ("icon.png", "image/png"),
    "/fonts/nunito.woff2": ("fonts/nunito-latin-wght-normal.woff2", "font/woff2"),
}


# Actions carry a monitor id or a network name and password: this is plenty.
MAX_BODY = 1024


def make_handler(fleet, config, restart):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            try:
                if parts.path == "/api/monitors":
                    self._monitors()
                elif parts.path == "/api/settings":
                    self._settings()
                elif parts.path in ("/api/current", "/api/history", "/api/export.csv"):
                    monitor = fleet.get(query.get("monitor", [HOME])[0])
                    if monitor is None:
                        self._json({"error": "unknown monitor"}, status=404)
                    elif parts.path == "/api/current":
                        self._json(self._current(monitor))
                    elif parts.path == "/api/history":
                        self._history(monitor, query.get("range", ["day"])[0])
                    else:
                        self._export(monitor)
                elif parts.path in STATIC_FILES:
                    self._static(*STATIC_FILES[parts.path])
                else:
                    self._json({"error": "not found"}, status=404)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The viewer left. Nothing to tell them.

        def do_POST(self):
            try:
                if not self._is_local():
                    self._json({"error": "only the screen can change settings"}, status=403)
                    return
                body = self._body()
                if body is None:
                    self._json({"error": "bad request"}, status=400)
                elif urlsplit(self.path).path == "/api/settings/scan":
                    fleet.scan()
                    self._json({"found": len(fleet.found or ())})
                elif urlsplit(self.path).path == "/api/settings/wifi/scan":
                    self._json({"networks": network.scan_wifi()})
                elif urlsplit(self.path).path == "/api/settings/wifi/join":
                    self._join(body)
                else:
                    self._monitor_action(urlsplit(self.path).path, body.get("monitor"))
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _is_local(self):
            return ipaddress.ip_address(self.client_address[0]).is_loopback

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= MAX_BODY:
                    return None
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return None
            return body if isinstance(body, dict) else None

        def _join(self, body):
            ssid, password, security = (body.get(k, "") for k in ("ssid", "password", "security"))
            if not all(isinstance(value, str) for value in (ssid, password, security)):
                self._json({"error": "bad request"}, status=400)
                return
            result = network.join(ssid, password, security)
            self._json({"result": result}, status=400 if result == "invalid" else 200)

        def _monitor_action(self, path, monitor_id):
            monitor = fleet.get(monitor_id) if isinstance(monitor_id, str) else None
            if path not in ("/api/settings/room", "/api/settings/forget"):
                self._json({"error": "not found"}, status=404)
            elif monitor is None:
                self._json({"error": "unknown monitor"}, status=404)
            elif monitor is fleet.home:
                self._json({"error": "that is this room's monitor"}, status=400)
            elif path == "/api/settings/forget":
                fleet.forget(monitor)
                self._json({"ok": True})
            else:
                fleet.choose_room(monitor)
                self._json({"ok": True, "restarting": True})
                restart()

        def _monitors(self):
            now = int(time.time())
            self._json({"monitors": [fleet.summary(m, now) for m in fleet.all()]})

        def _settings(self):
            now = int(time.time())
            self._json(
                {
                    "editable": self._is_local(),
                    "monitors": [fleet.summary(m, now) for m in fleet.all()],
                    "found": None if fleet.found is None else len(fleet.found),
                    "network": network.info(),
                }
            )

        def _current(self, monitor):
            state = monitor.poller.snapshot()
            device = state["device"]
            return {
                "monitor": {
                    "id": monitor.id,
                    "name": monitor.name,
                    "host": monitor.host,
                    "serial": device.get("serialno"),
                    "model": device.get("model"),
                    "firmware": device.get("firmware"),
                },
                "settings": {
                    "fahrenheit": config["fahrenheit"],
                    "useCompensated": config["use_compensated"],
                },
                "ts": state["ts"],
                "reading": state["values"],
                "error": state["error"],
                "clockSet": state["clockSet"],
                "now": int(time.time()),
            }

        def _history(self, monitor, range_name):
            if range_name not in RANGES:
                self._json({"error": "unknown range"}, status=400)
                return
            self._json(monitor.store.history(range_name, int(time.time())))

        def _export(self, monitor):
            name = "aetherfield.csv" if monitor is fleet.home else "aetherfield-{}.csv".format(monitor.id)
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="{}"'.format(name))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self._csv_rows([("timestamp",) + FIELDS])
            for rows in monitor.store.export():
                self._csv_rows(
                    (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(row[0])),) + row[1:]
                    for row in rows
                )

        def _csv_rows(self, rows):
            text = io.StringIO()
            csv.writer(text).writerows(rows)
            self.wfile.write(text.getvalue().encode("utf-8"))

        def _static(self, name, content_type):
            with open(os.path.join(STATIC_DIR, name), "rb") as handle:
                body = handle.read()
            self._send(body, content_type)

        def _json(self, payload, status=200):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self._send(body, "application/json", status)

        def _send(self, body, content_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # The kiosk hits this every few seconds; the journal is on the card too.

    return Handler


def make_server(fleet, config, restart=lambda: None):
    server = ThreadingHTTPServer(
        (config["bind"], config["port"]), make_handler(fleet, config, restart)
    )
    server.daemon_threads = True
    return server
