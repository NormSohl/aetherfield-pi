"""`python3 -m app`: runs the poller and the web server in one process."""

import os
import signal
import threading

from .poller import Poller
from .store import Store
from .web import make_server


def flag(name, default):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def main():
    host = os.environ.get("AG_HOST", "").strip()
    if not host:
        raise SystemExit("Set AG_HOST to the monitor, e.g. airgradient_d83bda1a0f70.local")

    config = {
        "host": host,
        "name": os.environ.get("AG_NAME", "Air Quality"),
        "bind": os.environ.get("AG_BIND", "0.0.0.0"),
        "port": int(os.environ.get("AG_PORT", "8080")),
        "fahrenheit": flag("AG_FAHRENHEIT", "true"),
        "use_compensated": flag("AG_USE_COMPENSATED", "true"),
    }

    store = Store(os.environ.get("AG_DB", "aetherfield.sqlite3"))
    poller = Poller(
        store,
        host,
        interval=int(os.environ.get("AG_POLL_SECONDS", "60")),
        clock_file=os.environ.get("AG_CLOCK_FILE", ""),
    )
    server = make_server(store, poller, config)

    def shut_down(*_):
        # shutdown() waits for serve_forever, so it can't run on this thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shut_down)
    signal.signal(signal.SIGINT, shut_down)

    thread = threading.Thread(target=poller.run, daemon=True)
    thread.start()
    print("Serving on {bind}:{port}, polling {host}".format(**config), flush=True)
    server.serve_forever()

    poller.stop()
    thread.join(timeout=10)
    store.close()  # The clean-shutdown flush: nothing buffered is lost on a reboot.


if __name__ == "__main__":
    main()
