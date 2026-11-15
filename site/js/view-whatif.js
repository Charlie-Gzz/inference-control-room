// What-if explorer: every measured operating point (a server config at one traffic level),
// the Pareto frontier, and the cheapest config that meets the latency target you set.

import { axes, CONFIG_COLORS, linear, log, logTicks, niceTicks, svg } from "./chart.js";
import { money, percent } from "./format.js";

const ui = { ttft: 2.0, itl: 0.1, yKey: "itl_p95_s", gpu: "l4", workload: "chat" };
let observer = null;

function meets(p) {
  return !p.errors && p.ttft_p95_s != null && p.ttft_p95_s <= ui.ttft && (p.itl_p95_s == null || p.itl_p95_s <= ui.itl);
}

// Highest traffic level that meets the target with every lower level meeting it too.
function capacityPoint(points) {
  let best = null;
  for (const p of points) {
    if (!meets(p)) break;
    best = p;
  }
  return best;
}

function pareto(points, yKey) {
  const usable = points.filter((p) => p.cost_per_m_output != null && p[yKey] != null);
  usable.sort((a, b) => a.cost_per_m_output - b.cost_per_m_output || a[yKey] - b[yKey]);
  const out = [];
  let bestY = Infinity;
  for (const p of usable) {
    if (p[yKey] < bestY) {
      out.push(p);
      bestY = p[yKey];
    }
  }
  return out;
}

export function render(root, state) {
  const sweep = state.index.summary && state.index.summary.sweep;
  if (!sweep || !Object.keys(sweep).length) {
    root.innerHTML = '<div class="card p-6 text-muted">The what-if explorer needs the single-replica sweep results. They are not in this data set.</div>';
    return;
  }
  if (!sweep[ui.gpu]) ui.gpu = Object.keys(sweep)[0];
  if (!sweep[ui.gpu][ui.workload]) ui.workload = Object.keys(sweep[ui.gpu])[0];
  const gpus = Object.keys(sweep);
  const workloads = Object.keys(sweep[ui.gpu]);
  const option = (v, label, current) => `<option value="${v}"${v === current ? " selected" : ""}>${label}</option>`;

  root.innerHTML = `
    <div class="layout-side">
      <div class="card p-3">
        <div class="flex flex-wrap items-center gap-3 px-1 pb-2 text-sm">
          <span class="font-semibold">Every measured operating point</span>
          <label class="text-muted flex items-center gap-1.5">GPU
            <select id="wi-gpu" class="bg-panel border border-line rounded-md text-ink px-2 py-1">${gpus.map((g) => option(g, g.toUpperCase(), ui.gpu)).join("")}</select></label>
          <label class="text-muted flex items-center gap-1.5">Workload
            <select id="wi-workload" class="bg-panel border border-line rounded-md text-ink px-2 py-1">${workloads.map((w) => option(w, w, ui.workload)).join("")}</select></label>
          <label class="text-muted flex items-center gap-1.5">Latency axis
            <select id="wi-y" class="bg-panel border border-line rounded-md text-ink px-2 py-1">
              ${option("itl_p95_s", "p95 inter-token latency", ui.yKey)}${option("ttft_p95_s", "p95 time to first token", ui.yKey)}
            </select></label>
        </div>
        <div id="wi-plot"></div>
        <div class="px-1 pt-2 text-xs text-muted">Each dot is one server config at one traffic level of its ramp (lines join the levels of a config, from light load to heavy). Pushing a GPU harder makes tokens cheaper and responses slower. Solid dots meet your target. The white line is the Pareto frontier: nothing is both cheaper and faster. Levels where requests failed are not drawn.</div>
      </div>
      <div class="space-y-3">
        <div class="card p-4 space-y-4">
          <div class="font-semibold">Your latency target</div>
          <div>
            <div class="flex justify-between text-sm"><span class="text-muted">p95 time to first token</span><span class="mono" id="wi-ttft-val"></span></div>
            <input type="range" class="slo mt-2" id="wi-ttft" min="0.1" max="3" step="0.05" value="${ui.ttft}">
          </div>
          <div>
            <div class="flex justify-between text-sm"><span class="text-muted">p95 inter-token latency</span><span class="mono" id="wi-itl-val"></span></div>
            <input type="range" class="slo mt-2" id="wi-itl" min="0.02" max="0.3" step="0.005" value="${ui.itl}">
          </div>
          <button id="wi-reset" class="nav-btn active">Reset to the default (2 s, 100 ms)</button>
        </div>
        <div class="card p-4" id="wi-answer"></div>
      </div>
    </div>`;

  const redraw = () => draw(root, sweep[ui.gpu][ui.workload]);
  // Redraw when the plot's box changes width (window resize, or late-arriving styles).
  if (observer) observer.disconnect();
  const holder = root.querySelector("#wi-plot");
  let drawnWidth = 0;
  observer = new ResizeObserver(() => {
    if (Math.abs(holder.clientWidth - drawnWidth) > 2) {
      drawnWidth = holder.clientWidth;
      redraw();
    }
  });
  observer.observe(holder);
  root.querySelector("#wi-gpu").addEventListener("change", (e) => {
    ui.gpu = e.target.value;
    render(root, state);
  });
  root.querySelector("#wi-workload").addEventListener("change", (e) => {
    ui.workload = e.target.value;
    render(root, state);
  });
  root.querySelector("#wi-y").addEventListener("change", (e) => {
    ui.yKey = e.target.value;
    redraw();
  });
  root.querySelector("#wi-ttft").addEventListener("input", (e) => {
    ui.ttft = Number(e.target.value);
    redraw();
  });
  root.querySelector("#wi-itl").addEventListener("input", (e) => {
    ui.itl = Number(e.target.value);
    redraw();
  });
  root.querySelector("#wi-reset").addEventListener("click", () => {
    ui.ttft = 2.0;
    ui.itl = 0.1;
    root.querySelector("#wi-ttft").value = "2";
    root.querySelector("#wi-itl").value = "0.1";
    redraw();
  });
  redraw();
}

// Exposed for the video: set the target from a script and redraw.
export function setTarget(root, state, ttft, itl) {
  ui.ttft = ttft;
  ui.itl = itl;
  const a = root.querySelector("#wi-ttft");
  if (!a) return render(root, state);
  a.value = String(ttft);
  root.querySelector("#wi-itl").value = String(itl);
  draw(root, state.index.summary.sweep[ui.gpu][ui.workload]);
}

function draw(root, data) {
  root.querySelector("#wi-ttft-val").textContent = `${ui.ttft.toFixed(2)} s`;
  root.querySelector("#wi-itl-val").textContent = `${Math.round(ui.itl * 1000)} ms`;
  const configs = data.configs;
  const color = Object.fromEntries(configs.map((c, i) => [c.config, CONFIG_COLORS[i % CONFIG_COLORS.length]]));
  // Levels where requests failed are not drawn: their token counts (and so their cost) mean nothing.
  const drawn = (p) => p.cost_per_m_output != null && p[ui.yKey] != null && !p.errors;
  const all = configs.flatMap((c) => c.points).filter(drawn);
  const capacity = Object.fromEntries(configs.map((c) => [c.config, capacityPoint(c.points)]));
  const winners = Object.values(capacity).filter(Boolean).sort((a, b) => a.cost_per_m_output - b.cost_per_m_output);
  const best = winners[0] || null;

  const holder = root.querySelector("#wi-plot");
  const width = Math.max(holder.clientWidth, 320);
  const height = Math.max(360, Math.min(560, width * 0.56));
  const margin = { left: 76, right: 18, top: 14, bottom: 44 };
  const xs = all.map((p) => p.cost_per_m_output);
  const ys = all.map((p) => p[ui.yKey]);
  const limit = ui.yKey === "itl_p95_s" ? ui.itl : ui.ttft;
  const x = log(Math.min(...xs) * 0.85, Math.max(...xs) * 1.15, margin.left, width - margin.right);
  const yLo = Math.min(...ys, limit) * 0.8;
  const yHi = Math.max(...ys, limit) * 1.25;
  const y = log(yLo, yHi, height - margin.bottom, margin.top);
  holder.innerHTML = "";
  const root_ = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Cost per million output tokens against p95 latency for every operating point" }, holder);
  const unit = ui.yKey === "itl_p95_s" ? (v) => `${Math.round(v * 1000)} ms` : (v) => `${v >= 1 ? v.toFixed(1) : v.toFixed(2)} s`;
  axes(root_, {
    width, height, margin, x, y,
    xTicks: logTicks(Math.min(...xs) * 0.85, Math.max(...xs) * 1.15),
    yTicks: logTicks(yLo, yHi),
    xLabel: "$ per million output tokens (lower is cheaper)",
    yLabel: ui.yKey === "itl_p95_s" ? "p95 inter-token latency" : "p95 time to first token",
    xFormat: (v) => `$${v}`, yFormat: unit,
  });

  // The target on the plotted latency axis.
  const ly = y(limit);
  svg("rect", { x: margin.left, y: margin.top, width: width - margin.left - margin.right, height: Math.max(ly - margin.top, 0), fill: "rgba(239,68,68,0.06)" }, root_);
  svg("line", { x1: margin.left, x2: width - margin.right, y1: ly, y2: ly, stroke: "#EF4444", "stroke-dasharray": "5 4" }, root_);
  svg("text", { x: width - margin.right - 4, y: ly - 6, fill: "#EF4444", "font-size": 11, "text-anchor": "end", "font-family": "JetBrains Mono, monospace" }, root_, `target ${unit(limit)}`);

  // The frontier only counts points that meet your target on the latency not on this axis.
  const otherOk = (p) => (ui.yKey === "itl_p95_s" ? p.ttft_p95_s <= ui.ttft : (p.itl_p95_s || 0) <= ui.itl);
  const frontier = pareto(all.filter(otherOk), ui.yKey);
  if (frontier.length > 1) {
    svg("polyline", { points: frontier.map((p) => `${x(p.cost_per_m_output)},${y(p[ui.yKey])}`).join(" "), fill: "none", stroke: "#E5E7EB", "stroke-width": 1.5, "stroke-opacity": 0.75 }, root_);
  }
  for (const c of configs) {
    const pts = c.points.filter(drawn);
    svg("polyline", { points: pts.map((p) => `${x(p.cost_per_m_output)},${y(p[ui.yKey])}`).join(" "), fill: "none", stroke: color[c.config], "stroke-opacity": 0.3 }, root_);
    for (const p of pts) {
      const ok = meets(p) && capacity[c.config] && p.level <= capacity[c.config].level;
      const dot = svg("circle", { cx: x(p.cost_per_m_output), cy: y(p[ui.yKey]), r: 5, fill: ok ? color[c.config] : "#0B0F17", stroke: color[c.config], "stroke-width": 1.5, "fill-opacity": ok ? 0.95 : 1, "stroke-opacity": ok ? 1 : 0.55 }, root_);
      svg("title", {}, dot, `${c.config} at ${p.rate_rps} req/s: ${money(p.cost_per_m_output)} per M output tokens, TTFT p95 ${p.ttft_p95_s} s, ITL p95 ${Math.round((p.itl_p95_s || 0) * 1000)} ms${ok ? "" : " (misses the target)"}`);
    }
  }
  if (best) {
    const bx = x(best.cost_per_m_output);
    const by = y(best[ui.yKey]);
    svg("circle", { cx: bx, cy: by, r: 11, fill: "none", stroke: "#FB7185", "stroke-width": 2 }, root_);
    const right = bx < width - 190;
    svg("text", { x: bx + (right ? 16 : -16), y: by + 4, fill: "#FB7185", "font-size": 12, "font-weight": 600, "text-anchor": right ? "start" : "end", "font-family": "Inter, sans-serif" }, root_, `cheapest: ${best.config}`);
  }

  // Legend: one entry per config, with its capacity under the current target.
  const legend = configs
    .map((c) => {
      const cap = capacity[c.config];
      return `<div class="flex items-center justify-between gap-2 text-xs py-0.5${cap ? "" : " opacity-50"}">
        <span><span class="legend-dot" style="background:${color[c.config]};border-radius:50%"></span><span class="mono">${c.config}</span></span>
        <span class="mono text-muted">${cap ? `${cap.rate_rps} req/s · ${money(cap.cost_per_m_output)}` : "misses the target"}</span></div>`;
    })
    .join("");

  const answer = root.querySelector("#wi-answer");
  if (!best) {
    answer.innerHTML = `<div class="font-semibold">No config meets this target</div><p class="text-muted text-sm mt-2">Even at the lightest traffic level tested, every config is slower than the target. Loosen one of the sliders.</p><div class="mt-3">${legend}</div>`;
    return;
  }
  const cfg = configs.find((c) => c.config === best.config);
  const top = best.level === Math.max(...cfg.points.map((p) => p.level));
  const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  answer.innerHTML = `
    <div class="text-xs uppercase tracking-wider text-muted">Cheapest config that meets it</div>
    <div class="mono text-2xl font-semibold mt-1" style="color:var(--rose)">${cfg.config}</div>
    <div class="mono text-xl mt-1">${money(best.cost_per_m_output)} <span class="text-sm text-muted">per million output tokens</span></div>
    <dl class="inspector" style="border:0;padding:0;background:none;display:grid;grid-template-columns:auto 1fr;gap:5px 12px;margin-top:12px">
      ${row("Weights", cfg.quantization)}
      ${row("Speculative decoding", cfg.speculative)}
      ${row("Prefix caching", cfg.prefix_caching ? "on" : "off")}
      ${row("Batch limit", `${cfg.max_num_seqs} sequences`)}
      ${row("Traffic it carries", `${best.rate_rps} req/s${top ? " or more" : ""}`)}
      ${row("p95 first token", `${best.ttft_p95_s.toFixed(2)} s`)}
      ${row("p95 token gap", `${Math.round((best.itl_p95_s || 0) * 1000)} ms`)}
      ${row("Incl. prompt tokens", `${money(best.cost_per_m_total)} per M`)}
      ${row("GSM8K accuracy", cfg.gsm8k ? percent(cfg.gsm8k.accuracy, 1) : "not measured")}
    </dl>
    ${top ? '<p class="text-xs text-muted mt-2">This config met the target at the highest traffic level tested, so its real capacity may be higher and its cost lower.</p>' : ""}
    <div class="mt-3 pt-3 border-t border-line"><div class="text-xs uppercase tracking-wider text-muted mb-1">Capacity under this target</div>${legend}</div>`;
}
