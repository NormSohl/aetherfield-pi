# Aetherfield Pi

An untended kiosk for a room with spray painting and resin printing. A Raspberry
Pi 3 logs an AirGradient ONE to its SD card and shows it on an attached screen.

This started from the design and air quality logic of the
[Aetherfield](https://github.com/NormSohl/AirGradient-to-iOS) iPad app, but it is
its own project and doesn't track that app.

- The screen needs no input: a status banner, then VOC, PM2.5 and CO₂ with a week
  of history each, plus temperature and humidity.
- Polls the monitor's local API once a minute, and never faster. No account, no cloud.
- Keeps every minute sample in one SQLite file. Downloads as CSV at `/api/export.csv`.
- Serves the dashboard on port 8080, so anything on the LAN can open it too.
- Runs on the Python standard library. The only extras are a browser and the
  small compositor that runs it full screen.

## Install

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. In its
   settings set the hostname to `aetherfield`, your Wi-Fi, and SSH on. The Pi 3
   only has 2.4 GHz Wi-Fi.
2. From the Mac:

   ```sh
   rsync -a --exclude .git ~/projects/aetherfield-pi/ aetherfield.local:aetherfield-pi/
   ssh aetherfield.local
   ```

3. On the Pi:

   ```sh
   sudo aetherfield-pi/deploy/setup.sh airgradient_d83bda1a0f70.local "Living Room"
   sudo reboot
   ```

Run the same two steps to update. Data and settings are kept.

With no screen attached, add `--no-screen` in place of the display name.

Settings live in `/etc/default/aetherfield`: monitor address, name, port, poll
interval, °F or °C, and compensated or raw readings.

Screens: anything HDMI or the official DSI touchscreen. The layout is tested from
800x480 to 1080p. Small GPIO/SPI hats aren't supported: they don't appear as a
normal display.

## The hidden detail view

Double-click anywhere (a double-tap works too) for every metric and Day, Week,
Month and Year charts. There is no visible control. Double-click again to leave,
or leave it: the kiosk returns to the room view after 3 minutes with no input.
A browser on the LAN can open it directly at `/?view=detail`.

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
python3 -m unittest tests.test_logger
node --test tests/metrics.test.mjs
```

## Moving the data

The database is `/var/lib/aetherfield/aetherfield.sqlite3`, about 50 MB a year.
The card is the one copy, so take a CSV now and then, or copy the file while the
service is stopped.
