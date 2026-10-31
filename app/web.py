"""The internal web server: a read-only JSON API and the dashboard page."""

import csv
import io
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

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
    "/icon.png": ("icon.png", "image/png"),
    "/fonts/nunito.woff2": ("fonts/nunito-latin-wght-normal.woff2", "font/woff2"),
}


def make_handler(store, poller, config):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            try:
                if parts.path == "/api/current":
                    self._json(self._current())
                elif parts.path == "/api/history":
                    self._history(query.get("range", ["day"])[0])
                elif parts.path == "/api/export.csv":
                    self._export()
                elif parts.path in STATIC_FILES:
                    self._static(*STATIC_FILES[parts.path])
                else:
                    self._json({"error": "not found"}, status=404)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The viewer left. Nothing to tell them.

        def _current(self):
            state = poller.snapshot()
            device = state["device"]
            return {
                "monitor": {
                    "name": config["name"],
                    "host": config["host"],
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

        def _history(self, range_name):
            if range_name not in RANGES:
                self._json({"error": "unknown range"}, status=400)
                return
            self._json(store.history(range_name, int(time.time())))

        def _export(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="aetherfield.csv"')
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self._csv_rows([("timestamp",) + FIELDS])
            for rows in store.export():
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


def make_server(store, poller, config):
    server = ThreadingHTTPServer((config["bind"], config["port"]), make_handler(store, poller, config))
    server.daemon_threads = True
    return server
