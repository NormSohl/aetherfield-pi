import { BANDS, METRICS, timeWeightedMean } from "./metrics.js";
import { drawChart } from "./chart.js";

const RANGES = [
  { id: "day", title: "Day" },
  { id: "week", title: "Week" },
  { id: "month", title: "Month" },
  { id: "year", title: "Year" },
];

const CURRENT_EVERY = 15_000;
const HISTORY_EVERY = 60_000;

// Stand-ins for SF Symbols, which can't ship on a Pi.
const ICONS = {
  gauge: '<path d="M2 11a6 6 0 1 1 12 0"/><path d="M8 11l3-4"/>',
  dots: '<circle cx="4" cy="5" r="1.4"/><circle cx="10" cy="3.5" r="1.4"/><circle cx="12" cy="9" r="1.4"/><circle cx="6" cy="10" r="1.4"/><circle cx="9" cy="13" r="1.4"/>',
  cloud: '<path d="M4.5 12.5a3 3 0 0 1-.4-6A4 4 0 0 1 11.8 6a3.3 3.3 0 0 1 .2 6.5z"/>',
  thermometer: '<path d="M6.5 9.3V3a1.5 1.5 0 0 1 3 0v6.3a3 3 0 1 1-3 0z"/>',
  drop: '<path d="M8 1.5s4.5 4.8 4.5 8a4.5 4.5 0 0 1-9 0c0-3.2 4.5-8 4.5-8z"/>',
  wind: '<path d="M1.5 6h8a2 2 0 1 0-2-2"/><path d="M1.5 10h11a1.8 1.8 0 1 1-1.8 1.8"/>',
};

// A URL parameter wins, so the kiosk's starting chart can be set in its URL.
function remembered(key, fallback, allowed) {
  const asked = new URLSearchParams(location.search).get(key);
  if (allowed.includes(asked)) return asked;
  try {
    const value = localStorage.getItem(key);
    return allowed.includes(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // A preference that doesn't stick is no reason to stop.
  }
}

const params = new URLSearchParams(location.search);
const kiosk = params.has("kiosk");
if (kiosk) {
  document.documentElement.dataset.theme = "dark";
  document.documentElement.classList.add("kiosk");
  document.body.classList.add("kiosk");
}

const state = {
  metric: remembered("metric", "pm25", METRICS.map((m) => m.id)),
  range: remembered("range", "day", RANGES.map((r) => r.id)),
  current: null,
  history: null,
  reached: true, // Whether this page can reach its own server.
};

const $ = (id) => document.getElementById(id);
const settings = () => state.current?.settings ?? { fahrenheit: true, useCompensated: true };
const metricOf = (id) => METRICS.find((m) => m.id === id);
const timeText = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

function buildTiles() {
  for (const metric of METRICS) {
    const tile = document.createElement("button");
    tile.className = "tile";
    tile.type = "button";
    tile.dataset.metric = metric.id;
    tile.innerHTML = `
      <span class="tile-title"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[metric.icon]}</svg></span>
      <span class="tile-value"><span class="tile-number">—</span><span class="tile-unit"></span></span>
      <span class="tile-band"><span class="dot"></span><span class="tile-band-text">No reading</span></span>`;
    tile.querySelector(".tile-title").append(metric.title);
    tile.addEventListener("click", () => {
      state.metric = metric.id;
      remember("metric", metric.id);
      renderTiles();
      renderHistory();
    });
    $("tiles").append(tile);
  }
}

function buildRanges() {
  for (const range of RANGES) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = range.title;
    button.dataset.range = range.id;
    button.addEventListener("click", () => {
      state.range = range.id;
      remember("range", range.id);
      state.history = null;
      renderRanges();
      renderHistory();
      refreshHistory();
    });
    $("ranges").append(button);
  }
}

function renderTiles() {
  const s = settings();
  const reading = state.current?.reading ?? null;
  for (const tile of $("tiles").children) {
    const metric = metricOf(tile.dataset.metric);
    const value = reading ? metric.value(reading, s) : null;
    const band = value === null ? null : BANDS[metric.band(value, s)];
    tile.setAttribute("aria-pressed", String(metric.id === state.metric));
    tile.querySelector(".tile-number").textContent = value === null ? "—" : metric.format(value);
    tile.querySelector(".tile-unit").textContent = metric.unit(s);
    tile.querySelector(".tile-band-text").textContent = band?.short ?? "No reading";
    tile.querySelector(".dot").style.setProperty("--dot", band ? `var(--band-${band.id})` : "");
  }
}

function renderRanges() {
  for (const button of $("ranges").children) {
    button.setAttribute("aria-pressed", String(button.dataset.range === state.range));
  }
}

function renderStatus() {
  const current = state.current;
  let text = null;
  let detail = "";
  if (!state.reached) {
    text = "Can't reach the logger.";
  } else if (current?.error) {
    text = current.error;
    detail = `Checking ${current.monitor.host}`;
  }
  if (text && current?.ts) detail = `Last answered ${timeText(current.ts)}`;

  $("banner").hidden = !text;
  $("banner-text").textContent = text ?? "";
  $("banner-detail").textContent = detail;
  document.body.classList.toggle("stale", Boolean(text));

  const waiting = current && !current.clockSet;
  $("status").hidden = !waiting;
  $("status").textContent = waiting ? "Not recording: waiting for network time" : "";
  if (current) $("name").textContent = current.monitor.name;
}

function emptyMessage(anyRecorded) {
  const range = RANGES.find((r) => r.id === state.range).title.toLowerCase();
  return anyRecorded
    ? `Nothing recorded in the last ${range}. Pick a longer range to see older history.`
    : "Recording. The chart fills in about a point a minute.";
}

function renderHistory() {
  const s = settings();
  const metric = metricOf(state.metric);
  const unit = metric.unit(s);
  $("history-title").textContent = metric.title;

  const history = state.history;
  if (!history) return;

  const anyRecorded = history.rows.length > 0;
  const points = [];
  let samples = 0;
  for (const row of history.rows) {
    const reading = {};
    history.fields.forEach((field, i) => {
      reading[field] = row[i];
    });
    const value = metric.value(reading, s);
    if (value === null) continue;
    samples += reading.n;
    points.push({ t: reading.t, value, band: BANDS[metric.band(value, s)].id });
  }

  const host = $("chart");
  const summary = $("summary");
  if (points.length < 2) {
    host.replaceChildren();
    const message = document.createElement("div");
    message.className = "empty";
    message.textContent = emptyMessage(anyRecorded && samples > 0);
    host.append(message);
    summary.replaceChildren();
    return;
  }

  drawChart(host, {
    points,
    start: history.start,
    now: history.now,
    bucket: history.bucket,
    rangeName: state.range,
    fromZero: metric.id !== "temperature" && metric.id !== "humidity",
    format: metric.format,
    unit,
  });

  const last = points[points.length - 1];
  const average = timeWeightedMean(points);
  const dot = document.createElement("span");
  dot.className = "dot";
  dot.style.setProperty("--dot", `var(--band-${last.band})`);
  const text = document.createElement("span");
  text.textContent = `${samples.toLocaleString()} samples · avg ${average === null ? "—" : metric.format(average)} · now ${metric.format(last.value)} ${unit}`;
  summary.replaceChildren(dot, text);
}

function renderClock() {
  $("clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

async function refreshCurrent() {
  try {
    state.current = await getJSON("/api/current");
    state.reached = true;
    renderTiles();
  } catch {
    state.reached = false;
  }
  renderStatus();
}

async function refreshHistory() {
  const range = state.range;
  try {
    const history = await getJSON(`/api/history?range=${range}`);
    if (range !== state.range) return; // A slower answer for a range since left.
    state.history = history;
    renderHistory();
  } catch {
    // The banner from refreshCurrent says so; keep the chart that's on screen.
  }
}

// A long-lived browser on 1 GB of RAM is the likeliest thing here to go bad
// slowly, so the kiosk starts clean once a day, in the dead of night.
function scheduleKioskReload() {
  const next = new Date();
  next.setHours(4, 0, 0, 0);
  if (next <= new Date()) next.setDate(next.getDate() + 1);
  setTimeout(() => location.reload(), next - new Date());
}

buildTiles();
buildRanges();
renderTiles();
renderRanges();
renderClock();
await refreshCurrent();
await refreshHistory();

setInterval(refreshCurrent, CURRENT_EVERY);
setInterval(refreshHistory, HISTORY_EVERY);
setInterval(renderClock, 5_000);
if (kiosk) scheduleKioskReload();

let resizeTimer;
new ResizeObserver(() => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderHistory, 120);
}).observe($("chart"));
