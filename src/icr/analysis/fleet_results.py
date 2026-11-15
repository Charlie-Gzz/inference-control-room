"""Fleet results (M4): policy comparison, capacity at the SLO, autoscaling, router overhead.

Everything is recomputed from the saved request records. Repeats are reported as
median with min and max, and a spread above 10% of the median is flagged.
"""

from __future__ import annotations

import statistics

from icr.analysis import metrics
from icr.analysis.metrics import DEFAULT_SLO, SLO
from icr.analysis.runs import Run, all_runs

POLICIES = ("round-robin", "least-loaded", "prefix-aware")
WORKLOADS = ("chat", "rag", "no-sharing", "agentic")
COMPARED = (
    "ttft_p50_s", "ttft_p95_s", "itl_p95_s", "e2e_p95_s", "goodput", "cache_hit_rate",
    "imbalance", "output_tokens_per_s", "errors",
)  # fmt: skip
SPREAD_LIMIT = 0.10


def spread(values: list[float | None]) -> dict:
    """Median, min and max of the repeats. `wide` flags a spread above 10% of the median."""
    known = [v for v in values if v is not None]
    if not known:
        return {"median": None, "min": None, "max": None, "values": values, "wide": False}
    median = statistics.median(known)
    wide = bool(median) and (max(known) - min(known)) / abs(median) > SPREAD_LIMIT
    return {
        "median": round(median, 5), "min": min(known), "max": max(known), "values": values,
        "wide": wide,
    }  # fmt: skip


def _fleet_runs(kind: str, workload: str | None = None) -> list[Run]:
    prefix = f"fleet-{kind}-" + (f"{workload}-" if workload else "")
    found = [r for r in all_runs(prefix) if not r.run_id.endswith("-direct")]
    # "chat" is a prefix of nothing else, but keep the match exact anyway.
    return [r for r in found if workload is None or r.meta["workload"] == workload]


def run_summary(run: Run, slo: SLO = DEFAULT_SLO) -> dict:
    return metrics.summarize(run.requests, slo, replicas=run.meta.get("replicas"))


def policy_table(workload: str, slo: SLO = DEFAULT_SLO) -> dict:
    """Fixed-traffic comparison on one workload: policy -> metric -> spread over repeats."""
    by_policy: dict[str, dict[int, dict]] = {}
    rate = replicas = None
    for run in _fleet_runs("fixed", workload):
        by_policy.setdefault(run.meta["policy"], {})[run.meta["seed"]] = run_summary(run, slo)
        rate, replicas = run.meta["run"]["rate_rps"], run.meta.get("replicas")
    table = {}
    for policy in POLICIES:
        seeds = by_policy.get(policy)
        if not seeds:
            continue
        ordered = [seeds[s] for s in sorted(seeds)]
        table[policy] = {
            "repeats": len(ordered),
            "seeds": sorted(seeds),
            "requests": [s["requests"] for s in ordered],
            **{m: spread([s.get(m) for s in ordered]) for m in COMPARED},
        }
    return {"workload": workload, "rate_rps": rate, "replicas": replicas, "policies": table}


def capacity_table(slo: SLO = DEFAULT_SLO) -> dict:
    """Capacity ramp on chat: per policy, the highest traffic level that meets the SLO."""
    by_policy: dict[str, list[dict]] = {}
    rates: list[float] = []
    level_s = None
    for run in sorted(_fleet_runs("ramp"), key=lambda r: r.meta["seed"]):
        spec = run.meta["run"]
        rates, level_s = spec["rates_rps"], spec["level_s"]
        levels = metrics.by_level(run.requests, slo)
        cap = metrics.capacity(levels, rates, spec["level_s"])
        hourly = run.meta["cost_per_hour_usd"]
        by_policy.setdefault(run.meta["policy"], []).append(
            {
                "seed": run.meta["seed"],
                "levels": [
                    {
                        "rate_rps": rates[lv["level"]],
                        "meets_slo": lv["meets_slo"],
                        "ttft_p95_s": lv["ttft_p95_s"],
                        "itl_p95_s": lv["itl_p95_s"],
                        "goodput": lv["goodput"],
                        "errors": lv["errors"],
                        "cache_hit_rate": lv["cache_hit_rate"],
                    }
                    for lv in levels
                ],
                "max_rps_at_slo": cap["max_rps_at_slo"],
                "at_top_level": cap["level"] == len(rates) - 1,
                "output_tokens_per_hour": cap["output_tokens_per_hour_at_slo"],
                "cost_per_hour_usd": hourly,
                "cost_per_m_output": metrics.cost_per_million(
                    hourly, cap["output_tokens_per_hour_at_slo"]
                ),
                "cost_per_m_total": metrics.cost_per_million(
                    hourly, cap.get("total_tokens_per_hour_at_slo", 0)
                ),
            }
        )
    table = {}
    for policy in POLICIES:
        repeats = by_policy.get(policy)
        if not repeats:
            continue
        table[policy] = {
            "repeats": repeats,
            "max_rps_at_slo": spread([r["max_rps_at_slo"] for r in repeats]),
            "cost_per_m_output": spread([r["cost_per_m_output"] for r in repeats]),
            "cost_per_m_total": spread([r["cost_per_m_total"] for r in repeats]),
            "output_tokens_per_hour": spread([r["output_tokens_per_hour"] for r in repeats]),
            "lower_bound": any(r["at_top_level"] for r in repeats),
        }
    return {"workload": "chat", "rates_rps": rates, "level_s": level_s, "policies": table}


def _change(new: float | None, old: float | None) -> float | None:
    """Relative change from old to new, e.g. -0.25 for a 25% cut."""
    if new is None or not old:
        return None
    return new / old - 1


def headline(chat: dict, capacity: dict, a: str = "round-robin", b: str = "prefix-aware") -> dict:
    """The headline sentence, built from whatever the numbers are."""
    pa, rr = chat["policies"].get(b), chat["policies"].get(a)
    if not pa or not rr:
        return {}
    ttft = _change(pa["ttft_p95_s"]["median"], rr["ttft_p95_s"]["median"])
    cap_b, cap_a = capacity["policies"].get(b), capacity["policies"].get(a)
    cap = cost = None
    if cap_a and cap_b:
        cap = _change(cap_b["max_rps_at_slo"]["median"], cap_a["max_rps_at_slo"]["median"])
        cost = _change(cap_b["cost_per_m_output"]["median"], cap_a["cost_per_m_output"]["median"])

    def pct(x: float) -> str:
        return f"{abs(x) * 100:.0f}%"

    first = (
        f"{b} routing {'cut' if ttft < 0 else 'raised'} p95 time to first token by "
        f"<b>{pct(ttft)}</b> versus {a}"
    )
    if cap is None:
        second = ""
    elif abs(cap) < 0.005:
        second = ", and served the same traffic within the SLO, so cost per million tokens is equal"
    else:
        more = cap > 0
        second = (
            f", {'and' if more == (ttft < 0) else 'but'} served <b>{pct(cap)}</b> "
            f"{'more' if more else 'less'} traffic within the SLO"
        )
        if cost is not None:
            second += (
                f", which is <b>{pct(cost)}</b> {'lower' if cost < 0 else 'higher'} "
                "cost per million tokens"
            )
    html = f"On the same {chat.get('replicas') or 4} GPUs and the same traffic, {first}{second}."
    text = html.replace("<b>", "").replace("</b>", "")
    return {
        "ttft_p95_change": ttft, "capacity_change": cap, "cost_change": cost,
        "ttft_p95_s": {a: rr["ttft_p95_s"]["median"], b: pa["ttft_p95_s"]["median"]},
        "html": html[0].upper() + html[1:], "text": text,
        "tour": "Both sides got exactly the same requests at the same times. " + text,
    }  # fmt: skip


def autoscale_table(slo: SLO = DEFAULT_SLO) -> dict:
    """Static fleet vs autoscaled fleet on the bursty window.

    GPU-seconds are MODELED: a replica counts from the moment the autoscaler starts it
    (startup included) until it is stopped, as if each replica were billed on its own.
    In the real container all four GPUs are billed for the whole run. Both fleets are
    counted over the same window, the planned traffic window (warmup + measured).
    """
    rows: dict[str, list[dict]] = {}
    for run in sorted(_fleet_runs("autoscale"), key=lambda r: r.meta["seed"]):
        summary = run_summary(run, slo)
        spec = run.meta["run"]
        duration = spec["warmup_s"] + spec["measured_s"]  # the traffic window, same for both
        replicas = run.meta["replicas"]
        row = {
            "seed": run.meta["seed"],
            "duration_s": duration,
            "ttft_p50_s": summary["ttft_p50_s"],
            "ttft_p95_s": summary["ttft_p95_s"],
            "itl_p95_s": summary["itl_p95_s"],
            "goodput": summary["goodput"],
            "errors": summary["errors"],
            "gpu_seconds": round(replicas * duration, 1),
        }
        if run.meta["policy"] == "autoscaled":
            events = run.meta.get("autoscaler_events") or []
            row["gpu_seconds"] = round(modeled_gpu_seconds(events, duration), 1)
            row["events"] = events
            startups = [e["startup_s"] for e in events if e["event"] == "ready"]
            row["scale_ups"] = len(startups)
            row["startup_s"] = startups
        rows.setdefault(run.meta["policy"], []).append(row)
    out = {
        variant: {
            "repeats": repeats,
            **{
                m: spread([r[m] for r in repeats])
                for m in ("ttft_p50_s", "ttft_p95_s", "itl_p95_s", "goodput", "gpu_seconds")
            },
        }
        for variant, repeats in rows.items()
    }
    if {"static", "autoscaled"} <= set(out):
        saved = _change(
            out["autoscaled"]["gpu_seconds"]["median"], out["static"]["gpu_seconds"]["median"]
        )
        out["modeled_gpu_seconds_saved"] = None if saved is None else round(-saved, 4)
    return out


def modeled_gpu_seconds(events: list[dict], duration_s: float, initial: int = 1) -> float:
    """Replica-active seconds of an autoscaled run (modeled, see `autoscale_table`)."""
    total = initial * duration_s  # the initial replicas run the whole time
    started: dict[int, float] = {}
    for e in events:
        t = min(e["t"], duration_s)  # only the traffic window counts, for both fleets
        if e["event"] == "start":
            started[e["replica"]] = t
        elif e["event"] == "stopped":
            if e["replica"] in started:
                total += t - started.pop(e["replica"])
            else:  # an initial replica was stopped
                total -= duration_s - t
    return total + sum(duration_s - t for t in started.values())


def router_overhead() -> dict:
    """What the router adds: its own timer on every routed request, and the proxy check."""
    by_policy: dict[str, list[int]] = {}
    for run in all_runs("fleet-"):
        if run.meta.get("policy") in (None, "direct"):
            continue
        policy = run.meta.get("run", {}).get("router_policy", run.meta["policy"])
        values = [
            r["router_overhead_us"] for r in run.requests
            if r.get("router_overhead_us") is not None
        ]  # fmt: skip
        by_policy.setdefault(policy, []).extend(values)
    out: dict = {"decision_us": {}}
    for policy, values in by_policy.items():
        if policy in POLICIES and values:
            out["decision_us"][policy] = {
                "requests": len(values),
                "p50": round(metrics.percentile(values, 50)),
                "p95": round(metrics.percentile(values, 95)),
                "p99": round(metrics.percentile(values, 99)),
            }
    proxied = [r for r in all_runs("fleet-proxycheck-") if not r.run_id.endswith("-direct")]
    direct = [r for r in all_runs("fleet-proxycheck-") if r.run_id.endswith("-direct")]
    if proxied and direct:
        a, b = run_summary(direct[0]), run_summary(proxied[0])
        out["proxycheck"] = {
            "requests": a["requests"],
            "direct": {k: a[k] for k in ("ttft_p50_s", "ttft_p95_s", "itl_p95_s")},
            "router": {k: b[k] for k in ("ttft_p50_s", "ttft_p95_s", "itl_p95_s")},
            "added_ttft_p50_ms": round((b["ttft_p50_s"] - a["ttft_p50_s"]) * 1000, 2),
        }
    return out
