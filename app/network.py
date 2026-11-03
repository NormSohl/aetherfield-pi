"""This Pi's connection, for the settings screen: what it is, and joining another.

A Wi-Fi password only ever reaches nmcli on stdin. On a command line it would show
in process listings, and in the text of any exception.
"""

import os
import re
import socket
import subprocess
import threading

NMCLI_TIMEOUT = 5
SCAN_TIMEOUT = 20
# How long nmcli waits for a network to accept us, then a margin for the call.
JOIN_WAIT = 30

INTERFACE = "wlan0"
PSK_FIELD = "802-11-wireless-security.psk"

_joining = threading.Lock()


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


def fields_of(line):
    """`nmcli -t` lines are colon-separated, with colons in a name escaped."""
    return [
        field.replace("\\:", ":").replace("\\\\", "\\")
        for field in re.split(r"(?<!\\):", line)
    ]


def parse_wifi(output):
    for line in output.splitlines():
        fields = fields_of(line)
        if len(fields) == 3 and fields[0] == "*":
            signal = fields[2]
            return {
                "name": fields[1],
                "signal": int(signal) if signal.isdigit() else None,
            }
    return None


def nmcli(arguments, timeout=NMCLI_TIMEOUT, stdin=None):
    """The command's output, or None if it failed."""
    try:
        result = subprocess.run(
            ["nmcli"] + arguments,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            universal_newlines=True,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def wifi():
    output = nmcli(["-t", "-f", "IN-USE,SSID,SIGNAL", "device", "wifi", "list", "--rescan", "no"])
    return None if output is None else parse_wifi(output)


def key_management(security):
    """nmcli's key-mgmt for a scan's SECURITY text: "" for open networks, and
    None for what a shared password can't join, like 802.1X."""
    words = security.split()
    if "802.1X" in words:
        return None
    if "WPA3" in words and "WPA2" not in words and "WPA1" not in words:
        return "sae"
    return "wpa-psk" if words else ""


def parse_networks(output):
    """One entry per name, strongest first. A name can have several access points."""
    networks = {}
    for line in output.splitlines():
        fields = fields_of(line)
        if len(fields) != 4 or not fields[1]:
            continue
        in_use, ssid, signal, security = fields
        strength = int(signal) if signal.isdigit() else 0
        known = networks.get(ssid)
        networks[ssid] = {
            "ssid": ssid,
            "signal": max(strength, known["signal"] if known else 0),
            "connected": in_use == "*" or bool(known and known["connected"]),
            "security": security,
            "open": not security.split(),
            "supported": key_management(security) is not None,
        }
    return sorted(networks.values(), key=lambda n: (not n["connected"], -n["signal"]))


def scan_wifi():
    command = ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"]
    output = nmcli(command, timeout=SCAN_TIMEOUT)
    return None if output is None else parse_networks(output)


def active_wifi():
    output = nmcli(["-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
    for line in (output or "").splitlines():
        fields = fields_of(line)
        if len(fields) == 2 and fields[1] == "802-11-wireless":
            return fields[0]
    return None


def valid_password(password):
    # What WPA allows: 8 to 63 printable ASCII characters. This also keeps a
    # line break out of what's written to nmcli.
    return 8 <= len(password) <= 63 and all(32 <= ord(c) < 127 for c in password)


def valid_ssid(ssid):
    return 0 < len(ssid.encode("utf-8")) <= 32 and all(ord(c) >= 32 for c in ssid)


def join(ssid, password, security):
    """Joins a network and saves it, or leaves things as they were. Returns
    "joined", "failed", "busy" or "invalid". Takes up to `JOIN_WAIT` seconds."""
    keys = key_management(security)
    if keys is None or not valid_ssid(ssid) or (keys and not valid_password(password)):
        return "invalid"
    if not _joining.acquire(blocking=False):
        return "busy"
    try:
        previous = active_wifi()
        name = "wifi-" + re.sub(r"[^A-Za-z0-9_-]", "_", ssid)
        if previous == name:
            return "joined"
        nmcli(["connection", "delete", name])  # An earlier try at the same network.
        add = ["connection", "add", "type", "wifi", "con-name", name, "ifname", INTERFACE]
        add += ["ssid", ssid, "connection.autoconnect", "no"]
        if keys:
            add += ["802-11-wireless-security.key-mgmt", keys]
        if nmcli(add) is None:
            return "failed"
        saved = True
        if keys:
            editor = "set {} {}\nsave persistent\nquit\n".format(PSK_FIELD, password)
            saved = nmcli(["connection", "edit", "id", name], stdin=editor) is not None
        up = ["--wait", str(JOIN_WAIT), "connection", "up", name]
        if saved and nmcli(up, timeout=JOIN_WAIT + 10) is not None:
            nmcli(["connection", "modify", name, "connection.autoconnect", "yes"])
            return "joined"
        nmcli(["connection", "delete", name])
        if previous:
            nmcli(["--wait", str(JOIN_WAIT), "connection", "up", previous], timeout=JOIN_WAIT + 10)
        return "failed"
    finally:
        _joining.release()


def info():
    return {
        "hostname": socket.gethostname().split(".")[0],
        "address": address(),
        "wired": wired(),
        "wifi": wifi(),
    }
