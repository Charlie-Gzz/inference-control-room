// Switchyard control room: loads recorded runs and replays them.
// One clock drives every yard on screen. All drawing is a function of the replay time T.

import { loadIndex, loadRun } from "./data.js";
import { clock, compact, integer, KIND_LABEL, percent, secondsText, why } from "./format.js";
import { YardPanel } from "./panel.js";
import { COLORS, POLICY_COLORS } from "./yard.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const SPEEDS = [1, 2, 4, 8, 16];
const VIEWS = ["split", "room", "whatif", "autoscale", "about"];

export const state = {
  index: null,
  view: "split",
  T: 0,
  playing: !reducedMotion,
  speed: 2,
  scenario: null, // "kind:workload"
  seed: 0,
  policies: { left: "round-robin", right: "prefix-aware", room: "prefix-aware" },
  panels: {},
  selected: null, // { panel, i }
  record: params.has("record"),
};


// --- run selection -----------------------------------------------------------------

const scenarioOf = (run) => `${run.kind}:${run.workload}`;

function scenarioLabel(key) {
  const [kind, workload] = key.split(":");
  if (kind === "ramp") return `${workload} (capacity ramp)`;
  if (kind === "autoscale") return `${workload} (bursty, autoscaling)`;
  if (kind === "proxycheck") return "router overhead check";
  return workload === "no-sharing" ? "no-sharing (control)" : workload;
}

function runsOf(scenario, seed) {
  return state.index.runs.filter((r) => scenarioOf(r) === scenario && (seed == null || r.seed === seed));
}

function findRun(scenario, seed, policy) {
  const options = runsOf(scenario, seed);
  return options.find((r) => r.policy === policy) || options[0];
}

async function applySelection() {
  const options = runsOf(state.scenario, state.seed);
  const names = options.map((r) => r.policy);
  if (!names.includes(state.policies.left)) state.policies.left = names[0];
  if (!names.includes(state.policies.right)) state.policies.right = names[names.length - 1];
  if (!names.includes(state.policies.room)) state.policies.room = names[names.length - 1];
  const sides = state.view === "room" ? ["room"] : ["left", "right"];
  await Promise.all(
    sides.map(async (side) => {
      const run = findRun(state.scenario, state.seed, state.policies[side]);
      state.panels[side].setRun(await loadRun(run.id), names);
    }),
  );
  state.selected = null;
  showInspector();
  drawScrubber();
  renderHonest();
  renderLegend();
  if (state.T > duration()) state.T = 0;
  render();
}

function activePanels() {
  if (state.view === "room") return [state.panels.room];
  if (state.view === "split") return [state.panels.left, state.panels.right];
  return [];
}

function duration() {
  const list = activePanels().filter((p) => p.replay);
  return list.length ? Math.max(...list.map((p) => p.replay.duration)) + 1 : 1;
}

// --- pickers -----------------------------------------------------------------------

function renderPickers() {
  const scenarios = [...new Set(state.index.runs.map(scenarioOf))];
  const seeds = [...new Set(runsOf(state.scenario).map((r) => r.seed))].sort();
  const select = (id, label, options, current) =>
    `<label class="flex items-center gap-1.5 text-muted">${label}
       <select id="${id}" class="bg-panel border border-line rounded-md text-ink text-sm px-2 py-1">
         ${options.map(([v, text]) => `<option value="${v}"${v === current ? " selected" : ""}>${text}</option>`).join("")}
       </select></label>`;
  $("pickers").innerHTML =
    select("pick-scenario", "Workload", scenarios.map((s) => [s, scenarioLabel(s)]), state.scenario) +
    select("pick-seed", "Repeat", seeds.map((s) => [String(s), String(s + 1)]), String(state.seed));
  $("pick-scenario").addEventListener("change", (e) => {
    state.scenario = e.target.value;
    state.seed = runsOf(state.scenario)[0].seed;
    state.T = 0;
    renderPickers();
    applySelection().then(jumpToStart);
  });
  $("pick-seed").addEventListener("change", (e) => {
    state.seed = Number(e.target.value);
    applySelection();
  });
}

// --- transport ---------------------------------------------------------------------

const ICON_PLAY = '<svg width="16" height="16" viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>';
const ICON_PAUSE = '<svg width="16" height="16" viewBox="0 0 16 16"><path d="M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z" fill="currentColor"/></svg>';

function setupTransport() {
  $("speeds").innerHTML = SPEEDS.map((s) => `<button class="speed-btn" data-speed="${s}">${s}x</button>`).join("");
  $("speeds").addEventListener("click", (e) => {
    const speed = Number(e.target.dataset.speed);
    if (speed) {
      state.speed = speed;
      renderTransport();
    }
  });
  $("play").addEventListener("click", () => {
    state.playing = !state.playing;
    renderTransport();
  });
  $("scrub").addEventListener("input", (e) => {
    state.T = (Number(e.target.value) / 1000) * duration();
    render();
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
    if (e.code === "Space") {
      e.preventDefault();
      $("play").click();
    }
  });
  renderTransport();
}

function renderTransport() {
  $("play").innerHTML = state.playing ? ICON_PAUSE : ICON_PLAY;
  for (const b of $("speeds").children) b.classList.toggle("active", Number(b.dataset.speed) === state.speed);
}

// Arrivals per second under the scrubber, with bursts and the warmup marked.
function drawScrubber() {
  const canvas = $("scrub-canvas");
  const panel = activePanels().find((p) => p.replay);
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  if (!panel) return;
  const replay = panel.replay;
  const total = duration();
  const x = (t) => (t / total) * rect.width;
  const h = rect.height;
  const peak = Math.max(...replay.arrivals, 1);
  if (replay.warmup > 0) {
    ctx.fillStyle = "rgba(156,163,175,0.08)";
    ctx.fillRect(0, 0, x(replay.warmup), h);
    ctx.fillStyle = COLORS.muted;
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.textBaseline = "top";
    ctx.fillText("WARMUP", 4, 2);
  }
  for (const [a, b] of replay.bursts()) {
    ctx.fillStyle = "rgba(245,158,11,0.14)";
    ctx.fillRect(x(a), 0, x(b) - x(a), h);
    ctx.fillStyle = COLORS.warn;
    ctx.fillRect(x(a), 0, x(b) - x(a), 2);
  }
  ctx.fillStyle = "#3B4658";
  const bar = Math.max(1, rect.width / replay.arrivals.length - 0.5);
  replay.arrivals.forEach((count, s) => {
    const height = (count / peak) * (h - 12);
    ctx.fillRect(x(s), h - 2 - height, bar, height);
  });
  ctx.fillStyle = COLORS.line;
  ctx.fillRect(0, h - 2, rect.width, 2);
  state.scrubBase = ctx.getImageData(0, 0, canvas.width, canvas.height);
}

function drawPlayhead() {
  const canvas = $("scrub-canvas");
  if (!state.scrubBase) return;
  const ctx = canvas.getContext("2d");
  ctx.putImageData(state.scrubBase, 0, 0);
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const x = (state.T / duration()) * rect.width;
  ctx.fillStyle = "rgba(251,113,133,0.12)";
  ctx.fillRect(0, 0, x, rect.height);
  ctx.fillStyle = COLORS.rose;
  ctx.fillRect(Math.round(x) - 1, 0, 2, rect.height);
  $("scrub").value = String(Math.round((state.T / duration()) * 1000));
  const panel = activePanels().find((p) => p.replay);
  const warm = panel && state.T < panel.replay.warmup ? ' <span class="tag">warmup</span>' : "";
  $("time").innerHTML = `<b>${clock(state.T)}</b> / ${clock(duration() - 1)}${warm}`;
}

function jumpToStart() {
  const panel = activePanels().find((p) => p.replay);
  if (!panel) return;
  // Open on live traffic: the end of the warmup, when caches are warm and counting starts.
  state.T = params.has("t") ? Number(params.get("t")) : Math.max(panel.replay.warmup - 2, 0);
  render();
}

// --- scoreboard (split view) -------------------------------------------------------

function renderScoreboard() {
  const { left, right } = state.panels;
  if (!left.replay || !right.replay) return;
  const a = left.replay.stats(state.T).total;
  const b = right.replay.stats(state.T).total;
  const share = (s) => (s.promptTokens ? s.cachedTokens / s.promptTokens : null);
  const rows = [
    ["Requests finished", a.done, b.done, integer, null],
    ["Mean time to first token", a.meanTtft, b.meanTtft, secondsText, "low"],
    ["Missed the latency target", a.misses, b.misses, integer, "low"],
    ["Prompt tokens from cache", share(a), share(b), (v) => percent(v, 1), "high"],
    ["Tokens not recomputed", a.cachedTokens, b.cachedTokens, compact, "high"],
  ];
  const colorA = POLICY_COLORS[left.replay.meta.policy];
  const colorB = POLICY_COLORS[right.replay.meta.policy];
  const html = rows
    .map(([name, va, vb, fmt, better]) => {
      const wins = (x, y) => better && x != null && y != null && x !== y && (better === "low" ? x < y : x > y);
      const total = (va || 0) + (vb || 0);
      const wa = total > 0 ? ((va || 0) / total) * 100 : 50;
      return `<div class="score-row">
        <div class="score-name">${name}</div>
        <div class="score-val${wins(va, vb) ? " win" : ""}">${fmt(va)}</div>
        <div class="score-val right${wins(vb, va) ? " win" : ""}">${fmt(vb)}</div>
        <div class="score-bar"><i style="width:${wa}%;background:${colorA}"></i><i style="width:${100 - wa}%;background:${colorB}"></i></div>
      </div>`;
    })
    .join("");
  const counting = state.T >= left.replay.warmup;
  const head = (panel, color, side) =>
    `<span class="mono text-xs font-semibold ${side}" style="color:${color}">${panel.replay.meta.policy}</span>`;
  $("scoreboard").innerHTML = `
    <div class="score-title">Same requests, same arrival times</div>
    <div class="text-xs text-muted mt-1 mb-2">${counting ? "Totals since the warmup ended." : "Warming up. Counting starts when the warmup ends."}</div>
    <div class="flex justify-between">${head(left, colorA, "")}${head(right, colorB, "text-right")}</div>
    ${html}`;
}

// --- inspector and tooltip ---------------------------------------------------------

function showInspector() {
  const box = $("inspector");
  const docked = state.view === "room";
  const dock = $("inspector-dock");
  if (docked && box.parentElement !== dock) dock.appendChild(box);
  if (!docked && box.parentElement !== document.body) document.body.appendChild(box);
  box.classList.toggle("floating", !docked);
  for (const p of Object.values(state.panels)) p.yard.selected = -1;
  if (!state.selected) {
    box.classList.toggle("hidden-view", !docked);
    box.innerHTML = docked
      ? '<h3>Request inspector</h3><p class="text-muted mt-2">Click any car to see that request\'s real record: when it arrived, which GPU it went to and why, how much of its prompt was cached, and how long it took.</p>'
      : "";
    return;
  }
  const { panel, i } = state.selected;
  panel.yard.selected = i;
  const rec = panel.replay.record(i);
  const cached = rec.promptTokens ? rec.cachedTokens / rec.promptTokens : 0;
  const verdict = rec.error ? '<span style="color:var(--bad)">failed</span>' : rec.good ? '<span style="color:var(--good)">within the target</span>' : '<span style="color:var(--bad)">missed the target</span>';
  box.classList.remove("hidden-view");
  box.innerHTML = `
    <div class="flex items-center justify-between gap-2">
      <h3>Request #${rec.id} <span class="text-muted font-normal">${KIND_LABEL[rec.kind] || rec.kind}</span></h3>
      <button id="inspector-close" class="text-muted hover:text-ink text-lg leading-none" aria-label="Close">&times;</button>
    </div>
    <dl>
      <dt>Arrived at</dt><dd>${rec.scheduled.toFixed(2)} s${rec.warmup ? " (warmup)" : ""}</dd>
      <dt>Prefix group</dt><dd>${rec.tenant === "none" ? rec.group : `${rec.tenant} · ${rec.group}`}${rec.turn > 1 ? ` · turn ${rec.turn}` : ""}</dd>
      <dt>Routed to</dt><dd>GPU ${rec.replica} · ${rec.reason}</dd>
      <dt>Prompt</dt><dd>${integer(rec.promptTokens)} tokens</dd>
      <dt>From cache</dt><dd style="color:var(--rose)">${integer(rec.cachedTokens)} (${percent(cached)})</dd>
      <dt>Output</dt><dd>${integer(rec.outputTokens)} tokens</dd>
      <dt>First token after</dt><dd>${secondsText(rec.ttft)}</dd>
      <dt>Per token</dt><dd>${secondsText(rec.itl)}</dd>
      <dt>Total time</dt><dd>${secondsText(rec.total)}</dd>
      <dt>Router added</dt><dd>${rec.overheadUs == null ? "-" : `${rec.overheadUs} µs`}</dd>
      <dt>Latency target</dt><dd>${verdict}</dd>
    </dl>
    <div class="why">${why(rec)}</div>`;
  $("inspector-close").addEventListener("click", () => {
    state.selected = null;
    showInspector();
    render();
  });
}

function onPick(panel, i) {
  state.selected = i >= 0 ? { panel, i } : null;
  showInspector();
  render();
}

function onHover(panel, i, event) {
  const tip = $("tip");
  if (i < 0) {
    tip.classList.add("hidden-view");
    return;
  }
  const rec = panel.replay.record(i);
  tip.innerHTML = `<div class="text-muted mb-1">Latest decision · request #${rec.id}</div>${why(rec)}`;
  tip.classList.remove("hidden-view");
  tip.style.left = `${Math.min(event.clientX + 14, window.innerWidth - 300)}px`;
  tip.style.top = `${event.clientY + 16}px`;
}

function onPolicy(panel, policy) {
  const side = Object.keys(state.panels).find((k) => state.panels[k] === panel);
  state.policies[side] = policy;
  applySelection();
}

// --- text around the yards ---------------------------------------------------------

function renderHeadline() {
  const summary = state.index.summary;
  if (state.index.mock) {
    $("headline").textContent = "Same four GPUs, same traffic, two routers. (Mock data: the real headline appears after the GPU runs.)";
  } else if (summary && summary.headline) {
    $("headline").innerHTML = summary.headline.html;
  } else {
    $("headline").textContent = "Same four GPUs, same traffic, two routers.";
  }
}

function renderHonest() {
  const panel = activePanels().find((p) => p.replay);
  const facts = (state.index.summary && state.index.summary.facts) || {};
  const parts = [];
  if (state.index.mock) {
    parts.push('<span class="tag modeled">mock</span> Local simulator, development only. Not real numbers.');
  } else if (state.view === "autoscale") {
    parts.push('<span class="tag real">measured</span> latency and replica counts · <span class="tag modeled">modeled</span> GPU-seconds saved');
  } else {
    parts.push('<span class="tag real">real</span> Replay of a real recorded run. Nothing is simulated.');
  }
  if (facts.gpu) parts.push(`GPU: <b>${facts.gpu}</b>`);
  if (facts.model) parts.push(`Model: <b>${facts.model}</b>`);
  if (facts.engine) parts.push(`Engine: <b>${facts.engine}</b>`);
  if (panel && (state.view === "split" || state.view === "room")) {
    parts.push(`Workload: <b>${scenarioLabel(state.scenario)}</b>, repeat ${state.seed + 1}`);
  }
  parts.push('Arrival pattern: <a class="underline" href="https://github.com/HPMLL/BurstGPT">BurstGPT</a> trace (CC BY 4.0)');
  $("honest").innerHTML = parts.map((p) => `<span>${p}</span>`).join("");
}

function renderLegend() {
  $("room-legend").innerHTML = `
    <div class="font-semibold">How to read the yard</div>
    <p class="text-muted">Each car is one real request. Its color is its prefix group (tenant, document set or agent type), so cars of one color share the start of their prompt.</p>
    <p><span class="legend-dot" style="border:1px solid #7dd3fc"></span>Hollow: waiting for its first token (queue and prompt processing).</p>
    <p><span class="legend-dot" style="background:#7dd3fc"></span>Filling up: tokens are streaming out.</p>
    <p><span class="legend-dot" style="background:var(--rose);border-radius:50%"></span>Rose flash on arrival: most of the prompt was already in that GPU's cache.</p>
    <p><span class="legend-dot" style="background:var(--bad)"></span>Red: the first token took longer than the 2 s target.</p>
    <p class="text-muted">Hover the router to see its latest decision. Dials show the last 30 seconds.</p>`;
}

// --- views -------------------------------------------------------------------------

async function setView(view) {
  state.view = VIEWS.includes(view) ? view : "split";
  for (const v of VIEWS) $(`view-${v}`).classList.toggle("hidden-view", v !== state.view);
  for (const b of $("nav").querySelectorAll("[data-view]")) b.classList.toggle("active", b.dataset.view === state.view);
  const replaying = state.view === "split" || state.view === "room";
  $("transport").classList.toggle("hidden-view", !replaying);
  $("pickers").classList.toggle("hidden-view", !replaying);
  $("headline-box").classList.toggle("hidden-view", state.view === "about");
  if (replaying) {
    for (const p of activePanels()) p.yard.resize();
    await applySelection();
  } else {
    state.selected = null;
    showInspector();
    renderHonest();
    const module = await import(`./view-${state.view}.js`);
    module.render($(`view-${state.view}`), state);
  }
  if (!state.record) history.replaceState(null, "", state.view === "split" ? location.pathname : `?view=${state.view}`);
}

// --- frame loop --------------------------------------------------------------------

export function render() {
  const opts = { reduced: reducedMotion };
  for (const p of activePanels()) p.draw(state.T, opts);
  if (state.view === "split") renderScoreboard();
  if (state.view === "split" || state.view === "room") drawPlayhead();
}

let last = null;
function tick(now) {
  if (last != null && state.playing && !document.hidden && !state.record) {
    const dt = Math.min((now - last) / 1000, 0.1);
    state.T += dt * state.speed;
    if (state.T >= duration()) state.T = 0;
    render();
  }
  last = now;
  requestAnimationFrame(tick);
}

async function main() {
  state.index = await loadIndex();
  const index = state.index;
  $("mock-banner").classList.toggle("hidden-view", !index.mock);
  const mk = (id) => new YardPanel($(id), { onPick, onPolicy, onHover });
  state.panels = { left: mk("yard-left"), right: mk("yard-right"), room: mk("yard-room") };

  const split = index.default_split && index.runs.find((r) => r.id === index.default_split.left);
  const first = split || index.runs[0];
  state.scenario = params.get("scenario") || scenarioOf(first);
  state.seed = params.has("seed") ? Number(params.get("seed")) : first.seed;
  if (params.has("speed")) state.speed = Number(params.get("speed"));

  renderHeadline();
  renderPickers();
  setupTransport();
  $("nav").addEventListener("click", (e) => {
    if (e.target.dataset.view) setView(e.target.dataset.view);
  });
  $("tour-start").addEventListener("click", async () => {
    const tour = await import("./tour.js");
    tour.start(state, { setView, render });
  });
  window.addEventListener("resize", () => {
    for (const p of activePanels()) p.yard.resize();
    drawScrubber();
    render();
  });

  await setView(params.get("view") || "split");
  jumpToStart();
  await document.fonts.ready;
  render();
  if (state.record) {
    const recorder = await import("./record.js");
    recorder.install(state, { setView, render, applySelection, loadRun });
  }
  requestAnimationFrame(tick);
  document.documentElement.dataset.ready = "1";
}

main().catch((error) => {
  $("headline").textContent = `Could not load the recorded runs: ${error.message}`;
  console.error(error);
});
