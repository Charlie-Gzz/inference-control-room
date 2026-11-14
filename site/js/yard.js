// The yard: one canvas that draws requests as cars moving from the entry track, through
// the router's switch, into the GPU platforms. Pure function of (replay, time T).

import { TIMING } from "./replay.js";

export const COLORS = {
  bg: "#0B0F17",
  panel: "#131A26",
  line: "#1F2937",
  ink: "#E5E7EB",
  muted: "#9CA3AF",
  rose: "#FB7185",
  good: "#22C55E",
  warn: "#F59E0B",
  bad: "#EF4444",
  rail: "#2B3648",
  bed: "#141C2A",
};

export const POLICY_COLORS = {
  "round-robin": "#9CA3AF",
  "least-loaded": "#38BDF8",
  "prefix-aware": "#FB7185",
  static: "#38BDF8",
  autoscaled: "#FB7185",
  direct: "#9CA3AF",
};

// One hue per prefix group. Reds and rose are left out: they mean SLO miss and cache hit.
export function groupHue(index) {
  return 38 + ((index * 137.5) % 270);
}

function carColor(replay, i, alpha = 1, light = 64) {
  const tenant = replay.req.ten[i];
  if (replay.names.tenants[tenant] === "none") return `hsla(215, 14%, ${light}%, ${alpha})`;
  return `hsla(${groupHue(tenant)}, 72%, ${light}%, ${alpha})`;
}

const easeOut = (u) => 1 - (1 - u) * (1 - u);
const lerp = (a, b, u) => a + (b - a) * u;
const clamp01 = (u) => Math.max(0, Math.min(1, u));

export class Yard {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.accent = opts.accent || COLORS.rose;
    this.replay = null;
    this.selected = -1;
    this.hits = [];
    this.lastDecision = -1;
    this.resize();
  }

  setReplay(replay, accent) {
    this.replay = replay;
    if (accent) this.accent = accent;
    this.selected = -1;
    this.layout();
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.dpr = window.devicePixelRatio || 1;
    this.w = Math.max(rect.width, 50);
    this.h = Math.max(rect.height, 50);
    this.canvas.width = Math.round(this.w * this.dpr);
    this.canvas.height = Math.round(this.h * this.dpr);
    this.layout();
  }

  layout() {
    const { w, h } = this;
    const n = this.replay ? this.replay.replicas : 4;
    const pad = Math.max(8, w * 0.014);
    const gap = Math.max(6, h * 0.022);
    const ph = (h - 2 * pad - gap * (n - 1)) / n;
    const xs = w * 0.16;
    const xb = w * 0.31;
    this.sw = { x: xs, y: h / 2 };
    this.small = ph < 62 || w < 520;
    const header = this.small ? 15 : 20;
    this.platforms = Array.from({ length: n }, (_, i) => {
      const y = pad + i * (ph + gap);
      return {
        x: xb, y, w: w - pad - xb, h: ph, cy: y + ph / 2, header,
        area: { x: xb + 10, y: y + header + 3, w: w - pad - xb - 20, h: ph - header - 3 - 9 },
      };
    });
    // Largest car size that still fits the busiest moment of the run.
    const need = this.replay ? Math.max(this.replay.maxSlots, 1) : 1;
    const area = this.platforms[0].area;
    let car = null;
    for (let s = this.small ? 9 : 13; s >= 2.5; s -= 0.5) {
      const cw = s * 1.9;
      const g = Math.max(1.5, s * 0.32);
      const rows = Math.max(1, Math.floor((area.h + g) / (s + g)));
      const cols = Math.max(1, Math.floor((area.w + g) / (cw + g)));
      car = { cw, ch: s, g, rows, cols };
      if (rows * cols >= need) break;
    }
    this.car = car;
  }

  slotXY(platform, slot) {
    const { cw, ch, g, rows, cols } = this.car;
    const col = Math.floor(slot / rows) % cols;
    const row = slot % rows;
    const used = rows * (ch + g) - g;
    const { area } = platform;
    return [area.x + col * (cw + g), area.y + (area.h - used) / 2 + row * (ch + g)];
  }

  branchPoint(r, u) {
    const p = this.platforms[r];
    const { x: x0, y: y0 } = this.sw;
    const x3 = p.x;
    const y3 = p.cy;
    const dx = (x3 - x0) * 0.55;
    const a = (1 - u) ** 3;
    const b = 3 * (1 - u) ** 2 * u;
    const c = 3 * (1 - u) * u * u;
    const d = u ** 3;
    return [a * x0 + b * (x0 + dx) + c * (x3 - dx) + d * x3, a * y0 + b * y0 + c * y3 + d * y3];
  }

  draw(T, opts = {}) {
    const { ctx, w, h, replay } = this;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    this.hits = [];
    if (!replay) return;
    if (opts.camera) {
      // Video only: zoom by `scale` keeping the point (cx, cy) of the yard at the center.
      const { scale, cx, cy } = opts.camera;
      ctx.translate(w / 2, h / 2);
      ctx.scale(scale, scale);
      ctx.translate(-cx * w, -cy * h);
    }
    const q = replay.req;
    const n = replay.replicas;
    const [lo, hi] = replay.range(T);
    const shown = (i) => opts.only == null || i === opts.only; // video cold open: one request

    // Which branches were used in the last moments, and the newest decision.
    const lit = new Float32Array(n);
    let newest = -1;
    let before = -1;
    for (let i = lo; i < hi; i++) {
      const r = q.rep[i];
      if (r == null || !shown(i)) continue;
      const age = T - (q.t[i] - TIMING.branch);
      if (age < 0) continue;
      if (age < 2.5) lit[r] = Math.min(1, lit[r] + Math.exp(-age / 0.45));
      before = newest;
      newest = i;
    }
    this.lastDecision = newest;

    this.drawTracks(lit);
    this.drawSwitch(T, newest, before);
    for (let r = 0; r < n; r++) this.drawPlatform(r, replay.replicaAt(r, T), opts.only != null);

    const flashes = [];
    for (let i = lo; i < hi; i++) {
      if (replay.leave[i] + TIMING.depart < T || !shown(i)) continue;
      this.drawCar(i, T, flashes, opts);
    }
    if (!opts.reduced) for (const f of flashes) this.drawFlash(f);
  }

  drawTracks(lit) {
    const { ctx, sw } = this;
    const path = (r) => {
      ctx.beginPath();
      ctx.moveTo(sw.x, sw.y);
      for (let u = 0.05; u <= 1.001; u += 0.05) ctx.lineTo(...this.branchPoint(r, u));
    };
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    // Beds, then rails.
    for (const [width, color] of [[7, COLORS.bed], [1.5, COLORS.rail]]) {
      ctx.lineWidth = width;
      ctx.strokeStyle = color;
      ctx.beginPath();
      ctx.moveTo(0, sw.y);
      ctx.lineTo(sw.x, sw.y);
      ctx.stroke();
      for (let r = 0; r < this.platforms.length; r++) {
        path(r);
        ctx.stroke();
      }
    }
    // Ties on the entry track.
    ctx.strokeStyle = COLORS.rail;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 6; x < sw.x - 8; x += 9) {
      ctx.moveTo(x, sw.y - 3.5);
      ctx.lineTo(x, sw.y + 3.5);
    }
    ctx.stroke();
    // Branches in use light up in the policy color.
    for (let r = 0; r < lit.length; r++) {
      if (lit[r] < 0.02) continue;
      ctx.globalAlpha = 0.15 + 0.75 * lit[r];
      ctx.strokeStyle = this.accent;
      ctx.lineWidth = 2;
      ctx.shadowColor = this.accent;
      ctx.shadowBlur = 8 * lit[r];
      path(r);
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.globalAlpha = 1;
    }
  }

  drawSwitch(T, newest, before) {
    const { ctx, sw, replay } = this;
    const q = replay.req;
    // The blade points at the branch of the newest decision, swinging over from the previous one.
    let target = null;
    if (newest >= 0) {
      const to = this.branchPoint(q.rep[newest], 0.42);
      const from = before >= 0 && q.rep[before] != null ? this.branchPoint(q.rep[before], 0.42) : to;
      const u = easeOut(clamp01((T - (q.t[newest] - TIMING.branch)) / 0.14));
      target = [lerp(from[0], to[0], u), lerp(from[1], to[1], u)];
    }
    if (target) {
      ctx.strokeStyle = this.accent;
      ctx.lineWidth = 3;
      ctx.shadowColor = this.accent;
      ctx.shadowBlur = 10;
      ctx.beginPath();
      ctx.moveTo(sw.x, sw.y);
      ctx.lineTo(target[0], target[1]);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }
    ctx.fillStyle = COLORS.bg;
    ctx.strokeStyle = this.accent;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(sw.x, sw.y, this.small ? 5 : 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = COLORS.muted;
    ctx.font = `600 ${this.small ? 8 : 9.5}px "JetBrains Mono", monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText("ROUTER", sw.x, sw.y - (this.small ? 9 : 13));
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(this.small ? "IN" : "REQUESTS", 6, sw.y + (this.small ? 9 : 13));
  }

  drawPlatform(r, m, quiet = false) {
    const { ctx } = this;
    const p = this.platforms[r];
    if (quiet) m = { ...m, running: 0, waiting: 0, tps: null, kv: 0 }; // cold open: no live stats
    ctx.globalAlpha = m.up ? 1 : 0.45;
    ctx.fillStyle = COLORS.panel;
    ctx.strokeStyle = COLORS.line;
    ctx.lineWidth = 1;
    ctx.setLineDash(m.up ? [] : [4, 4]);
    ctx.beginPath();
    ctx.roundRect(p.x + 0.5, p.y + 0.5, p.w - 1, p.h - 1, 8);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);

    const size = this.small ? 9 : 11;
    const baseline = p.y + (this.small ? 4 : 6);
    ctx.textBaseline = "top";
    ctx.font = `600 ${size}px "JetBrains Mono", monospace`;
    ctx.textAlign = "left";
    ctx.fillStyle = COLORS.ink;
    ctx.fillText(`GPU ${r}`, p.x + 10, baseline);
    ctx.font = `${size}px "JetBrains Mono", monospace`;
    ctx.textAlign = "right";
    if (!m.up) {
      ctx.fillStyle = COLORS.muted;
      ctx.fillText("stopped", p.x + p.w - 10, baseline);
    } else {
      const waiting = m.waiting || 0;
      const text = this.small
        ? `${m.running} run  ${waiting} wait  ${m.tps == null ? "-" : Math.round(m.tps)} t/s`
        : `${m.running} running   ${waiting} waiting   ${m.tps == null ? "-" : Math.round(m.tps)} tok/s`;
      ctx.fillStyle = waiting > 0 ? COLORS.warn : COLORS.muted;
      ctx.fillText(text, p.x + p.w - 10, baseline);
      // KV cache in use, along the bottom edge.
      const kv = m.kv || 0;
      ctx.fillStyle = COLORS.line;
      ctx.fillRect(p.x + 10, p.y + p.h - 6, p.w - 20, 2);
      ctx.fillStyle = kv > 0.95 ? COLORS.bad : kv > 0.8 ? COLORS.warn : this.accent;
      ctx.globalAlpha = 0.85;
      ctx.fillRect(p.x + 10, p.y + p.h - 6, (p.w - 20) * Math.min(kv, 1), 2);
      if (!this.small) {
        ctx.globalAlpha = 1;
        ctx.textAlign = "left";
        ctx.fillStyle = COLORS.muted;
        ctx.fillText(`KV ${Math.round(kv * 100)}%`, p.x + 58, baseline);
      }
    }
    ctx.globalAlpha = 1;
  }

  drawCar(i, T, flashes, opts) {
    const { ctx, replay, sw } = this;
    const q = replay.req;
    const r = q.rep[i];
    if (r == null || r >= this.platforms.length) return;
    const t0 = q.t[i];
    const tSwitch = t0 - TIMING.branch;
    const tEnter = tSwitch - TIMING.approach;
    if (T < tEnter) return;
    const { cw, ch } = this.car;
    const tw = Math.max(cw, 11);
    const th = Math.max(ch, 6);
    const selected = i === this.selected;

    if (T < t0) {
      // On the tracks: lit car with a short trail.
      let x;
      let y;
      let px;
      let py;
      if (T < tSwitch) {
        const u = (T - tEnter) / TIMING.approach;
        x = lerp(-tw, sw.x, u);
        y = sw.y;
        px = x - 14;
        py = y;
      } else {
        const u = (T - tSwitch) / TIMING.branch;
        [x, y] = this.branchPoint(r, u);
        [px, py] = this.branchPoint(r, Math.max(0, u - 0.18));
      }
      const color = carColor(replay, i);
      ctx.strokeStyle = carColor(replay, i, 0.35);
      ctx.lineWidth = th * 0.7;
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.lineTo(x, y);
      ctx.stroke();
      ctx.fillStyle = color;
      if (!opts.reduced) {
        ctx.shadowColor = color;
        ctx.shadowBlur = 9;
      }
      ctx.beginPath();
      ctx.roundRect(x - tw / 2, y - th / 2, tw, th, th * 0.35);
      ctx.fill();
      ctx.shadowBlur = 0;
      this.hits.push({ i, x: x - tw / 2, y: y - th / 2, w: tw, h: th });
      if (selected) this.outline(x - tw / 2, y - th / 2, tw, th);
      return;
    }

    // On the platform.
    const p = this.platforms[r];
    const [sx, sy] = this.slotXY(p, replay.slot[i]);
    const settle = easeOut(clamp01((T - t0) / TIMING.settle));
    let x = lerp(p.x - cw, sx, settle);
    const y = lerp(p.cy - ch / 2, sy, settle);
    let alpha = 1;
    const leave = replay.leave[i];
    if (T > leave) {
      const v = clamp01((T - leave) / TIMING.depart);
      x += v * (cw + 14);
      alpha = 1 - v;
    }
    const first = q.first[i];
    const generating = first != null && T >= first;
    const late = generating ? q.ttft[i] > replay.slo.ttft_s : T - t0 > replay.slo.ttft_s;
    const failed = q.err[i] === 1;
    const bad = late || failed;
    const radius = ch * 0.32;

    ctx.globalAlpha = alpha;
    if (generating) {
      // The car fills up as its tokens stream out.
      const span = Math.max((q.end[i] ?? leave) - first, 1e-6);
      const progress = clamp01((T - first) / span);
      ctx.fillStyle = bad ? "rgba(239,68,68,0.20)" : carColor(replay, i, 0.16);
      ctx.strokeStyle = bad ? "rgba(239,68,68,0.75)" : carColor(replay, i, 0.6);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(x + 0.5, y + 0.5, cw - 1, ch - 1, radius);
      ctx.fill();
      ctx.stroke();
      ctx.save();
      ctx.beginPath();
      ctx.rect(x, y, cw * progress, ch);
      ctx.clip();
      ctx.fillStyle = bad ? COLORS.bad : carColor(replay, i, 0.96);
      ctx.beginPath();
      ctx.roundRect(x, y, cw, ch, radius);
      ctx.fill();
      ctx.restore();
    } else {
      // Waiting for its first token (queue + prefill): hollow.
      ctx.fillStyle = bad ? "rgba(239,68,68,0.30)" : carColor(replay, i, 0.16);
      ctx.strokeStyle = bad ? COLORS.bad : carColor(replay, i, 0.85);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(x + 0.5, y + 0.5, cw - 1, ch - 1, radius);
      ctx.fill();
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    this.hits.push({ i, x, y, w: cw, h: ch });
    if (selected) this.outline(x, y, cw, ch);

    const age = T - t0;
    if (age < TIMING.flash && q.ptok[i] > 0) {
      flashes.push({ x: x + cw / 2, y: y + ch / 2, u: age / TIMING.flash, share: q.ctok[i] / q.ptok[i], size: ch });
    }
  }

  // Center of a request's car at time T (canvas CSS pixels). The video's camera follows it.
  carXY(i, T) {
    const q = this.replay.req;
    const r = q.rep[i];
    const t0 = q.t[i];
    const tSwitch = t0 - TIMING.branch;
    const tEnter = tSwitch - TIMING.approach;
    if (T < tSwitch) return [lerp(-11, this.sw.x, clamp01((T - tEnter) / TIMING.approach)), this.sw.y];
    if (T < t0) return this.branchPoint(r, (T - tSwitch) / TIMING.branch);
    const p = this.platforms[r];
    const [sx, sy] = this.slotXY(p, this.replay.slot[i]);
    const u = easeOut(clamp01((T - t0) / TIMING.settle));
    return [lerp(p.x - this.car.cw, sx, u) + this.car.cw / 2, lerp(p.cy - this.car.ch / 2, sy, u) + this.car.ch / 2];
  }

  // A cache hit flashes rose as the car arrives. A miss gets a faint grey ring.
  drawFlash({ x, y, u, share, size }) {
    const { ctx } = this;
    const hit = share >= 0.1;
    const strength = hit ? 0.35 + 0.65 * share : 0.3;
    ctx.globalAlpha = (1 - u) * strength;
    ctx.strokeStyle = hit ? COLORS.rose : COLORS.muted;
    ctx.lineWidth = hit ? 1.8 : 1;
    if (hit) {
      ctx.shadowColor = COLORS.rose;
      ctx.shadowBlur = 12;
    }
    ctx.beginPath();
    ctx.arc(x, y, size * (0.8 + 1.3 * easeOut(u)) * (hit ? 1 : 0.7), 0, Math.PI * 2);
    ctx.stroke();
    if (hit) {
      ctx.fillStyle = COLORS.rose;
      ctx.globalAlpha = (1 - u) * 0.6 * share;
      ctx.beginPath();
      ctx.arc(x, y, size * 0.75, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
  }

  outline(x, y, w, h) {
    const { ctx } = this;
    ctx.strokeStyle = "#FFFFFF";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(x - 2.5, y - 2.5, w + 5, h + 5, 4);
    ctx.stroke();
  }

  // Request under the pointer (canvas CSS pixels), or -1. Small cars get a larger target.
  pick(x, y) {
    let best = -1;
    let bestD = 9;
    for (const hit of this.hits) {
      const dx = Math.max(hit.x - x, 0, x - (hit.x + hit.w));
      const dy = Math.max(hit.y - y, 0, y - (hit.y + hit.h));
      const d = Math.hypot(dx, dy);
      if (d < bestD) {
        bestD = d;
        best = hit.i;
      }
    }
    return best;
  }

  nearSwitch(x, y) {
    return Math.hypot(x - this.sw.x, y - this.sw.y) < 22;
  }
}
