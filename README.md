# Aetherfield Pi

An untended kiosk for a room with spray painting and resin printing. A Raspberry
Pi 3 logs an AirGradient ONE to its SD card and shows it on an attached screen.

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
   sudo aetherfield-pi/deploy/setup.sh auto "Spray Room"
   sudo reboot
   ```

`auto` finds the monitor on the network, and asks if there are several. It uses
mDNS, which stays on one network, so if the Pi and the monitor are on separate
ones (a guest or IoT Wi-Fi), pass the monitor's address in place of `auto`.

Run the same two steps to update. Data and settings are kept.

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

With no screen attached, add `--no-screen` in place of the display name.

Settings live in `/etc/default/aetherfield`: monitor address, name, port, poll
interval, °F or °C, and compensated or raw readings.

Screen: an HDMI panel of 11 inches or larger, landscape. The layout scales with the
screen's height, so it fills the panel the same way at any resolution; checked at
1366x768 and 1080p.

## The hidden detail view

Double-click anywhere (a double-tap works too) for every metric and Day, Week,
Month and Year charts. There is no visible control. Double-click again to leave,
or leave it: the kiosk returns to the room view after 3 minutes with no input.
A browser on the LAN can open it directly at `/?view=detail`.

## Other monitors

The monitor chosen at install is this room's, and it's the only one the room view
ever shows. Any others on the network are found within 5 minutes and logged from
then on, up to 7 of them, with no setup.

With more than one, the hidden detail view has a row of monitors to click, greyed
when one has no recent data. Choosing another shows "Not this room's monitor", and
leaving the view, or the 3-minute timeout, returns to this room's.

They're named "Monitor" and the end of their serial. To name them, set
`AG_MONITOR_NAMES` in `/etc/default/aetherfield` (there's an example there) and
restart. One CSV per monitor: `/api/export.csv?monitor=<serial>`. A monitor stays
listed once seen; to retire one, stop the service and delete its
`/var/lib/aetherfield/monitor-<serial>.sqlite3`.

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
node --test tests/metrics.test.mjs
```

## Moving the data

The database is `/var/lib/aetherfield/aetherfield.sqlite3`, about 50 MB a year.
The card is the one copy, so take a CSV now and then, or copy the file while the
service is stopped.
