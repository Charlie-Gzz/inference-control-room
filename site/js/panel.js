// A yard panel: policy chip, the yard canvas, and the six dials under it.

import { compact, percent, seconds } from "./format.js";
import { POLICY_COLORS, Yard } from "./yard.js";

const DIALS = [
  ["ttftP50", "TTFT p50", "Time to first token, median, last 30 s"],
  ["ttftP95", "TTFT p95", "Time to first token, 95th percentile, last 30 s"],
  ["itlP95", "ITL p95", "Inter-token latency: time between output tokens, 95th percentile, last 30 s"],
  ["tps", "Tokens / s", "Fleet output tokens per second, from vLLM's counters"],
  ["hit", "Cache hit", "Share of prompt tokens served from the prefix cache, last 30 s"],
  ["goodput", "Within SLO", "Share of requests that met the latency target, last 30 s"],
];

export class YardPanel {
  constructor(mount, { onPick, onPolicy, onHover }) {
    this.mount = mount;
    mount.innerHTML = `
      <div class="yard-panel">
        <div class="yard-head">
          <span class="chip"></span>
          <select aria-label="Routing policy"></select>
          <span class="yard-sub"></span>
        </div>
        <canvas class="yard-canvas"></canvas>
        <div class="dials">${DIALS.map(
          ([key, label, title]) =>
            `<div class="dial" title="${title}"><div class="dial-label">${label}</div><div class="dial-value" data-dial="${key}">-</div></div>`,
        ).join("")}</div>
      </div>`;
    this.chip = mount.querySelector(".chip");
    this.select = mount.querySelector("select");
    this.sub = mount.querySelector(".yard-sub");
    this.canvas = mount.querySelector("canvas");
    this.cells = Object.fromEntries(DIALS.map(([key]) => [key, mount.querySelector(`[data-dial="${key}"]`)]));
    this.yard = new Yard(this.canvas);
    this.replay = null;
    this.select.addEventListener("change", () => onPolicy(this, this.select.value));
    this.canvas.addEventListener("click", (e) => {
      const [x, y] = this.local(e);
      onPick(this, this.yard.pick(x, y));
    });
    this.canvas.addEventListener("mousemove", (e) => {
      const [x, y] = this.local(e);
      onHover(this, this.yard.nearSwitch(x, y) ? this.yard.lastDecision : -1, e);
    });
    this.canvas.addEventListener("mouseleave", (e) => onHover(this, -1, e));
  }

  local(e) {
    const rect = this.canvas.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  }

  setRun(replay, policies) {
    this.replay = replay;
    const policy = replay.meta.policy;
    const color = POLICY_COLORS[policy] || "#9CA3AF";
    this.chip.style.setProperty("--c", color);
    this.chip.textContent = policy;
    this.select.innerHTML = policies.map((p) => `<option${p === policy ? " selected" : ""}>${p}</option>`).join("");
    this.select.style.display = policies.length > 1 ? "" : "none";
    const rate = replay.meta.rate_rps ? `${replay.meta.rate_rps} req/s` : "ramp";
    this.sub.textContent = `${replay.meta.workload} · repeat ${replay.meta.seed + 1} · ${rate} · ${replay.replicas} GPUs`;
    this.yard.setReplay(replay, color);
  }

  draw(T, opts) {
    if (!this.replay) return;
    this.yard.draw(T, opts);
    const s = this.replay.stats(T);
    const slo = this.replay.slo;
    this.dial("ttftP50", seconds(s.ttftP50), level(s.ttftP50, slo.ttft_s));
    this.dial("ttftP95", seconds(s.ttftP95), level(s.ttftP95, slo.ttft_s));
    this.dial("itlP95", seconds(s.itlP95), level(s.itlP95, slo.itl_s));
    this.dial("tps", [compact(s.tps), ""], "");
    this.dial("hit", [percent(s.hit), ""], "rose");
    this.dial("goodput", [percent(s.goodput), ""], s.goodput == null ? "" : s.goodput >= 0.99 ? "good" : s.goodput >= 0.9 ? "warn" : "bad");
  }

  dial(key, [value, unit], cls) {
    const cell = this.cells[key];
    const html = unit ? `${value}<small>${unit}</small>` : value;
    if (cell.dataset.html !== html) {
      cell.innerHTML = html;
      cell.dataset.html = html;
    }
    const name = `dial-value ${cls}`;
    if (cell.className !== name) cell.className = name;
  }
}

// good within the target, warn in the last quarter below it, bad above it.
function level(value, limit) {
  if (value == null) return "";
  if (value > limit) return "bad";
  return value > 0.75 * limit ? "warn" : "good";
}
