// Autoscaling view: the bursty window with a static 4-replica fleet and an autoscaled one.
// Latency and replica counts are measured. GPU-seconds saved are MODELED (as if each
// replica were billed on its own) and labeled that way.

import { axes, linear, log, logTicks, niceTicks, svg } from "./chart.js";
import { loadRun } from "./data.js";
import { percent, secondsText } from "./format.js";
import { percentile } from "./replay.js";
import { POLICY_COLORS } from "./yard.js";

const BUCKET = 10; // seconds per latency bucket
let seed = null;

// Replicas being paid for (from "start") and replicas serving (from "ready"), as step series.
function replicaSteps(replay) {
  const events = replay.meta.autoscaler_events;
  const n = replay.replicas;
  if (!events) return { billed: [[0, n], [replay.duration, n]], serving: [[0, n], [replay.duration, n]] };
  let billed = 1;
  let serving = 1;
  const b = [[0, billed]];
  const s = [[0, serving]];
  for (const e of events) {
    if (e.event === "start") b.push([e.t, ++billed]);
    if (e.event === "stopped") b.push([e.t, --billed]);
    if (e.event === "ready") s.push([e.t, ++serving]);
    if (e.event === "drain") s.push([e.t, --serving]);
  }
  b.push([replay.duration, billed]);
  s.push([replay.duration, serving]);
  return { billed: b, serving: s };
}

function startupRange(values) {
  const lo = Math.round(Math.min(...values));
  const hi = Math.round(Math.max(...values));
  return lo === hi ? `${lo} s` : `${lo} to ${hi} s`;
}

function stepPath(steps, x, y) {
  let d = "";
  steps.forEach(([t, v], i) => {
    d += i === 0 ? `M${x(t)},${y(v)}` : `H${x(t)}V${y(v)}`;
  });
  return d;
}

function ttftBuckets(replay) {
  const buckets = [];
  const { t, ttft } = replay.req;
  for (let i = 0; i < replay.n; i++) {
    const k = Math.floor(t[i] / BUCKET);
    (buckets[k] = buckets[k] || []).push(ttft[i] ?? 120);
  }
  return buckets.map((values, k) => (values ? [(k + 0.5) * BUCKET, percentile(values.sort((a, b) => a - b), 95)] : null)).filter(Boolean);
}

export async function render(root, state) {
  const runs = state.index.runs.filter((r) => r.kind === "autoscale");
  if (!runs.length) {
    root.innerHTML = '<div class="card p-6 text-muted">The autoscaling runs are not in this data set.</div>';
    return;
  }
  const seeds = [...new Set(runs.map((r) => r.seed))].sort();
  if (seed == null || !seeds.includes(seed)) seed = seeds[0];
  const pick = (policy) => runs.find((r) => r.seed === seed && r.policy === policy);
  const [fixed, scaled] = await Promise.all([loadRun(pick("static").id), loadRun(pick("autoscaled").id)]);
  const summary = (state.index.summary && state.index.summary.autoscale) || {};
  const saved = summary.modeled_gpu_seconds_saved;
  const med = (variant, key) => (summary[variant] ? summary[variant][key].median : null);
  const startups = (summary.autoscaled ? summary.autoscaled.repeats : []).flatMap((r) => r.startup_s || []);
  const card = (label, value, sub, tag) =>
    `<div class="card p-4"><div class="text-xs uppercase tracking-wider text-muted flex items-center gap-2">${label}${tag || ""}</div>
     <div class="mono text-2xl font-semibold mt-1">${value}</div><div class="text-xs text-muted mt-1">${sub}</div></div>`;

  root.innerHTML = `
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      ${card("GPU-seconds saved", saved == null ? "-" : percent(saved), `${Math.round(med("autoscaled", "gpu_seconds") || 0).toLocaleString()} vs ${Math.round(med("static", "gpu_seconds") || 0).toLocaleString()} GPU-seconds, median of ${summary.static ? summary.static.repeats.length : 0} repeats`, '<span class="tag modeled">modeled</span>')}
      ${card("p95 time to first token", `${secondsText(med("autoscaled", "ttft_p95_s"))}`, `autoscaled, against ${secondsText(med("static", "ttft_p95_s"))} with 4 replicas always on`, '<span class="tag real">measured</span>')}
      ${card("Requests within the target", percent(med("autoscaled", "goodput"), 1), `autoscaled, against ${percent(med("static", "goodput"), 1)} static`, '<span class="tag real">measured</span>')}
      ${card("Replica startup", startups.length ? startupRange(startups) : "-", "from the scale-up decision to the first request served: what autoscaling has to absorb", '<span class="tag real">measured</span>')}
    </div>
    <div class="card p-3 mt-3">
      <div class="flex flex-wrap items-center gap-4 px-1 pb-2 text-sm">
        <span class="font-semibold">Bursty traffic window</span>
        <label class="text-muted flex items-center gap-1.5">Repeat
          <select id="as-seed" class="bg-panel border border-line rounded-md text-ink px-2 py-1">${seeds.map((s) => `<option value="${s}"${s === seed ? " selected" : ""}>${s + 1}</option>`).join("")}</select></label>
        <span class="text-muted"><span class="legend-dot" style="background:${POLICY_COLORS.static}"></span>static, 4 replicas</span>
        <span class="text-muted"><span class="legend-dot" style="background:${POLICY_COLORS.autoscaled}"></span>autoscaled, 1 to 4 replicas</span>
      </div>
      <div id="as-plot"></div>
      <div class="px-1 pt-2 text-xs text-muted">Top: requests per second (the same arrivals for both fleets). Middle: replicas switched on, with the dashed line showing replicas actually serving (a new replica needs time to load the model). Bottom: p95 time to first token per ${BUCKET} seconds, on a log scale. The saving is modeled: it counts each replica from the moment it is started until it is stopped, as if replicas were billed one by one. In the real test all four GPUs sat in one container and were billed for the whole run.</div>
    </div>`;
  root.querySelector("#as-seed").addEventListener("change", (e) => {
    seed = Number(e.target.value);
    render(root, state);
  });

  const holder = root.querySelector("#as-plot");
  const width = Math.max(holder.clientWidth, 320);
  const margin = { left: 58, right: 16, top: 10, bottom: 46 };
  const heights = [110, 110, 170];
  const gap = 26;
  const height = margin.top + heights.reduce((a, b) => a + b, 0) + gap * 2 + margin.bottom;
  const total = Math.max(fixed.duration, scaled.duration);
  const x = linear(0, total, margin.left, width - margin.right);
  const root_ = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Traffic, replicas and latency over the bursty window" }, holder);
  const xTicks = niceTicks(0, total, 8);
  let top = margin.top;
  const panel = (h, y, yTicks, yLabel, yFormat, last) => {
    axes(root_, {
      width, height: top + h + (last ? margin.bottom : 0), margin: { ...margin, top, bottom: last ? margin.bottom : 0 }, x, y,
      xTicks, yTicks, yLabel: null, xLabel: last ? "seconds since the run started" : null,
      xFormat: (v) => (last ? String(v) : ""), yFormat,
    });
    svg("text", { x: margin.left + 6, y: top + 12, fill: "#9CA3AF", "font-size": 11, "font-family": "Inter, sans-serif" }, root_, yLabel);
  };

  // 1. Traffic.
  const peak = Math.max(...fixed.arrivals, 1);
  const y1 = linear(0, peak, top + heights[0], top);
  panel(heights[0], y1, niceTicks(0, peak, 3), "requests per second", (v) => String(v));
  const bar = Math.max((width - margin.left - margin.right) / fixed.arrivals.length - 0.5, 0.5);
  fixed.arrivals.forEach((count, s) => {
    if (count > 0) svg("rect", { x: x(s), y: y1(count), width: bar, height: y1(0) - y1(count), fill: "#4B5563" }, root_);
  });
  top += heights[0] + gap;

  // 2. Replicas.
  const y2 = linear(0, 5.2, top + heights[1], top);
  panel(heights[1], y2, [0, 1, 2, 3, 4], "replicas switched on", (v) => String(v));
  for (const [replay, color] of [[fixed, POLICY_COLORS.static], [scaled, POLICY_COLORS.autoscaled]]) {
    const steps = replicaSteps(replay);
    svg("path", { d: stepPath(steps.billed, x, y2), fill: "none", stroke: color, "stroke-width": 2 }, root_);
    if (replay.meta.autoscaler_events) {
      svg("path", { d: stepPath(steps.serving, x, y2), fill: "none", stroke: color, "stroke-width": 1.3, "stroke-dasharray": "4 3", "stroke-opacity": 0.8 }, root_);
    }
  }
  top += heights[1] + gap;

  // 3. Latency.
  const series = [[fixed, POLICY_COLORS.static], [scaled, POLICY_COLORS.autoscaled]].map(([r, c]) => [ttftBuckets(r), c]);
  const values = series.flatMap(([pts]) => pts.map((p) => p[1]));
  const slo = fixed.slo.ttft_s;
  const lo = Math.max(Math.min(...values, slo) * 0.7, 0.01);
  const hi = Math.max(...values, slo) * 1.4;
  const y3 = log(lo, hi, top + heights[2], top);
  panel(heights[2], y3, logTicks(lo, hi), "p95 time to first token", (v) => (v >= 1 ? `${v} s` : `${Math.round(v * 1000)} ms`), true);
  svg("line", { x1: margin.left, x2: width - margin.right, y1: y3(slo), y2: y3(slo), stroke: "#EF4444", "stroke-dasharray": "5 4" }, root_);
  svg("text", { x: width - margin.right - 4, y: y3(slo) - 5, fill: "#EF4444", "font-size": 11, "text-anchor": "end", "font-family": "JetBrains Mono, monospace" }, root_, `target ${slo} s`);
  for (const [pts, color] of series) {
    svg("polyline", { points: pts.map(([t, v]) => `${x(t)},${y3(v)}`).join(" "), fill: "none", stroke: color, "stroke-width": 2 }, root_);
    for (const [t, v] of pts) svg("circle", { cx: x(t), cy: y3(v), r: 2.5, fill: color }, root_);
  }
}
