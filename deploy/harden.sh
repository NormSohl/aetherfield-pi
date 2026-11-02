#!/usr/bin/env bash
# Trims the Pi down to an appliance: no automatic updates, no services the room
# doesn't use, fewer card writes, and nothing listening that it doesn't need.
#   sudo ./deploy/harden.sh
# setup.sh runs this; it is safe to run again on its own. See README, "Updates".
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
cd "$(dirname "$0")/.."

have_unit() { systemctl list-unit-files --no-legend "$1" 2>/dev/null | grep -q .; }

# --- No automatic updates -----------------------------------------------------
# Pi OS Lite doesn't install upgrades on its own, but the apt timers still wake
# to refresh package lists, and unattended-upgrades may have been added. A kiosk
# should only change when someone updates it on purpose.
if dpkg -s unattended-upgrades >/dev/null 2>&1; then
  apt-get purge -y unattended-upgrades
fi
for unit in apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service man-db.timer; do
  if have_unit "$unit"; then
    systemctl disable --now "$unit" 2>/dev/null || true
    systemctl mask "$unit"
  fi
done

# --- Services the room doesn't use ---------------------------------------------
# Keep avahi-daemon (the monitor is found by its .local name), systemd-timesyncd
# (recording waits on network time), NetworkManager/wpa_supplicant and ssh.
for unit in bluetooth.service hciuart.service triggerhappy.service triggerhappy.socket \
            ModemManager.service rpi-connect.service rpi-connect-wayvnc.service; do
  if have_unit "$unit"; then
    systemctl disable --now "$unit" 2>/dev/null || true
    systemctl mask "$unit"
  fi
done

# Bluetooth off in hardware too. Wi-Fi shares the chip and is unaffected.
CONFIG=/boot/firmware/config.txt
[[ -f $CONFIG ]] || CONFIG=/boot/config.txt
if [[ -f $CONFIG ]] && ! grep -qx 'dtoverlay=disable-bt' "$CONFIG"; then
  printf '\n# Aetherfield: no Bluetooth\ndtoverlay=disable-bt\n' >> "$CONFIG"
fi

# --- Card wear -------------------------------------------------------------------
# Older images swap to a file on the card. Swap to compressed RAM instead: the
# 1 GB Pi 3 needs some swap for Chromium, but not on the SD card. Newer images
# already use zram and have no dphys-swapfile.
if dpkg -s dphys-swapfile >/dev/null 2>&1; then
  apt-get install -y zram-tools
  sed -i -e 's/^#\?ALGO=.*/ALGO=zstd/' -e 's/^#\?PERCENT=.*/PERCENT=50/' /etc/default/zramswap
  systemctl enable --now zramswap
  dphys-swapfile swapoff || true
  systemctl disable --now dphys-swapfile
  dphys-swapfile uninstall || true
fi

# --- Wi-Fi reliability -------------------------------------------------------------
# Power saving on the Pi 3's Wi-Fi drops the link now and then on a box nobody
# is watching.
if [[ -d /etc/NetworkManager/conf.d ]]; then
  printf '[connection]\nwifi.powersave = 2\n' > /etc/NetworkManager/conf.d/aetherfield-wifi.conf
fi

# --- SSH ---------------------------------------------------------------------------
# Keys only, but only once a key is installed, so this can never lock you out.
USER_NAME=${SUDO_USER:-pi}
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
install -d /etc/ssh/sshd_config.d
if [[ -s "$USER_HOME/.ssh/authorized_keys" ]]; then
  printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' \
    > /etc/ssh/sshd_config.d/aetherfield.conf
  SSH_NOTE="SSH: keys only."
else
  printf 'PermitRootLogin no\n' > /etc/ssh/sshd_config.d/aetherfield.conf
  SSH_NOTE="SSH: still accepts passwords. Copy a key (ssh-copy-id $USER_NAME@$(hostname).local) and run this again."
fi
systemctl reload ssh 2>/dev/null || true

# --- Firewall ------------------------------------------------------------------------
# Inbound: SSH, the dashboard port, mDNS, DHCP and ping. Everything else is dropped.
PORT=8080
if [[ -f /etc/default/aetherfield ]]; then
  PORT=$(. /etc/default/aetherfield; echo "${AG_PORT:-8080}")
fi
apt-get install -y nftables
cat > /etc/nftables.conf <<EOF
#!/usr/sbin/nft -f
# Written by aetherfield-pi deploy/harden.sh. Rerun it after changing AG_PORT.
flush ruleset
table inet filter {
  chain input {
    type filter hook input priority filter; policy drop;
    iif lo accept
    ct state established,related accept
    ct state invalid drop
    meta l4proto { icmp, ipv6-icmp } accept
    tcp dport { 22, $PORT } accept
    udp dport 5353 accept comment "mDNS"
    udp sport 67 udp dport 68 accept comment "DHCPv4"
    udp dport 546 accept comment "DHCPv6"
  }
  chain forward {
    type filter hook forward priority filter; policy drop;
  }
  chain output {
    type filter hook output priority filter; policy accept;
  }
}
EOF
nft -c -f /etc/nftables.conf
systemctl enable nftables
systemctl restart nftables

echo "Hardened: automatic updates off, unused services masked, firewall on (22, $PORT)."
echo "$SSH_NOTE"
echo "Bluetooth and swap changes take effect after a reboot."
