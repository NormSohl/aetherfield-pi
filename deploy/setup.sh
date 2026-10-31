#!/usr/bin/env bash
# Sets up a Raspberry Pi 3 (Raspberry Pi OS Lite, 64-bit) as the air quality logger and display.
#   sudo ./deploy/setup.sh <monitor-host> ["Display name"]   install or update everything
#   sudo ./deploy/setup.sh <monitor-host> --no-screen        logger and web server only
# <monitor-host> is airgradient_<serial>.local, or an IP address.
# Safe to run again: it updates the app, keeps the data and any edits to /etc/default/aetherfield.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
[[ -n "${1:-}" ]] || { sed -n 2,6p "$0" >&2; exit 1; }
cd "$(dirname "$0")/.."

HOST=$1
NAME="Air Quality"
SCREEN=1
if [[ "${2:-}" == "--no-screen" ]]; then SCREEN=0; elif [[ -n "${2:-}" ]]; then NAME=$2; fi
USER_NAME=${SUDO_USER:-pi}
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)

apt-get update
apt-get install -y python3 curl avahi-daemon libnss-mdns
if (( SCREEN )); then
  if apt-cache show chromium-browser >/dev/null 2>&1; then BROWSER=chromium-browser; else BROWSER=chromium; fi
  apt-get install -y --no-install-recommends cage "$BROWSER"
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

echo
echo "Logger running. Check it:"
echo "  curl -s localhost:8080/api/current"
echo "  systemctl status aetherfield"
echo "From anywhere on the LAN: http://$(hostname).local:8080"
(( SCREEN )) && echo "Reboot to start the display: sudo reboot"
exit 0
