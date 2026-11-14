"""Operating points, capacity under an SLO, the cheapest config and the Pareto frontier."""

from icr.analysis import optimizer
from icr.analysis.metrics import SLO


def point(config, level, ttft, itl=0.05, cost=1.0, errors=0):
    return {
        "config": config, "level": level, "ttft_p95_s": ttft, "itl_p95_s": itl,
        "errors": errors, "cost_per_m_output": cost,
    }  # fmt: skip


def records(level, n, ttft, tokens=100):
    return [
        {
            "phase": "measured", "level": level, "scheduled_s": level * 10 + i * 0.1,
            "sent_s": level * 10 + i * 0.1, "end_s": level * 10 + i * 0.1 + 1, "ttft_s": ttft,
            "itl_s": 0.02, "e2e_s": 1.0, "prompt_tokens": 500, "cached_tokens": 100,
            "completion_tokens": tokens, "error": "",
        }
        for i in range(n)
    ]  # fmt: skip


def test_operating_points_turn_tokens_into_cost():
    rows = records(0, 10, 0.3) + records(1, 20, 0.9)
    points = optimizer.operating_points("awq", rows, [1.0, 2.0], level_s=10.0, cost_per_hour=1.0)
    assert [p["rate_rps"] for p in points] == [1.0, 2.0]
    assert points[0]["output_tokens_per_hour"] == 10 * 100 * 360
    # Twice the tokens for the same hourly cost: half the cost per token.
    assert points[1]["cost_per_m_output"] == points[0]["cost_per_m_output"] / 2
    assert points[0]["cost_per_m_total"] < points[0]["cost_per_m_output"]


def test_capacity_stops_at_the_first_level_that_misses_the_slo():
    points = [point("a", 0, 0.5), point("a", 1, 1.5), point("a", 2, 3.0), point("a", 3, 1.0)]
    assert optimizer.capacity_point(points)["level"] == 1  # level 3 passes but comes after a miss
    assert optimizer.capacity_point(points, SLO(ttft_s=0.4)) is None
    assert optimizer.capacity_point(points, SLO(ttft_s=5.0))["level"] == 3


def test_errors_and_slow_tokens_fail_a_level():
    assert not optimizer.point_meets(point("a", 0, 0.5, errors=1))
    assert not optimizer.point_meets(point("a", 0, 0.5, itl=0.2))
    assert optimizer.point_meets(point("a", 0, 0.5, itl=None))


def test_top_level_capacity_is_flagged_as_a_lower_bound():
    points = [point("a", 0, 0.5), point("a", 1, 0.6)]
    assert optimizer.at_top_level(points, optimizer.capacity_point(points))
    assert not optimizer.at_top_level(points, points[0])


def test_cheapest_config_depends_on_the_slo():
    configs = {
        "fast": [point("fast", 0, 0.2, cost=4.0), point("fast", 1, 0.4, cost=2.0)],
        "cheap": [point("cheap", 0, 0.8, cost=1.5), point("cheap", 1, 1.8, cost=0.8)],
    }
    assert optimizer.cheapest(configs)["config"] == "cheap"
    assert optimizer.cheapest(configs, SLO(ttft_s=0.5))["config"] == "fast"
    assert optimizer.cheapest(configs, SLO(ttft_s=0.1)) is None


def test_pareto_keeps_only_points_nothing_else_beats():
    points = [
        point("a", 0, 0.2, cost=4.0),
        point("a", 1, 0.5, cost=2.0),
        point("b", 0, 0.6, cost=3.0),  # beaten by a/1 on both axes
        point("b", 1, 1.5, cost=1.0),
        point("c", 0, None, cost=0.5),  # no latency: not usable
    ]
    frontier = optimizer.pareto(points)
    assert [(p["config"], p["level"]) for p in frontier] == [("b", 1), ("a", 1), ("a", 0)]
