# Aetherfield Pi

An untended kiosk for a room with spray painting and resin printing. A Raspberry
Pi 3 logs an AirGradient ONE to its SD card and shows it on an attached screen.

The story of the project, with photos: [An air quality screen for the Seattle Makers
spray room](https://www.sohl.com/2026/11/07/aetherfield-pi/) on sohl.com.

This started from the design and air quality logic of the
[Aetherfield](https://github.com/NormSohl/AirGradient-to-iOS) iPad app, but it is
its own project and doesn't track that app.

- The screen needs no input: a status banner, then VOC, PM2.5 and CO₂ with a week
  of history each, plus temperature and humidity.
- Polls the monitor's local API once a minute, and never faster. No account, no cloud.
- Logs any other AirGradient monitors on the network too, each in its own history.
- Keeps every minute sample in SQLite. Downloads as CSV at `/api/export.csv`.
- Serves the dashboard on port 8080, so anything on the LAN can open it too.
- Runs on the Python standard library. The only extras are a browser and the
  small compositor that runs it full screen.

## Install

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. In its
   settings set the hostname to `aetherfield`, the username `pi`, a password, your
   Wi-Fi, and SSH on. The Pi 3 only has 2.4 GHz Wi-Fi.
2. From the Mac:

   ```sh
   rsync -a --exclude .git ~/projects/aetherfield-pi/ pi@aetherfield.local:aetherfield-pi/
   ssh pi@aetherfield.local
   ```

3. On the Pi:

   ```sh
   sudo aetherfield-pi/deploy/setup.sh auto
   sudo reboot
   ```

`auto` finds the monitor on the network, and asks if there are several. It uses
mDNS, which stays on one network, so if the Pi and the monitor are on separate
ones (a guest or IoT Wi-Fi), pass the monitor's address in place of `auto`.

Run the same two steps to update. Data and settings are kept.

For a change to `app/` or `static/` there's a quicker way, which needs no password
or reboot. After the rsync above:

```sh
ssh pi@aetherfield.local sudo aetherfield-update
```

Changes to `deploy/` still need `setup.sh`.

## Updates and hardening

Setup also runs `deploy/harden.sh`, which makes the Pi an appliance that only
changes when someone changes it:

- **No automatic updates.** The apt timers are masked and `unattended-upgrades`
  is removed, so nothing downloads or installs on its own.
- **Unused services off:** Bluetooth (also disabled in `config.txt`),
  triggerhappy, ModemManager and Raspberry Pi Connect, where present.
  avahi, time sync, Wi-Fi and SSH stay on.
- **Less card wear:** swap moves from a file on the card to compressed RAM on
  images that still use a swap file.
- **Wi-Fi power saving off**, so the link doesn't drop on an untended box.
- **SSH keys only**, once a key is in `~/.ssh/authorized_keys`. Without one,
  passwords still work, so you can't be locked out. Add a key with
  `ssh-copy-id pi@aetherfield.local` and run setup again.
- **Firewall:** inbound is SSH, the dashboard port, mDNS, DHCP and ping only.
  Change `AG_PORT` and run setup again to move it.

Updating the OS is now a manual job. A few times a year:

```sh
ssh pi@aetherfield.local
sudo apt update && sudo apt full-upgrade -y && sudo reboot
```

Then check the screen comes back. Keep a copy of a known-good SD card image so a
bad update is a reflash, not a rebuild.

With no screen attached, add `--no-screen` after `auto`.

Settings live in `/etc/default/aetherfield`: monitor address, port, poll
interval, °F or °C, and compensated or raw readings.

Screen: the official 7-inch touchscreen (800x480, here in a SmartiPi Touch), or an
HDMI panel, landscape. Larger panels scale with the screen's height; checked at
800x480, 1366x768 and 1080p. Without jumper wires between the display board and the
Pi's GPIO pins, the display needs its own 5V supply, and the Pi's USB ports won't do.

## The detail view

Double-tap anywhere, or choose All readings and history in settings, for every
metric and Day, Week, Month and Year charts. Tap the X to leave, or leave it: the
kiosk returns to the room view after 3 minutes with no input.
A browser on the LAN can open it directly at `/?view=detail`.

## Settings

The gear at the top right opens settings. Nothing here needs a keyboard:

- **Air monitors:** every AirGradient found, with its status. **Show** puts one on
  screen, and the screen comes back a few seconds later. **Rename** gives one a name.
  **Remove** takes one that isn't answering off the list. **Search** looks for
  monitors now, rather than waiting up to 5 minutes.
- **All readings and history:** the detail view.
- **Network:** this Pi's name, address, Wi-Fi network and signal.

Nothing on the screen deletes readings. Remove sets a monitor's file aside, and it
picks up where it left off if that monitor returns. Those two actions take a second
tap on the same button. A browser elsewhere on the LAN can look at settings but not
change them: that takes the screen itself.

**Change Wi-Fi** lists nearby networks. Tap one, type its password on the on-screen
keyboard, and tap Connect. It takes up to half a minute. If it fails, the attempt is
removed and the Pi goes back to the network it was on. Joined networks stay saved,
so the Pi can move between them. It joins networks with a shared password, or none.
Ones needing a personal login are listed but can't be chosen, and a network with a
sign-in page won't work. There's no PIN, so anyone at the screen can change this.
Setup installs a polkit rule that lets the logger do this, and nothing else as root.

To add a network without the screen:

```sh
sudo nmcli connection add type wifi con-name NAME ifname wlan0 ssid "NETWORK" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "PASSWORD" connection.autoconnect yes
```

The screen shows the device it's tracking, because these move around: a name
belongs to its air monitor and follows it, and a new one reads "AirGradient" and
the end of its serial. The choice and the names are saved in
`/var/lib/aetherfield/settings.json`, and the choice wins over `AG_HOST`. Delete that
file and restart to go back to `AG_HOST`.

## Other monitors

The main view only ever shows the air monitor chosen for it. Any others on the
network are found within 5 minutes and logged every minute from then on, whether
or not they're on screen, up to 7 of them, with no setup. Each monitor keeps its
own history, which stays with it if it changes role.

With more than one, the detail view has a row of monitors to tap, greyed when one
has no recent data. Choosing another shows "Not the main air monitor", and leaving
the view, or the 3-minute timeout, returns to the main one.

One CSV per monitor: `/api/export.csv?monitor=<serial>`.

## What the screen can't tell you

"Readings normal" describes these sensors, not the safety of the room.

- The VOC index is relative. It re-centres on the last day or so of air, so fumes
  that linger for days drift back toward 100 and look normal. It shows change, not
  concentration.
- The monitor doesn't detect isocyanates, which two-part paints and clears can
  carry. A calm screen says nothing about them, so keep using the respirator.
- Overspray can foul the particle sensor's optics. If PM2.5 reads high or stuck
  with nothing going on, suspect the sensor.

## Running it elsewhere

```sh
AG_HOST=airgradient_d83bda1a0f70.local AG_BIND=127.0.0.1 python3 -m app   # http://localhost:8080
python3 tests/seed_demo.py demo.sqlite3                                   # a synthetic year
AG_HOST=… AG_DB=demo.sqlite3 python3 -m app                               # charts with data in them
```

## Tests

```sh
python3 -m unittest tests.test_logger tests.test_find_monitor
node --test tests/metrics.test.mjs tests/keyboard.test.mjs
```

## Moving the data

The database is `/var/lib/aetherfield/aetherfield.sqlite3`, about 50 MB a year.
The card is the one copy, so take a CSV now and then, or copy the file while the
service is stopped.
