// Run with: node --test tests/metrics.test.mjs
// Cases are Aetherfield's own: a test that wouldn't fail if the bug came back
// is decoration.

import assert from "node:assert/strict";
import { test } from "node:test";

import { aqiFromPm10, aqiFromPm25, assess, bandRuns, durationText, METRICS, segments, stateSince, timeWeightedMean } from "../static/metrics.js";

const metric = (id) => METRICS.find((m) => m.id === id);
const settings = { fahrenheit: true, useCompensated: true };

test("PM2.5 uses the 2024 breakpoints", () => {
  assert.equal(metric("pm25").band(9.0, settings), 0);
  assert.equal(metric("pm25").band(9.1, settings), 1);
  assert.equal(metric("pm25").band(12.0, settings), 1);
});

test("a value inside a breakpoint gap is truncated first", () => {
  assert.equal(Math.round(aqiFromPm25(9.05)), 50);
  assert.equal(Math.round(aqiFromPm10(54.9)), 50);
});

test("truncation survives float error", () => {
  assert.equal(aqiFromPm25(35.4), 100);
});

test("AQI is the worst sub-index, and survives one missing input", () => {
  assert.equal(metric("aqi").value({ pm02: 2, pm10: 500 }, { useCompensated: false }), aqiFromPm10(500));
  assert.equal(metric("aqi").value({ pm02: 2 }, { useCompensated: false }), aqiFromPm25(2));
  assert.equal(metric("aqi").value({}, settings), null);
});

test("a missing measurement is null for every metric, never 0", () => {
  for (const m of METRICS) assert.equal(m.value({}, settings), null, m.id);
});

test("a real zero stays zero", () => {
  assert.equal(metric("pm01").value({ pm01: 0 }, settings), 0);
  assert.equal(metric("pm25").value({ pm02Compensated: 0, pm02: 5 }, settings), 0);
});

test("compensated falls back to raw on older firmware", () => {
  assert.equal(metric("pm25").value({ pm02: 5 }, settings), 5);
});

test("temperature is judged in Celsius", () => {
  assert.equal(metric("temperature").band(72, { fahrenheit: true }), 0);
  assert.equal(metric("temperature").band(72, { fahrenheit: false }), 2);
  assert.equal(metric("temperature").value({ atmp: 20 }, settings), 68);
});

test("a steady VOC index of 100 is normal", () => {
  assert.equal(metric("tvoc").band(100, settings), 0);
});

test("the room is normal only when every watched metric is", () => {
  assert.equal(assess({ tvocIndex: 100, pm02: 2, rco2: 500 }, { useCompensated: false }).level, "normal");
  const pm = assess({ tvocIndex: 100, pm02: 12, rco2: 500 }, { useCompensated: false });
  assert.equal(pm.level, "elevated");
  assert.deepEqual(pm.drivers, ["PM2.5"]);
  assert.equal(assess({ tvocIndex: 100, pm02: 40, rco2: 500 }, { useCompensated: false }).level, "high");
});

test("VOC noise around its baseline doesn't raise the banner, a real rise does", () => {
  const clean = { pm02: 2, rco2: 500 };
  assert.equal(assess({ ...clean, tvocIndex: 140 }, { useCompensated: false }).level, "normal");
  const voc = assess({ ...clean, tvocIndex: 220 }, { useCompensated: false });
  assert.equal(voc.level, "high");
  assert.deepEqual(voc.drivers, ["VOC index"]);
});

test("a dead sensor doesn't read as normal air, and none at all is no verdict", () => {
  assert.equal(assess({}, settings), null);
  assert.deepEqual(assess({ rco2: 1600 }, settings).drivers, ["CO₂"]);
});

test("stateSince finds the last change either way", () => {
  const rows = [{ t: 1, ok: true }, { t: 2, ok: false }, { t: 3, ok: true }, { t: 4, ok: true }];
  assert.equal(stateSince(rows, (r) => r.ok), 3);
  assert.equal(stateSince(rows.slice(0, 2), (r) => r.ok), 2);
  assert.equal(stateSince(rows.slice(2), (r) => r.ok), null);
});

test("durations read at a glance", () => {
  assert.equal(durationText(600), "10 min");
  assert.equal(durationText(5400), "1 h 30 min");
  assert.equal(durationText(190000), "2 d 4 h");
});

test("segments break at gaps and nowhere else", () => {
  assert.deepEqual(segments([0, 120, 240, 2000, 2120], 120), [0, 0, 0, 1, 1]);
});

test("the mean counts hours, not samples", () => {
  const points = [{ t: 0, value: 10 }, { t: 3600, value: 20 }];
  for (let i = 1; i < 60; i += 1) points.push({ t: 3600 + i * 60, value: 20 });
  assert.equal(timeWeightedMean(points), 15);
  assert.equal(timeWeightedMean([]), null);
});

test("a 1-hour spike in a week keeps its colour", () => {
  const points = [];
  for (let i = 0; i < 672; i += 1) {
    const spike = i >= 300 && i < 304;
    points.push({ t: i * 900, band: spike ? "unhealthy" : "good" });
  }
  assert.ok(bandRuns(points).some((run) => run.band === "unhealthy"));
});

test("a dithering series folds to a bounded number of runs", () => {
  const points = [];
  for (let i = 0; i < 1500; i += 1) points.push({ t: i, band: i % 2 ? "good" : "moderate" });
  assert.ok(bandRuns(points).length <= 200);
});
