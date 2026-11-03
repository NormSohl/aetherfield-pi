"""What the settings screen shows about this Pi's connection. Read-only."""

import os
import re
import socket
import subprocess

NMCLI_TIMEOUT = 5


def address():
    # Connecting a UDP socket sends nothing: it only makes the OS pick a route.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
    except OSError:
        return None


def wired():
    try:
        with open("/sys/class/net/eth0/carrier") as handle:
            return handle.read().strip() == "1"
    except OSError:
        return False


def parse_wifi(output):
    """`nmcli -t` lines are colon-separated, with colons in a name escaped."""
    for line in output.splitlines():
        fields = re.split(r"(?<!\\):", line)
        if len(fields) == 3 and fields[0] == "*":
            signal = fields[2]
            return {
                "name": fields[1].replace("\\:", ":").replace("\\\\", "\\"),
                "signal": int(signal) if signal.isdigit() else None,
            }
    return None


def wifi():
    command = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL", "device", "wifi", "list", "--rescan", "no"]
    try:
        output = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=NMCLI_TIMEOUT,
            universal_newlines=True,
            errors="replace",
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_wifi(output)


def info():
    return {
        "hostname": socket.gethostname().split(".")[0],
        "address": address(),
        "wired": wired(),
        "wifi": wifi(),
    }
