"""`python3 -m app`: runs the pollers and the web server in one process."""

import os
import signal
import threading

from .fleet import Fleet
from .web import make_server


def flag(name, default):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def monitor_names(text):
    """`AG_MONITOR_NAMES`: "<serial>=Booth,<serial>=Spray Hall". The screen's own
    Rename wins over these."""
    pairs = (item.split("=", 1) for item in text.split(",") if "=" in item)
    return {serial.strip().lower(): name.strip() for serial, name in pairs}


def main():
    host = os.environ.get("AG_HOST", "").strip()
    if not host:
        raise SystemExit("Set AG_HOST to the monitor, e.g. airgradient_d83bda1a0f70.local")

    config = {
        "bind": os.environ.get("AG_BIND", "0.0.0.0"),
        "port": int(os.environ.get("AG_PORT", "8080")),
        "fahrenheit": flag("AG_FAHRENHEIT", "true"),
        "use_compensated": flag("AG_USE_COMPENSATED", "true"),
    }

    fleet = Fleet(
        host,
        os.environ.get("AG_DB", "aetherfield.sqlite3"),
        interval=int(os.environ.get("AG_POLL_SECONDS", "60")),
        clock_file=os.environ.get("AG_CLOCK_FILE", ""),
        names=monitor_names(os.environ.get("AG_MONITOR_NAMES", "")),
    )

    def shut_down(*_):
        # shutdown() waits for serve_forever, so it can't run on this thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    # A clean exit is also how a new room monitor applies: systemd starts us again.
    server = make_server(fleet, config, restart=shut_down)

    signal.signal(signal.SIGTERM, shut_down)
    signal.signal(signal.SIGINT, shut_down)

    fleet.start()
    print("Serving on {bind}:{port}, polling {host}".format(host=fleet.home.host, **config), flush=True)
    server.serve_forever()

    fleet.stop()  # Includes the final flush: nothing buffered is lost on a reboot.


if __name__ == "__main__":
    main()
