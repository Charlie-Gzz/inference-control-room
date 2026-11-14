// Replay model: everything the control room shows at replay time T, computed only from
// the recorded run. No simulation: positions and counters are functions of real timestamps.

export const TIMING = {
  approach: 0.8, // seconds a car spends on the entry track before the switch
  branch: 0.5, // seconds on the branch; the car reaches its platform at the scheduled time
  settle: 0.25, // sliding into its slot
  depart: 0.5, // leaving after the last token
  flash: 0.7, // cache-hit flash at arrival
  window: 30, // trailing window of the dials, seconds
};

export function lowerBound(arr, x) {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function percentile(sorted, q) {
  if (!sorted.length) return null;
  const pos = ((sorted.length - 1) * q) / 100;
  const lo = Math.floor(pos);
  const hi = Math.min(lo + 1, sorted.length - 1);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export class Replay {
  constructor(data) {
    this.meta = data.meta;
    this.req = data.req;
    this.rep = data.rep;
    this.names = { groups: data.groups, tenants: data.tenants, kinds: data.kinds, reasons: data.reasons };
    this.n = this.req.t.length;
    this.replicas = this.meta.replicas;
    this.slo = this.meta.slo;
    this.duration = this.meta.duration_s;
    this.warmup = this.meta.warmup_s || 0;
    this._prepare();
  }

  _prepare() {
    const { t, end, first, ttft, itl, err, rep, ptok, ctok, otok, warm } = this.req;
    const n = this.n;
    // When a request leaves the screen: its last token, or shortly after a failure.
    this.leave = new Float64Array(n);
    this.good = new Uint8Array(n);
    let maxLife = 0;
    for (let i = 0; i < n; i++) {
      this.leave[i] = end[i] ?? Math.min(t[i] + 8, this.duration);
      maxLife = Math.max(maxLife, this.leave[i] - t[i]);
      const ok = !err[i] && ttft[i] != null && ttft[i] <= this.slo.ttft_s;
      this.good[i] = ok && (itl[i] == null || itl[i] <= this.slo.itl_s) ? 1 : 0;
    }
    this.maxLife = maxLife;

    // Platform slots: each request keeps the lowest free slot of its replica while present.
    this.slot = new Int32Array(n).fill(-1);
    this.maxSlots = 0;
    const free = Array.from({ length: this.replicas }, () => []);
    const next = new Int32Array(this.replicas);
    const leaving = []; // min-heap substitute: sorted insert is fine at this size
    for (let i = 0; i < n; i++) {
      const r = rep[i];
      if (r == null || r >= this.replicas) continue;
      while (leaving.length && leaving[0][0] <= t[i]) {
        const [, rr, s] = leaving.shift();
        free[rr].push(s);
      }
      let s;
      if (free[r].length) {
        free[r].sort((a, b) => a - b);
        s = free[r].shift();
      } else {
        s = next[r]++;
      }
      this.slot[i] = s;
      this.maxSlots = Math.max(this.maxSlots, s + 1);
      const at = this.leave[i] + TIMING.depart;
      let k = leaving.length;
      while (k > 0 && leaving[k - 1][0] > at) k--;
      leaving.splice(k, 0, [at, r, s]);
    }

    // Orders for the dials: by first token (TTFT window) and by finish (everything else).
    const byFirst = [];
    for (let i = 0; i < n; i++) if (first[i] != null) byFirst.push(i);
    byFirst.sort((a, b) => first[a] - first[b]);
    this.firstIdx = byFirst;
    this.firstT = Float64Array.from(byFirst, (i) => first[i]);

    const byLeave = Array.from({ length: n }, (_, i) => i).sort((a, b) => this.leave[a] - this.leave[b]);
    this.leaveIdx = byLeave;
    this.leaveT = Float64Array.from(byLeave, (i) => this.leave[i]);
    // Prefix sums over finish order. "m" sums count measured requests only (the scoreboard).
    const mk = () => new Float64Array(n + 1);
    this.cum = { n: mk(), good: mk(), ptok: mk(), ctok: mk(), mN: mk(), mMiss: mk(), mPtok: mk(), mCtok: mk(), mTtft: mk(), mTtftN: mk() };
    byLeave.forEach((i, k) => {
      const c = this.cum;
      const m = warm[i] ? 0 : 1;
      c.n[k + 1] = c.n[k] + 1;
      c.good[k + 1] = c.good[k] + this.good[i];
      c.ptok[k + 1] = c.ptok[k] + ptok[i];
      c.ctok[k + 1] = c.ctok[k] + ctok[i];
      c.mN[k + 1] = c.mN[k] + m;
      c.mMiss[k + 1] = c.mMiss[k] + m * (1 - this.good[i]);
      c.mPtok[k + 1] = c.mPtok[k] + m * ptok[i];
      c.mCtok[k + 1] = c.mCtok[k] + m * ctok[i];
      c.mTtft[k + 1] = c.mTtft[k] + (m && ttft[i] != null ? ttft[i] : 0);
      c.mTtftN[k + 1] = c.mTtftN[k] + (m && ttft[i] != null ? 1 : 0);
    });

    // Arrivals per second, for the scrubber and its burst markers.
    const seconds = Math.max(1, Math.ceil(this.duration));
    this.arrivals = new Float32Array(seconds);
    for (let i = 0; i < n; i++) this.arrivals[Math.min(Math.floor(t[i]), seconds - 1)]++;
    this._stats = { key: -1, value: null };
    this.totalOutput = otok.reduce((a, b) => a + b, 0);
  }

  // Indices [lo, hi) that can be on screen at time T (still to be filtered by leave time).
  range(T) {
    const { t } = this.req;
    const lead = TIMING.approach + TIMING.branch;
    return [lowerBound(t, T - this.maxLife - TIMING.depart), lowerBound(t, T + lead)];
  }

  // Dials: trailing-window latency, cache hits and goodput. Cached per quarter second.
  stats(T) {
    const key = Math.floor(T * 4);
    if (this._stats.key === key) return this._stats.value;
    const Tq = key / 4;
    const W = TIMING.window;
    const { ttft, itl } = this.req;

    const f0 = lowerBound(this.firstT, Tq - W);
    const f1 = lowerBound(this.firstT, Tq + 1e-9);
    const ttfts = [];
    for (let k = f0; k < f1; k++) ttfts.push(ttft[this.firstIdx[k]]);
    ttfts.sort((a, b) => a - b);

    const l0 = lowerBound(this.leaveT, Tq - W);
    const l1 = lowerBound(this.leaveT, Tq + 1e-9);
    const itls = [];
    for (let k = l0; k < l1; k++) {
      const v = itl[this.leaveIdx[k]];
      if (v != null) itls.push(v);
    }
    itls.sort((a, b) => a - b);
    const c = this.cum;
    const d = (a) => a[l1] - a[l0];
    const done = d(c.n);

    let tps = 0;
    let any = false;
    for (let r = 0; r < this.replicas; r++) {
      const v = this.replicaAt(r, Tq);
      if (v.tps != null) {
        tps += v.tps;
        any = true;
      }
    }
    const value = {
      ttftP50: percentile(ttfts, 50),
      ttftP95: percentile(ttfts, 95),
      itlP95: percentile(itls, 95),
      tps: any ? tps : null,
      hit: d(c.ptok) > 0 ? d(c.ctok) / d(c.ptok) : null,
      goodput: done > 0 ? d(c.good) / done : null,
      // Run totals so far, measured requests only.
      total: {
        done: c.mN[l1],
        misses: c.mMiss[l1],
        cachedTokens: c.mCtok[l1],
        promptTokens: c.mPtok[l1],
        meanTtft: c.mTtftN[l1] ? c.mTtft[l1] / c.mTtftN[l1] : null,
      },
    };
    this._stats = { key, value };
    return value;
  }

  // One replica's recorded metrics at time T. tps is averaged over two seconds.
  replicaAt(r, T) {
    const { dt, running, waiting, kv, tps } = this.rep;
    const cell = Math.max(0, Math.min(Math.floor(T / dt), running[r].length - 1));
    let sum = 0;
    let count = 0;
    for (let k = Math.max(0, cell - 3); k <= cell; k++) {
      if (tps[r][k] != null) {
        sum += tps[r][k];
        count++;
      }
    }
    return {
      up: running[r][cell] != null,
      running: running[r][cell],
      waiting: waiting[r][cell],
      kv: kv[r][cell],
      tps: count ? sum / count : null,
    };
  }

  // Seconds where traffic runs well above the run's mean: the scrubber's burst markers.
  bursts(factor = 1.4) {
    const a = this.arrivals;
    const mean = this.n / a.length;
    const smooth = (s) => (a[Math.max(s - 1, 0)] + a[s] + a[Math.min(s + 1, a.length - 1)]) / 3;
    const spans = [];
    let start = null;
    for (let s = 0; s <= a.length; s++) {
      const hot = s < a.length && smooth(s) > factor * mean;
      if (hot && start == null) start = s;
      if (!hot && start != null) {
        if (s - start >= 3) spans.push([start, s]);
        start = null;
      }
    }
    return spans;
  }

  // Everything the inspector shows about one request: its real record.
  record(i) {
    const q = this.req;
    return {
      id: q.id[i],
      kind: this.names.kinds[q.kind[i]],
      group: this.names.groups[q.grp[i]],
      tenant: this.names.tenants[q.ten[i]],
      turn: q.turn[i],
      scheduled: q.t[i],
      replica: q.rep[i],
      reason: this.names.reasons[q.why[i]],
      matched: q.match[i],
      loads: q.loads[i],
      promptTokens: q.ptok[i],
      cachedTokens: q.ctok[i],
      outputTokens: q.otok[i],
      ttft: q.ttft[i],
      itl: q.itl[i],
      total: q.end[i] != null ? q.end[i] - q.t[i] : null,
      overheadUs: q.ovh[i],
      error: !!q.err[i],
      warmup: !!q.warm[i],
      good: !!this.good[i],
    };
  }
}
