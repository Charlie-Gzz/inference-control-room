"""Every chart, drawn from `results/summaries/summary.json` (and run files where needed).

`icr charts` writes PNG (1600 px wide) and SVG into `assets/charts/`. Titles state the
takeaway and are built from the numbers, so a rerun with different results rewrites them.
Policies are labeled on the axis and configs by marker shape: color is never the only cue.
"""

from __future__ import annotations

import json
import math

from matplotlib.ticker import FuncFormatter, NullFormatter

from icr import config
from icr.analysis import optimizer, runs
from icr.analysis.metrics import percentile
from icr.assets import theme
from icr.assets.theme import BAD, INK, MUTED, POLICY, ROSE, WARN

SUMMARY_FILE = config.RESULTS_DIR / "summaries" / "summary.json"
WORKLOAD_LABEL = {
    "chat": "chat",
    "rag": "rag",
    "no-sharing": "no-sharing\n(control)",
    "agentic": "agentic",
}
DASH = (0, (4, 3))


def load_summary() -> dict:
    return json.loads(SUMMARY_FILE.read_text("utf-8"))


def _pct(change: float) -> str:
    return f"{abs(change) * 100:.0f}%"


def _footer(s: dict, gpu: str | None = None, extra: str = "") -> str:
    f = s.get("facts", {})
    parts = [gpu or f.get("gpu", ""), f.get("model", ""), f.get("engine", ""), extra,
             "arrivals: BurstGPT trace (CC BY 4.0)"]  # fmt: skip
    return "  ·  ".join(p for p in parts if p)


def _finish(fig, name: str, title: str, subtitle: str, foot: str, bottom_px: int = 150, **adjust):
    """Header, footer and margins, then save. The axes start below the wrapped header."""
    top = theme.titles(fig, title, subtitle)
    fig.subplots_adjust(top=top, bottom=theme.bottom(fig, bottom_px), **adjust)
    theme.footer(fig, foot)
    return theme.save(fig, name)


def _policy_bars(ax, table: dict, metric: str, scale: float = 1.0, fmt: str = "{:.2f}") -> None:
    """One bar per policy at the median, a range line for min..max, a dot per repeat."""
    names = list(table)
    for k, name in enumerate(names):
        s = table[name][metric]
        if s["median"] is None:
            continue
        ax.bar(k, s["median"] * scale, width=0.62, color=POLICY[name], alpha=0.92, zorder=2)
        ax.plot([k, k], [s["min"] * scale, s["max"] * scale], color=INK, lw=1.4, zorder=3)
        values = [v * scale for v in s["values"] if v is not None]
        ax.scatter([k] * len(values), values, s=13, color=theme.BG, edgecolor=INK, lw=0.8, zorder=4)
        ax.annotate(fmt.format(s["median"] * scale), (k, s["max"] * scale), xytext=(0, 5),
                    textcoords="offset points", ha="center", fontsize=9, color=INK,
                    fontfamily=theme.MONO)  # fmt: skip
    ax.set_xticks(range(len(names)), [n.replace("-", "-\n") for n in names], fontsize=8.5)
    ax.grid(axis="x", visible=False)
    ax.margins(y=0.2)
    ax.set_ylim(bottom=0)


# --- fleet -------------------------------------------------------------------------


def capacity_by_policy(s: dict):
    cap = s["capacity"]["policies"]
    head = s.get("headline", {})
    fig = theme.figure(860)
    left, right = fig.subplots(1, 2)
    _policy_bars(left, cap, "max_rps_at_slo", fmt="{:.1f}")
    left.set_title("Highest traffic within the SLO (req/s)")
    _policy_bars(right, cap, "cost_per_m_output", fmt="${:.2f}")
    right.set_title("Cost per million output tokens there (USD)")
    change, cost = head.get("capacity_change"), head.get("cost_change")
    if change is None or abs(change) < 0.005:
        title = "Every routing policy carries the same traffic within the SLO"
    else:
        word = "more" if change > 0 else "less"
        title = f"Prefix-aware routing serves {_pct(change)} {word} traffic within the SLO on the same 4 GPUs"
        if cost is not None:
            title += f", {_pct(cost)} {'cheaper' if cost < 0 else 'more expensive'} per token"
    rates = ", ".join(f"{r:g}" for r in s["capacity"]["rates_rps"])
    level_s = s["capacity"].get("level_s") or 60
    sub = (f"Capacity ramp on the chat workload: levels of {rates} req/s, {level_s:g} s each, 2 repeats. "
           "Bar = median, line = min to max, dots = repeats.")  # fmt: skip
    foot = _footer(s, extra="SLO: p95 TTFT <= 2 s, p95 inter-token latency <= 100 ms, no errors")
    return _finish(fig, "capacity_by_policy", title, sub, foot, left=0.07, right=0.97, wspace=0.22)


def latency_by_policy(s: dict):
    fleet = s["fleet"]
    workloads = [w for w in WORKLOAD_LABEL if w in fleet]
    rows = [
        ("ttft_p95_s", "p95 time to first token (s)", 1.0, "{:.2f}"),
        ("itl_p95_s", "p95 inter-token latency (ms)", 1000.0, "{:.0f}"),
        ("goodput", "requests within the SLO (%)", 100.0, "{:.0f}"),
    ]
    fig = theme.figure(1300)
    axes = fig.subplots(len(rows), len(workloads), squeeze=False)
    for i, (metric, label, scale, fmt) in enumerate(rows):
        for j, workload in enumerate(workloads):
            ax = axes[i][j]
            _policy_bars(ax, fleet[workload]["policies"], metric, scale, fmt)
            if j == 0:
                ax.set_ylabel(label)
            if i == 0:
                name = WORKLOAD_LABEL[workload].replace("\n", " ")
                ax.set_title(f"{name}  ·  {fleet[workload]['rate_rps']:g} req/s", color=INK)
            if metric == "itl_p95_s":
                ax.axhline(100, color=BAD, lw=1, ls=DASH, zorder=1)
            if metric == "ttft_p95_s" and ax.get_ylim()[1] > 2:
                ax.axhline(2, color=BAD, lw=1, ls=DASH, zorder=1)
    ttft = s.get("headline", {}).get("ttft_p95_change")
    title = "Same traffic, three routers: latency by routing policy"
    if ttft is not None:
        title = (f"Prefix-aware routing {'cuts' if ttft < 0 else 'raises'} p95 time to first token "
                 f"on chat by {_pct(ttft)} against round-robin")  # fmt: skip
    sub = ("Fixed traffic at 70% of four replicas' saturation rate, 60 s warmup + 180 s measured, "
           "3 repeats. Bar = median, line = min to max, dots = repeats. Red dashes = SLO.")  # fmt: skip
    return _finish(fig, "latency_by_policy", title, sub, _footer(s), bottom_px=130, left=0.075,
                   right=0.98, wspace=0.3, hspace=0.42)  # fmt: skip


def cache_hit_by_policy(s: dict):
    fleet = s["fleet"]
    workloads = [w for w in WORKLOAD_LABEL if w in fleet]
    fig = theme.figure(800)
    ax = fig.subplots()
    width = 0.26
    for k, policy in enumerate(POLICY):
        for j, workload in enumerate(workloads):
            t = fleet[workload]["policies"].get(policy)
            if not t:
                continue
            c = t["cache_hit_rate"]
            x = j + (k - 1) * width
            ax.bar(x, c["median"] * 100, width=width * 0.9, color=POLICY[policy], zorder=2,
                   label=policy if j == 0 else None, hatch=theme.POLICY_HATCH[policy],
                   edgecolor=theme.BG)  # fmt: skip
            ax.plot([x, x], [c["min"] * 100, c["max"] * 100], color=INK, lw=1.3, zorder=3)
            ax.annotate(f"{c['median'] * 100:.0f}%", (x, c["max"] * 100), xytext=(0, 4),
                        textcoords="offset points", ha="center", fontsize=8.5,
                        fontfamily=theme.MONO)  # fmt: skip
    ax.set_xticks(range(len(workloads)), [WORKLOAD_LABEL[w] for w in workloads])
    ax.set_ylabel("prompt tokens from cache (%)")
    ax.set_ylim(0, 105)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right", ncols=3)
    chat = fleet.get("chat", {}).get("policies", {})
    title = "Prefix cache hit rate by routing policy"
    if {"round-robin", "prefix-aware"} <= set(chat):
        a = chat["round-robin"]["cache_hit_rate"]["median"] * 100
        b = chat["prefix-aware"]["cache_hit_rate"]["median"] * 100
        title = f"Prefix-aware routing serves {b:.0f}% of chat prompt tokens from cache, round-robin {a:.0f}%"
    sub = ("Share of prompt tokens vLLM reported as cached (usage.prompt_tokens_details). "
           "Median of 3 repeats, line = min to max.")  # fmt: skip
    return _finish(fig, "cache_hit_by_policy", title, sub, _footer(s), left=0.07, right=0.97)


def router_overhead(s: dict):
    o = s["router_overhead"]
    fig = theme.figure(760)
    ax = fig.subplots()
    names = [p for p in POLICY if p in o["decision_us"]]
    width = 0.25
    for k, (q, shade) in enumerate((("p50", 1.0), ("p95", 0.7), ("p99", 0.45))):
        for j, name in enumerate(names):
            v = o["decision_us"][name][q]
            x = j + (k - 1) * width
            ax.bar(x, v, width=width * 0.9, color=POLICY[name], alpha=shade, zorder=2)
            ax.annotate(f"{q}\n{v}", (x, v), xytext=(0, 4), textcoords="offset points", ha="center",
                        fontsize=8, fontfamily=theme.MONO)  # fmt: skip
    ax.set_xticks(range(len(names)), names)
    ax.set_ylabel("time the router adds per request (microseconds)")
    ax.grid(axis="x", visible=False)
    ax.margins(y=0.25)
    worst = max(o["decision_us"][n]["p99"] for n in names)
    title = f"The router adds at most {worst / 1000:.2f} ms per request at p99"
    sub = "Time from a request arriving at the router to it being forwarded (body read + decision)."
    if "proxycheck" in o:
        c = o["proxycheck"]
        sub += (f" Same requests direct vs through the router on one replica: TTFT p50 "
                f"{c['direct']['ttft_p50_s'] * 1000:.1f} ms vs {c['router']['ttft_p50_s'] * 1000:.1f} ms.")  # fmt: skip
    foot = _footer(s, extra="router and replicas share one container: no network between them")
    return _finish(fig, "router_overhead", title, sub, foot, left=0.07, right=0.97)


def _steps(events: list[dict], duration: float, on: str, off: str) -> list[tuple[float, int]]:
    """Replica count over time, starting from one replica, as (time, count) steps."""
    n, out = 1, [(0.0, 1)]
    for e in events:
        if e["event"] in (on, off):
            n += 1 if e["event"] == on else -1
            out.append((e["t"], n))
    return [*out, (duration, n)]


def autoscaling(s: dict, seed: int = 0):
    static = runs.load(f"fleet-autoscale-chat-static-s{seed}")
    scaled = runs.load(f"fleet-autoscale-chat-autoscaled-s{seed}")
    rows = static.requests
    total = max(static.meta["duration_s"], scaled.meta["duration_s"])
    fig = theme.figure(1200)
    top, mid, low = fig.subplots(3, 1, sharex=True, gridspec_kw={"height_ratios": [1, 1, 1.5]})
    arrivals = [0] * (int(total) + 1)
    for r in rows:
        arrivals[int(r["scheduled_s"])] += 1
    top.bar(range(len(arrivals)), arrivals, width=1.0, color="#4B5563", zorder=2)
    top.set_ylabel("requests / s")
    top.set_title("Traffic (identical for both fleets)")

    events = scaled.meta.get("autoscaler_events") or []
    mid.plot([0, total], [4, 4], color=POLICY["least-loaded"], lw=2, label="static: 4 replicas")
    for on, off, style, width, label in (
        ("start", "stopped", "-", 2, "autoscaled: switched on"),
        ("ready", "drain", DASH, 1.3, "autoscaled: serving"),
    ):
        pts = _steps(events, total, on, off)
        mid.step([p[0] for p in pts], [p[1] for p in pts], where="post", color=ROSE, lw=width,
                 ls=style, label=label)  # fmt: skip
    mid.set_ylim(0, 4.9)
    mid.set_yticks([0, 1, 2, 3, 4])
    mid.set_ylabel("replicas")
    mid.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), ncols=3)

    bucket = 10
    for run, color, marker, label in (
        (static, POLICY["least-loaded"], "s", "static"),
        (scaled, ROSE, "D", "autoscaled"),
    ):
        groups: dict[int, list[float]] = {}
        for r in run.requests:
            groups.setdefault(int(r["scheduled_s"] // bucket), []).append(r.get("ttft_s") or 120.0)
        xs = sorted(groups)
        low.plot([(k + 0.5) * bucket for k in xs], [percentile(groups[k], 95) for k in xs],
                 color=color, marker=marker, ms=4, lw=1.8, label=label)  # fmt: skip
    low.axhline(2.0, color=BAD, lw=1, ls=DASH)
    low.set_yscale("log")
    low.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    low.set_ylabel("p95 time to first token (s, log)")
    low.set_xlabel("seconds since the run started")
    low.legend(loc="upper right", ncols=2)
    a = s.get("autoscale", {})
    saved = a.get("modeled_gpu_seconds_saved")
    title = "Autoscaling on a bursty window"
    if saved is not None and "autoscaled" in a:
        ttft_a, ttft_s = (
            a["autoscaled"]["ttft_p95_s"]["median"],
            a["static"]["ttft_p95_s"]["median"],
        )
        gpu = f"saves {saved * 100:.0f}% of" if saved >= 0 else f"uses {-saved * 100:.0f}% more"
        title = (f"Autoscaling {gpu} GPU-seconds (modeled), and p95 time to first token goes "
                 f"from {ttft_s:.2f} s to {ttft_a:.2f} s")  # fmt: skip
    sub = ("Bursty BurstGPT segment. Latency and replica counts are measured. GPU-seconds are MODELED as if "
           f"each replica were billed alone; in the test all 4 GPUs were billed. Repeat {seed + 1} shown.")  # fmt: skip
    return _finish(fig, "autoscaling", title, sub, _footer(s), left=0.075, right=0.97, hspace=0.36)


# --- single-replica sweep ----------------------------------------------------------


def _configs(s: dict, label: str = "l4", workload: str = "chat") -> list[dict]:
    return s.get("sweep", {}).get(label, {}).get(workload, {}).get("configs", [])


def cost_by_config(s: dict):
    rows = _configs(s)
    ok = sorted((c for c in rows if c["cost_per_m_output"]), key=lambda c: c["cost_per_m_output"])
    failed = [c for c in rows if not c["cost_per_m_output"]]
    fig = theme.figure(380 + 64 * len(rows))
    ax = fig.subplots()
    labels = []
    for k, c in enumerate([*ok, *failed]):
        cost = c["cost_per_m_output"]
        labels.append(c["config"])
        if cost is None:
            ax.text(0.012, k, "misses the SLO at every traffic level tested", va="center",
                    fontsize=9, color=WARN, transform=ax.get_yaxis_transform())  # fmt: skip
            continue
        ax.barh(k, cost, height=0.6, color=ROSE if k == 0 else "#475569", zorder=2)
        more = " or more" if c["capacity_is_lower_bound"] else ""
        ax.annotate(f"${cost:.2f}   {c['max_rps_at_slo']:g} req/s{more}", (cost, k), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9, fontfamily=theme.MONO)  # fmt: skip
    ax.set_yticks(range(len(labels)), labels, fontfamily=theme.MONO, fontsize=9)
    ax.set_ylim(len(labels) - 0.5, -0.5)
    ax.set_xlabel("USD per million output tokens at the SLO (lower is better)")
    ax.grid(axis="y", visible=False)
    ax.margins(x=0.3)
    title = "Cost per million tokens at the SLO, by server config"
    if ok:
        base = next((c for c in ok if c["config"] == "awq"), None)
        title = (f"{ok[0]['config']} is the cheapest config that meets the SLO: "
                 f"${ok[0]['cost_per_m_output']:.2f} per million output tokens")  # fmt: skip
        if base and base is not ok[0]:
            title += f", {_pct(ok[0]['cost_per_m_output'] / base['cost_per_m_output'] - 1)} below the baseline"
    sub = ("One L4, chat workload. Every config ran the same 6-level ramp. Cost = hourly cost / tokens per "
           "hour at its highest level within the SLO. 'or more' = it met the SLO at the top level tested.")  # fmt: skip
    return _finish(
        fig, "cost_by_config", title, sub, _footer(s, "1 x NVIDIA L4"), left=0.17, right=0.96
    )


def pareto(s: dict, y_key: str = "itl_p95_s"):
    fig = theme.figure(980)
    ax = fig.subplots()
    scale = 1000 if y_key == "itl_p95_s" else 1
    k = 0
    every = []
    for label, edge in (("l4", "none"), ("h100", INK)):
        for c in _configs(s, label):
            pts = [
                p for p in c["points"] if p["cost_per_m_output"] and p[y_key] and not p["errors"]
            ]
            if not pts:
                continue
            every += pts
            color, marker = theme.SERIES[k % 12], theme.MARKERS[k % 12]
            k += 1
            xs, ys = [p["cost_per_m_output"] for p in pts], [p[y_key] * scale for p in pts]
            ax.plot(xs, ys, color=color, lw=1, alpha=0.45, zorder=2)
            ax.scatter(xs, ys, s=36, color=color, marker=marker, edgecolor=edge, lw=0.9, zorder=3,
                       label=f"{c['config']} ({label.upper()})")  # fmt: skip
    front = optimizer.pareto(every, y=y_key)
    ax.plot([p["cost_per_m_output"] for p in front], [p[y_key] * scale for p in front], color=INK,
            lw=1.5, alpha=0.8, zorder=1, label="Pareto frontier")  # fmt: skip
    limit = 100 if y_key == "itl_p95_s" else 2.0
    ax.axhline(limit, color=BAD, lw=1, ls=DASH)
    ax.annotate("SLO", (1.0, limit), xycoords=("axes fraction", "data"), xytext=(-4, 4),
                textcoords="offset points", ha="right", color=BAD, fontsize=8.5)  # fmt: skip
    ax.set_xscale("log")
    ax.set_yscale("log")
    for axis, fmt in ((ax.xaxis, "${:g}"), (ax.yaxis, "{:g}")):
        axis.set_major_formatter(FuncFormatter(lambda v, _, fmt=fmt: fmt.format(v)))
        axis.set_minor_formatter(NullFormatter())
    costs = [p["cost_per_m_output"] for p in every]
    x_ticks = (0.2, 0.3, 0.5, 0.7, 1, 1.5, 2, 3, 5, 10)
    ax.set_xticks([t for t in x_ticks if min(costs) * 0.8 <= t <= max(costs) * 1.2])
    lats = [p[y_key] * scale for p in every]
    y_ticks = (
        (20, 30, 50, 70, 100, 150, 200, 300, 500, 1000)
        if scale == 1000
        else (0.1, 0.2, 0.3, 0.5, 1, 2, 5)
    )
    ax.set_yticks([t for t in y_ticks if min(lats) * 0.8 <= t <= max(lats) * 1.2])
    ax.set_xlabel("USD per million output tokens (log scale)")
    ax.set_ylabel(
        "p95 inter-token latency (ms, log scale)"
        if scale == 1000
        else "p95 time to first token (s, log scale)"
    )
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8)
    title = "Cheaper tokens cost latency: every measured operating point and the frontier"
    sub = ("Each marker is one server config at one traffic level of its ramp (lines join a config's levels). "
           "Down and left is better. Levels where requests failed are not drawn.")  # fmt: skip
    return _finish(fig, "pareto", title, sub, _footer(s, "1 GPU per config"), left=0.08, right=0.8)


def spec_decode(s: dict):
    panels = []
    for workload in ("chat", "rag"):
        rows = _configs(s, "l4", workload)
        base = next((c for c in rows if c["config"] == "awq"), None)
        spec = [c for c in rows if c["speculative"] != "off"]
        if base and spec:
            panels.append((workload, base, spec))
    fig = theme.figure(900)
    axes = fig.subplots(2, len(panels), squeeze=False)
    best = None
    for j, (workload, base, spec) in enumerate(panels):
        names = [c["config"].replace("awq-", "") for c in spec]
        ratios = [
            c["max_rps_at_slo"] / base["max_rps_at_slo"] if base["max_rps_at_slo"] else 0
            for c in spec
        ]
        accept = [((c.get("spec_decode") or {}).get("acceptance_rate") or 0) * 100 for c in spec]
        if workload == "chat":
            best = max(zip(ratios, names, strict=True))
        for ax, values, fmt, ylabel in (
            (axes[0][j], ratios, "{:.2f}x", "capacity at the SLO vs no speculation"),
            (axes[1][j], accept, "{:.0f}%", "draft tokens accepted (%)"),
        ):
            ax.bar(range(len(names)), values, width=0.55, color=theme.SERIES[2], zorder=2)
            for k, v in enumerate(values):
                ax.annotate(fmt.format(v), (k, v), xytext=(0, 4), textcoords="offset points",
                            ha="center", fontsize=9, fontfamily=theme.MONO)  # fmt: skip
            ax.set_xticks(range(len(names)), names)
            ax.set_ylabel(ylabel, fontsize=8.5)
            ax.grid(axis="x", visible=False)
            ax.margins(y=0.22)
            ax.set_ylim(bottom=0)
        axes[0][j].axhline(1.0, color=MUTED, lw=1, ls=DASH)
        axes[0][j].set_title(f"{workload}: capacity relative to the baseline", color=INK)
        axes[1][j].set_title(f"{workload}: acceptance rate")
    title = "Speculative decoding: capacity and acceptance rate"
    if best:
        ratio, name = best
        if ratio > 1.02:
            title = f"Speculative decoding ({name}) raises single-GPU capacity at the SLO by {_pct(ratio - 1)} on chat"
        elif ratio < 0.98:
            title = f"Speculative decoding lowers single-GPU capacity at the SLO on chat (best: {name}, {_pct(1 - ratio)} lower)"
        else:
            title = "Speculative decoding does not change single-GPU capacity at the SLO on chat"
    sub = ("One L4, AWQ weights. Capacity = highest ramp level within the SLO (steps of about 15%). "
           "Acceptance = accepted / proposed draft tokens, from vLLM's counters.")  # fmt: skip
    return _finish(fig, "spec_decode", title, sub, _footer(s, "1 x NVIDIA L4"), left=0.08, right=0.97,
                   wspace=0.25, hspace=0.5)  # fmt: skip


def quantization(s: dict):
    rows = [c for c in _configs(s) if c.get("gsm8k") and c["speculative"] == "off"
            and c["prefix_caching"] and c["max_num_seqs"] == 128]  # fmt: skip
    fig = theme.figure(820)
    ax = fig.subplots()
    for k, c in enumerate(rows):
        g = c["gsm8k"]
        acc, n = g["accuracy"], g["questions"]
        half = 1.96 * math.sqrt(acc * (1 - acc) / n) * 100  # normal-approximation 95% interval
        x = c["max_rps_at_slo"]
        ax.errorbar(x, acc * 100, yerr=half, color=theme.SERIES[k], marker=theme.MARKERS[k], ms=9,
                    capsize=4, lw=1.4, zorder=3)  # fmt: skip
        more = " or more" if c["capacity_is_lower_bound"] else ""
        cost = (
            f"${c['cost_per_m_output']:.2f} per M tokens"
            if c["cost_per_m_output"]
            else "misses the SLO"
        )
        ax.annotate(f"{c['quantization']}\n{acc * 100:.1f}%  ·  {x:g} req/s{more}  ·  {cost}",
                    (x, acc * 100), xytext=(12, 0), textcoords="offset points", va="center", fontsize=9)  # fmt: skip
    ax.set_xlabel("capacity at the SLO on one L4, chat workload (requests per second)")
    ax.set_ylabel("GSM8K accuracy (%), 250 questions")
    ax.margins(x=0.4, y=0.5)
    title = "Quantization: speed against GSM8K accuracy"
    if len(rows) > 1:
        fast = max(rows, key=lambda c: c["max_rps_at_slo"])
        accs = [c["gsm8k"]["accuracy"] * 100 for c in rows]
        title = (f"{fast['quantization']} carries the most traffic on an L4, and GSM8K accuracy stays within "
                 f"{max(accs) - min(accs):.1f} points across quantizations")  # fmt: skip
    sub = ("Bars are 95% intervals for 250 questions (about 3 points each way), so small accuracy gaps are "
           "within noise. Greedy decoding, same prompt for every config.")  # fmt: skip
    return _finish(
        fig, "quantization", title, sub, _footer(s, "1 x NVIDIA L4"), left=0.08, right=0.96
    )


CHARTS = {
    "capacity_by_policy": (capacity_by_policy, lambda s: "capacity" in s),
    "latency_by_policy": (latency_by_policy, lambda s: bool(s.get("fleet"))),
    "cache_hit_by_policy": (cache_hit_by_policy, lambda s: bool(s.get("fleet"))),
    "cost_by_config": (cost_by_config, lambda s: bool(_configs(s))),
    "pareto": (pareto, lambda s: bool(_configs(s))),
    "spec_decode": (spec_decode, lambda s: any(c["speculative"] != "off" for c in _configs(s))),
    "quantization": (quantization, lambda s: sum(1 for c in _configs(s) if c.get("gsm8k")) > 1),
    "autoscaling": (autoscaling, lambda s: "autoscaled" in s.get("autoscale", {})),
    "router_overhead": (
        router_overhead,
        lambda s: bool(s.get("router_overhead", {}).get("decision_us")),
    ),
}


def write_all() -> dict[str, str]:
    """Draw every chart whose data exists. Returns name -> 'written' or 'skipped: no data yet'."""
    s = load_summary()
    status = {}
    for name, (draw, ready) in CHARTS.items():
        if ready(s):
            draw(s)
            status[name] = "written"
        else:
            status[name] = "skipped: no data yet"
    return status
