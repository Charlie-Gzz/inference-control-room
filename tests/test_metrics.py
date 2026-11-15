"""Metric definitions: percentiles, goodput, capacity at the SLO, cost."""

import pytest

from icr.analysis import metrics
from icr.analysis.metrics import SLO


def record(i, ttft=0.5, itl=0.03, level=0, phase="measured", error="", out=100):
    return {
        "id": i, "phase": phase, "level": level, "scheduled_s": float(i), "sent_s": float(i),
        "ttft_s": ttft, "itl_s": itl, "e2e_s": ttft + itl * out, "end_s": i + ttft + itl * out,
        "prompt_tokens": 1000, "cached_tokens": 600, "completion_tokens": out, "replica": i % 2,
        "error": error,
    }  # fmt: skip


def test_percentile_interpolates():
    assert metrics.percentile([1, 2, 3, 4, 5], 50) == 3
    assert metrics.percentile([0, 10], 95) == pytest.approx(9.5)
    assert metrics.percentile([], 95) is None


def test_a_stream_cut_off_before_its_usage_block_counts_as_failed():
    cut = {**record(1), "completion_tokens": None}  # first token arrived, then the server died
    assert metrics.failed(cut) and not metrics.is_good(cut)
    assert not metrics.failed(record(2))
    summary = metrics.summarize([record(0), cut])
    assert summary["errors"] == 1 and summary["output_tokens"] == 100


def test_summary_excludes_warmup_and_counts_errors():
    rows = [record(0, phase="warmup", ttft=99)] + [record(i) for i in range(1, 11)]
    rows.append(record(11, error="boom"))
    s = metrics.summarize(rows)
    assert s["requests"] == 11 and s["errors"] == 1
    assert s["ttft_p95_s"] == 0.5
    assert s["cache_hit_rate"] == 0.6
    assert s["goodput"] == pytest.approx(10 / 11, abs=1e-4)
    assert s["replica_requests"] == [5, 5] and s["imbalance"] == 1.0


def test_goodput_needs_both_limits():
    slo = SLO(ttft_s=1.0, itl_s=0.05)
    assert metrics.is_good(record(0, ttft=0.9, itl=0.04), slo)
    assert not metrics.is_good(record(0, ttft=1.1, itl=0.04), slo)
    assert not metrics.is_good(record(0, ttft=0.9, itl=0.06), slo)
    assert not metrics.is_good(record(0, error="x"), slo)


def test_capacity_is_the_last_level_before_the_first_miss():
    rows = []
    for level, ttft in enumerate([0.3, 0.8, 3.0, 0.4]):  # level 3 passes but comes after a miss
        rows += [record(level * 100 + i, ttft=ttft, level=level) for i in range(20)]
    levels = metrics.by_level(rows)
    assert [lv["meets_slo"] for lv in levels] == [True, True, False, True]
    cap = metrics.capacity(levels, rates_rps=[2.0, 4.0, 6.0, 8.0], level_s=60.0)
    assert cap["max_rps_at_slo"] == 4.0
    assert cap["output_tokens_per_hour_at_slo"] == 20 * 100 * 60


def test_capacity_is_zero_when_the_first_level_misses():
    levels = metrics.by_level([record(i, ttft=5.0) for i in range(10)])
    assert metrics.capacity(levels, [2.0], 60.0)["max_rps_at_slo"] == 0.0


def test_cost_per_million_tokens():
    assert metrics.cost_per_million(4.0, 8_000_000) == 0.5
    assert metrics.cost_per_million(4.0, 0) is None
