"""Cost/latency frontier and the cheapest config for a latency target.

An *operating point* is one server config at one traffic level of its ramp: how many
tokens per hour it produced there, what that costs per million tokens, and the latency
users saw. Running a config hotter makes tokens cheaper and latency worse, so each
config traces a curve, and the best points across all configs form the Pareto frontier.

Capacity rule (frozen in docs/DECISIONS.md): a config's capacity under an SLO is its
highest traffic level that meets the SLO with every lower level also meeting it.
"""

from __future__ import annotations

from icr.analysis.metrics import DEFAULT_SLO, SLO, by_level, cost_per_million


def operating_points(
    name: str, records: list[dict], rates_rps: list[float], level_s: float, cost_per_hour: float
) -> list[dict]:
    """One point per traffic level of a ramp, lowest traffic first."""
    points = []
    for level in by_level(records):
        output_per_hour = level["output_tokens"] / level_s * 3600
        total_per_hour = (level["output_tokens"] + level["prompt_tokens"]) / level_s * 3600
        points.append(
            {
                "config": name,
                "level": level["level"],
                "rate_rps": rates_rps[level["level"]],
                "requests": level["requests"],
                "errors": level["errors"],
                "ttft_p50_s": level["ttft_p50_s"],
                "ttft_p95_s": level["ttft_p95_s"],
                "itl_p95_s": level["itl_p95_s"],
                "goodput": level["goodput"],
                "cache_hit_rate": level["cache_hit_rate"],
                "output_tokens_per_hour": round(output_per_hour),
                "total_tokens_per_hour": round(total_per_hour),
                "cost_per_m_output": cost_per_million(cost_per_hour, output_per_hour),
                "cost_per_m_total": cost_per_million(cost_per_hour, total_per_hour),
            }
        )
    return points


def point_meets(point: dict, slo: SLO = DEFAULT_SLO) -> bool:
    if point["errors"] or point["ttft_p95_s"] is None:
        return False
    itl = point["itl_p95_s"]
    return point["ttft_p95_s"] <= slo.ttft_s and (itl is None or itl <= slo.itl_s)


def capacity_point(points: list[dict], slo: SLO = DEFAULT_SLO) -> dict | None:
    """The config's best allowed operating point under `slo`, or None if even level 0 fails."""
    best = None
    for point in sorted(points, key=lambda p: p["level"]):
        if not point_meets(point, slo):
            break
        best = point
    return best


def at_top_level(points: list[dict], point: dict | None) -> bool:
    """True when the capacity point is the highest level tested (capacity may be higher)."""
    return point is not None and point["level"] == max(p["level"] for p in points)


def cheapest(configs: dict[str, list[dict]], slo: SLO = DEFAULT_SLO) -> dict | None:
    """Across configs, the capacity point with the lowest cost per million output tokens."""
    candidates = [p for p in (capacity_point(pts, slo) for pts in configs.values()) if p]
    return min(candidates, key=lambda p: p["cost_per_m_output"], default=None)


def pareto(points: list[dict], x: str = "cost_per_m_output", y: str = "ttft_p95_s") -> list[dict]:
    """Points that no other point beats on both `x` and `y` (lower is better), sorted by x."""
    usable = [p for p in points if p.get(x) is not None and p.get(y) is not None]
    frontier: list[dict] = []
    best_y = float("inf")
    for p in sorted(usable, key=lambda p: (p[x], p[y])):
        if p[y] < best_y:
            frontier.append(p)
            best_y = p[y]
    return frontier
