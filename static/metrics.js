// What the numbers mean, starting from Aetherfield's Metric.swift and
// SeriesShaping.swift. Pure functions, so tests/metrics.test.mjs can run this
// file without a browser. Decisions to preserve:
//   - A missing measurement stays null and renders "—", never 0.
//   - PM2.5 uses the EPA's 2024 breakpoints ("Good" ends at 9.0, not 12.0).
//   - VOC and NOx are Sensirion indices; a steady 100 is normal.
//   - Temperature is judged in Celsius whatever unit it's displayed in.
//   - Band colouring folds short runs by sample count, never by a fraction of
//     the span, or sharp spikes get painted the colour of the calm around them.

export const BANDS = [
  { id: "good", label: "Good", short: "Good" },
  { id: "moderate", label: "Moderate", short: "Moderate" },
  { id: "sensitive", label: "Unhealthy for sensitive groups", short: "Sensitive" },
  { id: "unhealthy", label: "Unhealthy", short: "Unhealthy" },
  { id: "very", label: "Very unhealthy", short: "Very bad" },
  { id: "hazardous", label: "Hazardous", short: "Hazardous" },
];

const PM25 = [
  [0.0, 9.0, 0, 50],
  [9.1, 35.4, 51, 100],
  [35.5, 55.4, 101, 150],
  [55.5, 125.4, 151, 200],
  [125.5, 225.4, 201, 300],
  [225.5, 325.4, 301, 500],
];

const PM10 = [
  [0, 54, 0, 50],
  [55, 154, 51, 100],
  [155, 254, 101, 150],
  [255, 354, 151, 200],
  [355, 424, 201, 300],
  [425, 604, 301, 500],
];

function interpolate(c, table) {
  if (c <= 0) return 0;
  for (const [lo, hi, aqiLo, aqiHi] of table) {
    if (c <= hi) return ((aqiHi - aqiLo) * (c - lo)) / (hi - lo) + aqiLo;
  }
  return 500;
}

// Truncated first, because that is the EPA's own procedure, and because the
// table has deliberate gaps (9.0 then 9.1) a raw sensor value can land inside.
export const aqiFromPm25 = (c) => interpolate(Math.floor(c * 10 + 1e-9) / 10, PM25);
export const aqiFromPm10 = (c) => interpolate(Math.floor(c), PM10);

const steps = (limits) => (v) => {
  const i = limits.findIndex((limit) => v < limit);
  return i === -1 ? limits.length : i;
};

const bandOfAqi = steps([51, 101, 151, 201, 301]);
const bandOfCo2 = steps([800, 1000, 1500, 2000, 3000]);
const bandOfIndex = steps([101, 151, 201, 301, 401]);

const bandOfTempC = (c) => (c >= 18 && c <= 25 ? 0 : c >= 15 && c <= 28 ? 1 : 2);
const bandOfHumidity = (h) => (h >= 30 && h <= 60 ? 0 : h >= 20 && h <= 70 ? 1 : 2);

const round0 = (v) => v.toFixed(0);
const pmFormat = (v) => (v < 10 ? v.toFixed(1) : v.toFixed(0));

const pm25Of = (r, s) => (s.useCompensated ? r.pm02Compensated ?? r.pm02 : r.pm02) ?? null;
const pm10Of = (r) => r.pm10 ?? null;

function aqiOf(r, s) {
  // The worst sub-index, as AirNow reports it: one bad pollutant is what you
  // breathe, not diluted by a clean one.
  const pm25 = pm25Of(r, s);
  const pm10 = pm10Of(r);
  if (pm25 === null && pm10 === null) return null;
  return Math.max(
    pm25 === null ? -Infinity : aqiFromPm25(pm25),
    pm10 === null ? -Infinity : aqiFromPm10(pm10)
  );
}

function tempOf(r, s) {
  const c = (s.useCompensated ? r.atmpCompensated ?? r.atmp : r.atmp) ?? null;
  if (c === null) return null;
  return s.fahrenheit ? (c * 9) / 5 + 32 : c;
}

export const METRICS = [
  { id: "aqi", title: "AQI", icon: "gauge", unit: () => "", value: aqiOf, format: round0, band: bandOfAqi },
  {
    id: "pm25",
    title: "PM2.5",
    icon: "dots",
    unit: () => "µg/m³",
    value: pm25Of,
    format: pmFormat,
    band: (v) => bandOfAqi(aqiFromPm25(v)),
  },
  {
    id: "pm10",
    title: "PM10",
    icon: "dots",
    unit: () => "µg/m³",
    value: pm10Of,
    format: pmFormat,
    band: (v) => bandOfAqi(aqiFromPm10(v)),
  },
  {
    id: "pm01",
    title: "PM1",
    icon: "dots",
    unit: () => "µg/m³",
    value: (r) => r.pm01 ?? null,
    format: pmFormat,
    // No EPA scale for PM1; PM2.5's is the closest honest proxy.
    band: (v) => bandOfAqi(aqiFromPm25(v)),
  },
  { id: "co2", title: "CO₂", icon: "cloud", unit: () => "ppm", value: (r) => r.rco2 ?? null, format: round0, band: bandOfCo2 },
  {
    id: "temperature",
    title: "Temperature",
    icon: "thermometer",
    unit: (s) => (s.fahrenheit ? "°F" : "°C"),
    value: tempOf,
    format: (v) => v.toFixed(1),
    band: (v, s) => bandOfTempC(s.fahrenheit ? ((v - 32) * 5) / 9 : v),
  },
  { id: "humidity", title: "Humidity", icon: "drop", unit: () => "%", value: (r, s) => (s.useCompensated ? r.rhumCompensated ?? r.rhum : r.rhum) ?? null, format: round0, band: bandOfHumidity },
  { id: "tvoc", title: "VOC index", icon: "dots", unit: () => "", value: (r) => r.tvocIndex ?? null, format: round0, band: bandOfIndex },
  { id: "nox", title: "NOx index", icon: "wind", unit: () => "", value: (r) => r.noxIndex ?? null, format: round0, band: bandOfIndex },
];

// The three things spraying and resin move, in the order the kiosk stacks them.
// `floor` holds each chart's scale up, so a quiet week looks quiet instead of
// autoscaling sensor noise into drama. `calm` is the highest band that doesn't
// raise the banner: the VOC index hovers around 100 by design, so its first band
// edge at 101 is noise, and a banner that flips on noise stops being read.
export const WATCHED = [
  { id: "tvoc", floor: 200, calm: 1 },
  { id: "pm25", floor: 35 },
  { id: "co2", floor: 1000 },
];

// The room's state right now: worst band among the watched metrics, and which
// ones are off normal. Null when none of them has a reading. "Normal" describes
// these sensors and nothing more, so nothing here ever says "safe".
export function assess(reading, s) {
  const judged = WATCHED.map(({ id, calm = 0 }) => ({ metric: METRICS.find((m) => m.id === id), calm }))
    .map(({ metric, calm }) => ({ metric, calm, value: metric.value(reading, s) }))
    .filter(({ value }) => value !== null)
    .map(({ metric, calm, value }) => ({ title: metric.title, band: metric.band(value, s), calm }));
  if (judged.length === 0) return null;
  const off = judged.filter((j) => j.band > j.calm);
  const worst = Math.max(0, ...off.map((j) => j.band));
  const drivers = off.map((j) => j.title);
  return { worst, level: worst === 0 ? "normal" : worst === 1 ? "elevated" : "high", drivers };
}

// When the room last changed between normal and not, from oldest-first history
// rows. Null if it has been in its current state for all of them.
export function stateSince(rows, isNormal) {
  if (rows.length === 0) return null;
  const now = isNormal(rows[rows.length - 1]);
  for (let i = rows.length - 2; i >= 0; i -= 1) {
    if (isNormal(rows[i]) !== now) return rows[i + 1].t;
  }
  return null;
}

export function durationText(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

// Index of the unbroken stretch each point belongs to, so the line breaks
// where nothing was recorded instead of bridging the hole with a trend nobody
// observed. Buckets are only absent when they held no samples.
export function segments(times, spacing) {
  let segment = 0;
  return times.map((t, i) => {
    if (i > 0 && t - times[i - 1] > spacing * 3) segment += 1;
    return segment;
  });
}

// Mean over time, not samples: each recorded hour counts once, and an hour
// with no samples doesn't count, rather than counting as zero.
export function timeWeightedMean(points) {
  const hours = new Map();
  for (const { t, value } of points) {
    const hour = Math.floor(t / 3600);
    const entry = hours.get(hour) ?? { sum: 0, count: 0 };
    entry.sum += value;
    entry.count += 1;
    hours.set(hour, entry);
  }
  if (hours.size === 0) return null;
  let total = 0;
  for (const { sum, count } of hours.values()) total += sum / count;
  return total / hours.size;
}

// Runs of like-banded points, positioned 0...1 along the series.
export function bandRuns(points, maxRuns = 200) {
  if (points.length === 0) return [];
  const first = points[0].t;
  const span = points[points.length - 1].t - first;
  if (span <= 0) return [{ band: points[0].band, start: 0, end: 1 }];

  for (let minRun = 2; ; minRun *= 2) {
    const runs = [];
    let i = 0;
    while (i < points.length) {
      let j = i;
      while (j + 1 < points.length && points[j + 1].band === points[i].band) j += 1;
      const start = (points[i].t - first) / span;
      const end = (points[j].t - first) / span;
      if (j - i + 1 < minRun && runs.length > 0) {
        runs[runs.length - 1].end = end; // Absorb the blip.
      } else {
        runs.push({ band: points[i].band, start, end });
      }
      i = j + 1;
    }
    if (runs.length <= maxRuns || minRun > points.length) return runs;
  }
}
