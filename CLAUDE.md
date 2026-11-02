# CLAUDE.md

A Raspberry Pi 3 logger and untended kiosk for an AirGradient ONE, in a room with
spray painting and resin printing. See README.md for what it does and how to
install it. This file records why it is the way it is.

## Status

Verified on a Mac against the real monitor (firmware 3.7.0), and by screenshot at
1366x768 and 1080p. **Nothing in `deploy/` has run on a Pi yet**, so
`setup.sh`, the systemd unit, cage + Chromium and the clock check are all
unproven until it does.

## Layout

```
app/      reading (lenient parse), store (SQLite), poller, fleet, web, __main__
static/   index.html, style.css, metrics.js (pure, tested), chart.js (SVG), app.js
deploy/   setup.sh, find-monitor, harden.sh, systemd unit, kiosk script, journald drop-in
tests/    test_logger.py, metrics.test.mjs, seed_demo.py, fixtures/ (real response)
```

Python stays 3.9-compatible and standard-library only. Pi OS has no reason to
need a venv or pip for this.

## Origin

This began from the Aetherfield iPad app (`~/Claude Code/AirGradient-to-iOS`), and
`static/metrics.js` started as a port of its `Metric.swift` and
`SeriesShaping.swift`. That repo's CLAUDE.md explains the reasoning behind each
rule, so it's worth reading. This is still an independent project: there is no
shared code, no dependency, and no duty to keep the two in step. Change anything
here to suit this room. References run one way, from here back to Aetherfield:
never edit that repo from work on this one, or add anything to it about this one.

Rules inherited from it that still hold: missing is "—" and never 0, EPA 2024 PM2.5
breakpoints, VOC/NOx are indices, temperature is judged in Celsius, band runs fold
by sample count.

## The screen

**Nothing day to day may depend on input.** The overview in `app.js` is the screen:
status banner, then VOC, PM2.5 and CO₂ over a week. The tiles are the hidden
detail view, reached by double-click. On the kiosk it times out back to
the overview, so nothing left open can strand the screen.

- **"Normal", never "safe".** The sensors can't justify the word. See README.
- **Stale data must not look live.** A failed monitor, a dead logger or a reading
  over 5 minutes old turns the banner to "no data" and blanks the numbers. The
  worst failure here is a frozen green screen.
- **Week charts plot each 15-minute bucket's worst minute**, not its average. A
  20-minute spray session is the event the chart exists for.
- **VOC is `calm: 1` in `WATCHED`.** Its tile uses the standard bands, but the
  banner ignores the 101-150 band, since the index sits around 100 by design and
  sensor noise would keep crossing that edge.
- **The panel is 11 inches or larger, and sizes come from screen height.** Type and
  chart padding are in `vh` (and `vh()` in `chart.js`), never px: 1080p on 11 inches
  is about 190 PPI, so px sizes that suit a monitor are too small across a room.
- **Chart scales have a `floor`**, so a quiet week looks quiet.

## Load-bearing decisions

- **Sensors are read at most once a minute.** `MIN_INTERVAL` overrides the config.
- **Writes are batched.** Samples sit in an in-memory table and reach the card
  every 5 minutes, or on a clean shutdown. A power cut loses at most that. Queries
  read both tables, so charts never wait on a flush.
- **Month and Year read `hourly`.** Averaging a year of minutes took 494 ms on an
  M-series Mac while holding the one lock, every minute; a Pi 3 is far slower.
  The rollup took it to 12 ms. Each flush recomputes whole hours from `samples`,
  so a split hour is never an average of averages. `hourly` is derived: drop it
  and it rebuilds on start.
- **Nothing is aged out.** 50 MB a year is nothing, and the raw record is the point.
- **Year is one point a day.** At 6-hour buckets the daily CO2 cycle drew as a
  solid block on an 800-wide panel.
- **No recording until NTP has answered.** A Pi has no battery clock; it boots at
  its last shutdown time, and those stamps would overwrite real samples. The
  check is `/run/systemd/timesync/synchronized`, not `time-sync.target`, so a boot
  with no internet still shows live tiles. The page says when it isn't recording.
- **Static files are an allowlist.** The server listens on the LAN; no client path
  touches the filesystem.
- **One room's monitor, any number logged.** `home` is fixed at install, by
  `deploy/find-monitor` or by hand, and stored by hostname: that is
  `airgradient_<serial>.local`, so it is the serial, and `.local` resolves afresh on
  every poll. `app/fleet.py` logs the others it finds over mDNS, each with its own
  poller and `monitor-<serial>.sqlite3`, so nothing in the store knows about rooms.
  Discovery never changes which monitor is `home`: one that vanishes must read as
  "no data", not get replaced by whichever answers next.
- **mDNS adverts are untrusted.** Anything on the LAN can send one, so only a name
  matching `airgradient_<hex>.local` reaches a file path or a URL, and `MAX_OTHERS`
  bounds what a flood can cost in threads and card writes.
- **Viewing another monitor is a hidden-view thing only.** Leaving that view, by
  double-click or timeout, always returns to `home`, and the page drops everything
  from the old monitor first: another room's green must never pass for this one.
  The choice lives in the page, not the server, which stays GET-only.
- **The kiosk starts from console auto-login**, which gives cage a logind seat
  without any root service. Its browser profile is in RAM, for card wear and to
  avoid the restore-pages bubble.
- **The Pi never updates itself** (`deploy/harden.sh`, run by setup). A kiosk that
  changes on its own can break unseen, and updates were reported as constant.
  The trade is a tight footprint: masked apt timers, unused services masked,
  nftables allowing only 22, `AG_PORT`, mDNS, DHCP and ping, and SSH keys only
  once a key exists (never before, so it can't lock anyone out). Keep
  avahi-daemon and timesyncd: discovery and the clock check depend on them.
  Swap goes to zram, not off: Chromium on 1 GB needs some. OS updates are manual.
- **The kiosk page reloads at 04:00.** Insurance against a slow leak in a browser
  that never closes on 1 GB of RAM.

## Testing notes

`.local` lookups take about 5 s per request from Python on macOS, so the first
poll looks stalled. Headless Chrome's `--window-size` resizes at capture, which
leaves the chart drawn too short: screenshot inside a fixed-size iframe instead.
