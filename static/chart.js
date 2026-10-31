// The history chart, in hand-written SVG: no library, nothing fetched, and
// light enough for a Pi 3. Line and fill carry the band colour along the x axis,
// exactly where the readings did, and break where recording did.

import { bandRuns, segments } from "./metrics.js";

const SVG = "http://www.w3.org/2000/svg";
const large = () => window.innerWidth >= 1200 && window.innerHeight >= 700;

function el(name, attrs = {}, text) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

// Fritsch-Carlson slopes: the same "monotone" curve Swift Charts draws, which
// never overshoots a reading and never invents a peak between two samples.
function monotonePath(points) {
  if (points.length === 1) return `M${points[0].x},${points[0].y}`;
  const n = points.length;
  const delta = [];
  for (let i = 0; i < n - 1; i += 1) {
    delta.push((points[i + 1].y - points[i].y) / (points[i + 1].x - points[i].x));
  }
  const slope = [delta[0]];
  for (let i = 1; i < n - 1; i += 1) {
    slope.push(delta[i - 1] * delta[i] <= 0 ? 0 : (2 * delta[i - 1] * delta[i]) / (delta[i - 1] + delta[i]));
  }
  slope.push(delta[n - 2]);

  let d = `M${points[0].x.toFixed(1)},${points[0].y.toFixed(1)}`;
  for (let i = 0; i < n - 1; i += 1) {
    const a = points[i];
    const b = points[i + 1];
    const h = (b.x - a.x) / 3;
    d += `C${(a.x + h).toFixed(1)},${(a.y + slope[i] * h).toFixed(1)},${(b.x - h).toFixed(1)},${(b.y - slope[i + 1] * h).toFixed(1)},${b.x.toFixed(1)},${b.y.toFixed(1)}`;
  }
  return d;
}

function niceStep(rough) {
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  for (const step of [1, 2, 2.5, 5]) {
    if (rough <= step * magnitude) return step * magnitude;
  }
  return 10 * magnitude;
}

// Y domain and gridlines on round numbers. Particles and indices start from
// zero; slow quantities like temperature would be a flat line on such an axis.
function yScale(values, fromZero, floor, divisions) {
  const low = fromZero ? 0 : Math.min(...values);
  const high = Math.max(...values, fromZero ? 1 : -Infinity, floor);
  const pad = fromZero ? 0 : Math.max((high - low) * 0.1, 0.5);
  const step = niceStep((high + pad - (low - pad)) / divisions);
  const lo = Math.floor((low - pad) / step) * step;
  const hi = Math.ceil((high + pad) / step) * step;
  const ticks = [];
  for (let i = 0; lo + i * step <= hi + step / 1000; i += 1) ticks.push(lo + i * step);
  return { lo, hi, ticks };
}

const tickText = (v) => String(Number(v.toFixed(2)));

// Tick times on calendar boundaries in local time, one layout per range.
function xTicks(rangeName, start, now, narrow) {
  const ticks = [];
  const date = new Date(start * 1000);
  date.setMinutes(0, 0, 0);
  if (rangeName === "day") {
    const step = narrow ? 6 : 3;
    date.setHours(date.getHours() - (date.getHours() % step));
    for (; date.getTime() <= now * 1000; date.setHours(date.getHours() + step)) {
      ticks.push({ t: date.getTime() / 1000, label: date.toLocaleTimeString([], { hour: "numeric" }) });
    }
  } else if (rangeName === "week") {
    date.setHours(0);
    for (; date.getTime() <= now * 1000; date.setDate(date.getDate() + 1)) {
      ticks.push({ t: date.getTime() / 1000, label: date.toLocaleDateString([], { weekday: "short" }) });
    }
  } else if (rangeName === "month") {
    date.setHours(0);
    date.setDate(date.getDate() - date.getDay());
    for (; date.getTime() <= now * 1000; date.setDate(date.getDate() + 7)) {
      ticks.push({ t: date.getTime() / 1000, label: date.toLocaleDateString([], { month: "short", day: "numeric" }) });
    }
  } else {
    const step = narrow ? 3 : 1;
    date.setHours(0);
    date.setDate(1);
    for (; date.getTime() <= now * 1000; date.setMonth(date.getMonth() + step)) {
      ticks.push({ t: date.getTime() / 1000, label: date.toLocaleDateString([], { month: "short" }) });
    }
  }
  return ticks.filter((tick) => tick.t >= start);
}

function hoverLabel(t, rangeName) {
  const date = new Date(t * 1000);
  return rangeName === "day"
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric" });
}

let gradients = 0;

// `series`: { points: [{t, value, band}], start, now, bucket, rangeName,
// fromZero, format, unit }. Points run oldest first and have no nulls.
// `compact` is a kiosk strip: no hover, fewer gridlines, a scale held up to at
// least `floor`, and day labels only if `xLabels`.
export function drawChart(host, series) {
  const { points, start, now, bucket, rangeName, fromZero, format, unit } = series;
  const { compact = false, xLabels = true, floor = -Infinity } = series;
  const width = host.clientWidth;
  const height = host.clientHeight;
  host.replaceChildren();
  if (width < 40 || height < 40) return;

  const PAD = large() ? { top: 12, right: 16, bottom: 28, left: 54 } : { top: 10, right: 12, bottom: 22, left: 40 };
  if (compact && !xLabels) PAD.bottom = 8;
  const plot = { w: width - PAD.left - PAD.right, h: height - PAD.top - PAD.bottom };
  const scale = yScale(points.map((p) => p.value), fromZero, floor, compact ? 2 : 3);
  const x = (t) => PAD.left + ((t - start) / (now - start)) * plot.w;
  const y = (v) => PAD.top + plot.h - ((v - scale.lo) / (scale.hi - scale.lo)) * plot.h;

  const svg = el("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img" });

  // Gradient stops stay relative to the data's span and run in user space, so
  // every broken segment shares one colouring instead of restarting its own.
  const defs = el("defs");
  gradients += 1;
  const paint = `bands-${gradients}`;
  const gradient = el("linearGradient", {
    id: paint,
    gradientUnits: "userSpaceOnUse",
    x1: x(points[0].t),
    x2: x(points[points.length - 1].t),
    y1: 0,
    y2: 0,
  });
  for (const run of bandRuns(points)) {
    const color = `var(--band-${run.band})`;
    gradient.append(el("stop", { offset: run.start, style: `stop-color:${color}` }));
    gradient.append(el("stop", { offset: run.end, style: `stop-color:${color}` }));
  }
  defs.append(gradient);
  svg.append(defs);

  for (const tick of scale.ticks) {
    svg.append(el("line", { class: "grid", x1: PAD.left, x2: width - PAD.right, y1: y(tick), y2: y(tick) }));
    svg.append(el("text", { class: "axis", x: PAD.left - 6, y: y(tick) + 3.5, "text-anchor": "end" }, tickText(tick)));
  }

  const narrow = width < 460;
  for (const tick of xTicks(rangeName, start, now, narrow)) {
    svg.append(el("line", { class: "grid", x1: x(tick.t), x2: x(tick.t), y1: PAD.top, y2: PAD.top + plot.h }));
    if (xLabels) svg.append(el("text", { class: "axis", x: x(tick.t), y: height - 6, "text-anchor": "middle" }, tick.label));
  }

  const ids = segments(points.map((p) => p.t), bucket);
  const groups = new Map();
  points.forEach((point, i) => {
    if (!groups.has(ids[i])) groups.set(ids[i], []);
    groups.get(ids[i]).push({ x: x(point.t), y: y(point.value) });
  });
  const base = PAD.top + plot.h;
  for (const group of groups.values()) {
    if (group.length === 1) {
      // A lone point between gaps has no line to draw, but it did happen.
      svg.append(el("circle", { cx: group[0].x, cy: group[0].y, r: 2, fill: `url(#${paint})` }));
      continue;
    }
    const line = monotonePath(group);
    const first = group[0];
    const last = group[group.length - 1];
    // Well below the line: the fill gives it a body, not competition.
    svg.append(el("path", { class: "fill", fill: `url(#${paint})`, d: `${line}L${last.x},${base}L${first.x},${base}Z` }));
    svg.append(el("path", { class: "line", stroke: `url(#${paint})`, d: line }));
  }

  if (compact) {
    host.append(svg);
    return;
  }

  // Crosshair and tooltip, for a mouse on the LAN or a finger on the screen.
  const cross = el("line", { class: "cross", y1: PAD.top, y2: base, visibility: "hidden" });
  const dot = el("circle", { class: "cross-dot", r: 4, visibility: "hidden" });
  const label = el("text", { class: "cross-label", visibility: "hidden" });
  svg.append(cross, dot, label);

  const show = (event) => {
    const box = svg.getBoundingClientRect();
    const px = event.clientX - box.left;
    let nearest = points[0];
    for (const point of points) {
      if (Math.abs(x(point.t) - px) < Math.abs(x(nearest.t) - px)) nearest = point;
    }
    const cx = x(nearest.t);
    cross.setAttribute("x1", cx);
    cross.setAttribute("x2", cx);
    dot.setAttribute("cx", cx);
    dot.setAttribute("cy", y(nearest.value));
    dot.setAttribute("style", `fill:var(--band-${nearest.band})`);
    label.textContent = `${format(nearest.value)} ${unit}  ·  ${hoverLabel(nearest.t, rangeName)}`.trim();
    const left = cx < width / 2;
    label.setAttribute("text-anchor", left ? "start" : "end");
    label.setAttribute("x", cx + (left ? 8 : -8));
    label.setAttribute("y", PAD.top + 12);
    for (const node of [cross, dot, label]) node.setAttribute("visibility", "visible");
  };
  const hide = () => {
    for (const node of [cross, dot, label]) node.setAttribute("visibility", "hidden");
  };
  svg.addEventListener("pointermove", show);
  svg.addEventListener("pointerdown", show);
  svg.addEventListener("pointerleave", hide);

  host.append(svg);
}
