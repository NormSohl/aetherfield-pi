#!/usr/bin/env bash
# Sets up a Raspberry Pi 3 (Raspberry Pi OS Lite, 64-bit) as the air quality logger and display.
#   sudo ./deploy/setup.sh [monitor] ["Display name"]   install or update everything
#   sudo ./deploy/setup.sh [monitor] --no-screen        logger and web server only
# [monitor] is "auto" to find it on the network (the default), airgradient_<serial>.local,
# or an IP address.
# Safe to run again: it updates the app, keeps the data and any edits to /etc/default/aetherfield.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
cd "$(dirname "$0")/.."

HOST=${1:-auto}
NAME="Air Quality"
SCREEN=1
if [[ "${2:-}" == "--no-screen" ]]; then SCREEN=0; elif [[ -n "${2:-}" ]]; then NAME=$2; fi
USER_NAME=${SUDO_USER:-pi}
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)

apt-get update
apt-get install -y python3 curl avahi-daemon avahi-utils libnss-mdns
if (( SCREEN )); then
  # Older Pi OS calls it chromium-browser. Where both exist, that name is the stale one.
  if apt-cache show chromium >/dev/null 2>&1; then BROWSER=chromium; else BROWSER=chromium-browser; fi
  apt-get install -y --no-install-recommends cage "$BROWSER"
fi

# An existing settings file wins below, so only a first install needs the monitor.
if [[ $HOST == auto && ! -f /etc/default/aetherfield ]]; then
  HOST=$(deploy/find-monitor)
  echo "Using monitor $HOST"
fi

install -d /opt/aetherfield
cp -R app static /opt/aetherfield/
if [[ ! -f /etc/default/aetherfield ]]; then
  sed -e "s|__HOST__|$HOST|" -e "s|__NAME__|\"$NAME\"|" deploy/aetherfield.default > /etc/default/aetherfield
fi
install -m 644 deploy/aetherfield.service /etc/systemd/system/aetherfield.service

# The logger won't record until network time has answered: a Pi has no battery clock.
timedatectl set-ntp true

install -d /etc/systemd/journald.conf.d
install -m 644 deploy/journald-aetherfield.conf /etc/systemd/journald.conf.d/aetherfield.conf
systemctl restart systemd-journald

systemctl daemon-reload
systemctl enable aetherfield
systemctl restart aetherfield

if (( SCREEN )); then
  install -m 755 deploy/aetherfield-kiosk /usr/local/bin/aetherfield-kiosk
  raspi-config nonint do_boot_behaviour B2   # Console auto-login.
  PROFILE="$USER_HOME/.bash_profile"
  LINE='[[ "$(tty)" == /dev/tty1 ]] && exec /usr/local/bin/aetherfield-kiosk'
  if ! grep -qsF "$LINE" "$PROFILE"; then
    # .profile is skipped once .bash_profile exists, so keep it running.
    { [[ -f "$PROFILE" ]] || echo '[[ -f ~/.profile ]] && source ~/.profile'; echo "$LINE"; } >> "$PROFILE"
    chown "$USER_NAME": "$PROFILE"
  fi
fi

# Appliance settings: no automatic updates, unused services off, firewall on.
"$(pwd)/deploy/harden.sh"

echo
echo "Logger running. Check it:"
echo "  curl -s localhost:8080/api/current"
echo "  systemctl status aetherfield"
echo "From anywhere on the LAN: http://$(hostname).local:8080"
(( SCREEN )) && echo "Reboot to start the display: sudo reboot"
exit 0
