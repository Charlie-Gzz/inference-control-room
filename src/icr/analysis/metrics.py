"""Metrics computed from a run's request records. Pure functions, no GPU, no network.

Records are dicts (lines of requests.jsonl). Only `phase == "measured"` requests count.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SLO:
    """Latency target. A request is good if it meets both limits and did not fail."""

    ttft_s: float = 2.0  # time to first token, from the scheduled arrival
    itl_s: float = 0.1  # mean time between output tokens


DEFAULT_SLO = SLO()


def percentile(values: list[float], q: float) -> float | None:
    """q-th percentile (0 to 100) with linear interpolation. None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def is_good(record: dict, slo: SLO = DEFAULT_SLO) -> bool:
    if record.get("error") or record.get("ttft_s") is None:
        return False
    itl = record.get("itl_s")
    return record["ttft_s"] <= slo.ttft_s and (itl is None or itl <= slo.itl_s)


def measured(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("phase") == "measured"]


def summarize(records: list[dict], slo: SLO = DEFAULT_SLO, replicas: int | None = None) -> dict:
    """Headline metrics for one run (or one traffic level of a ramp)."""
    rows = measured(records)
    ok = [r for r in rows if not r.get("error") and r.get("ttft_s") is not None]
    if not rows:
        return {"requests": 0}
    ttft = [r["ttft_s"] for r in ok]
    itl = [r["itl_s"] for r in ok if r.get("itl_s") is not None]
    prompt = sum(r.get("prompt_tokens") or 0 for r in ok)
    cached = sum(r.get("cached_tokens") or 0 for r in ok)
    output = sum(r.get("completion_tokens") or 0 for r in ok)
    start = min(r["scheduled_s"] for r in rows)
    span = max(max((r.get("end_s") or 0) for r in rows) - start, 1e-9)
    window = max(max(r["scheduled_s"] for r in rows) - start, 1e-9)
    summary = {
        "requests": len(rows),
        "errors": len(rows) - len(ok),
        "offered_rps": round(len(rows) / window, 3),
        "ttft_p50_s": _round(percentile(ttft, 50)),
        "ttft_p95_s": _round(percentile(ttft, 95)),
        "itl_p95_s": _round(percentile(itl, 95), 5),
        "e2e_p95_s": _round(percentile([r["e2e_s"] for r in ok], 95)),
        "goodput": round(sum(is_good(r, slo) for r in rows) / len(rows), 4),
        "output_tokens": output,
        "prompt_tokens": prompt,
        "output_tokens_per_s": round(output / span, 1),
        "cache_hit_rate": round(cached / prompt, 4) if prompt else 0.0,
        "send_lag_p95_s": _round(percentile([r["sent_s"] - r["scheduled_s"] for r in rows], 95)),
    }
    overheads = [r["router_overhead_us"] for r in ok if r.get("router_overhead_us") is not None]
    if overheads:
        summary["router_overhead_p50_us"] = round(percentile(overheads, 50))
        summary["router_overhead_p95_us"] = round(percentile(overheads, 95))
    counts = _replica_counts(ok, replicas)
    if len(counts) > 1:
        mean = sum(counts) / len(counts)
        summary["replica_requests"] = counts
        summary["imbalance"] = round(max(counts) / mean, 3) if mean else None  # 1.0 = even
    return summary


def meets_slo(summary: dict, slo: SLO = DEFAULT_SLO) -> bool:
    """A run or level meets the SLO if p95 TTFT and p95 ITL are within it and nothing failed."""
    if not summary.get("requests") or summary.get("errors"):
        return False
    ttft, itl = summary.get("ttft_p95_s"), summary.get("itl_p95_s")
    return ttft is not None and ttft <= slo.ttft_s and (itl is None or itl <= slo.itl_s)


def by_level(records: list[dict], slo: SLO = DEFAULT_SLO) -> list[dict]:
    """Per traffic level of a ramp: the summary plus whether the level met the SLO."""
    levels = sorted({r["level"] for r in measured(records)})
    out = []
    for level in levels:
        summary = summarize([r for r in records if r["level"] == level], slo)
        out.append({"level": level, **summary, "meets_slo": meets_slo(summary, slo)})
    return out


def capacity(levels: list[dict], rates_rps: list[float], level_s: float) -> dict:
    """Highest traffic level that meets the SLO, with every lower level meeting it too."""
    best = None
    for level in levels:
        if not level["meets_slo"]:
            break
        best = level
    if best is None:
        return {"max_rps_at_slo": 0.0, "output_tokens_per_hour_at_slo": 0.0, "level": None}
    return {
        "max_rps_at_slo": rates_rps[best["level"]],
        "output_tokens_per_hour_at_slo": round(best["output_tokens"] / level_s * 3600),
        "total_tokens_per_hour_at_slo": round(
            (best["output_tokens"] + best["prompt_tokens"]) / level_s * 3600
        ),
        "level": best["level"],
    }


def cost_per_million(cost_per_hour: float, tokens_per_hour: float) -> float | None:
    """Cost per million tokens at the SLO: hourly cost divided by hourly tokens at capacity."""
    if not tokens_per_hour:
        return None
    return round(cost_per_hour / tokens_per_hour * 1e6, 4)


def _replica_counts(rows: list[dict], replicas: int | None) -> list[int]:
    ids = [r["replica"] for r in rows if r.get("replica") is not None]
    n = replicas or (max(ids) + 1 if ids else 0)
    return [ids.count(i) for i in range(n)]


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)
