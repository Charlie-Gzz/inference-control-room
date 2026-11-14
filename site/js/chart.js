// Small SVG chart helpers shared by the what-if and autoscaling views.

const NS = "http://www.w3.org/2000/svg";

export function svg(tag, attrs = {}, parent = null, text = null) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  if (parent) parent.appendChild(el);
  return el;
}

export function linear(d0, d1, r0, r1) {
  const f = (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);
  f.invert = (p) => d0 + ((p - r0) / (r1 - r0)) * (d1 - d0);
  return f;
}

export function log(d0, d1, r0, r1) {
  const a = Math.log(d0);
  const b = Math.log(d1);
  return (v) => r0 + ((Math.log(Math.max(v, d0)) - a) / (b - a || 1)) * (r1 - r0);
}

// Round tick values (1, 2, 5 x 10^k) covering [lo, hi].
export function niceTicks(lo, hi, target = 5) {
  const step0 = (hi - lo) / target;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(Number(v.toPrecision(10)));
  return ticks;
}

export function logTicks(lo, hi) {
  const ticks = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
    for (const m of [1, 2, 5]) {
      const v = m * 10 ** e;
      if (v >= lo * 0.999 && v <= hi * 1.001) ticks.push(Number(v.toPrecision(6)));
    }
  }
  return ticks;
}

// Draws the frame, grid lines and tick labels. Returns the plot group.
export function axes(root, { width, height, margin, x, y, xTicks, yTicks, xLabel, yLabel, xFormat, yFormat }) {
  const g = svg("g", {}, root);
  const text = { fill: "#9CA3AF", "font-size": 11, "font-family": "JetBrains Mono, monospace" };
  for (const t of yTicks) {
    const py = y(t);
    svg("line", { x1: margin.left, x2: width - margin.right, y1: py, y2: py, stroke: "#1F2937" }, g);
    svg("text", { ...text, x: margin.left - 8, y: py + 4, "text-anchor": "end" }, g, yFormat(t));
  }
  for (const t of xTicks) {
    const px = x(t);
    svg("line", { x1: px, x2: px, y1: margin.top, y2: height - margin.bottom, stroke: "#1F2937" }, g);
    svg("text", { ...text, x: px, y: height - margin.bottom + 16, "text-anchor": "middle" }, g, xFormat(t));
  }
  const label = { fill: "#9CA3AF", "font-size": 12, "font-family": "Inter, sans-serif" };
  if (xLabel) svg("text", { ...label, x: (margin.left + width - margin.right) / 2, y: height - 6, "text-anchor": "middle" }, g, xLabel);
  if (yLabel) {
    const cy = (margin.top + height - margin.bottom) / 2;
    svg("text", { ...label, x: 14, y: cy, "text-anchor": "middle", transform: `rotate(-90 14 ${cy})` }, g, yLabel);
  }
  return g;
}

// Colors for server configs: distinct hues, none of them the status red.
export const CONFIG_COLORS = ["#FB7185", "#38BDF8", "#A78BFA", "#34D399", "#FBBF24", "#F472B6", "#22D3EE", "#C4B5FD", "#86EFAC", "#FDBA74", "#93C5FD", "#E879F9"];
