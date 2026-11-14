"""Fleet analysis: repeat spreads, the headline sentence, modeled GPU-seconds, full tables."""

import json

import pytest

from icr import config
from icr.analysis import fleet_results, runs


def test_spread_reports_median_range_and_flags_wide_repeats():
    tight = fleet_results.spread([1.00, 1.04, 1.08])
    assert tight["median"] == 1.04 and tight["min"] == 1.0 and tight["max"] == 1.08
    assert tight["wide"] is False
    assert fleet_results.spread([1.0, 1.2, 1.5])["wide"] is True
    assert fleet_results.spread([None, None])["median"] is None


def _chat(rr_ttft, pa_ttft):
    s = fleet_results.spread
    return {
        "policies": {
            "round-robin": {"ttft_p95_s": s([rr_ttft])},
            "prefix-aware": {"ttft_p95_s": s([pa_ttft])},
        }
    }


def _capacity(rr_rps, pa_rps, rr_cost, pa_cost):
    s = fleet_results.spread
    return {
        "policies": {
            "round-robin": {"max_rps_at_slo": s([rr_rps]), "cost_per_m_output": s([rr_cost])},
            "prefix-aware": {"max_rps_at_slo": s([pa_rps]), "cost_per_m_output": s([pa_cost])},
        }
    }


def test_headline_states_a_win_with_the_real_numbers():
    h = fleet_results.headline(_chat(1.0, 0.6), _capacity(10.0, 12.5, 1.0, 0.8))
    assert h["ttft_p95_change"] == pytest.approx(-0.4)
    assert h["capacity_change"] == pytest.approx(0.25)
    assert h["cost_change"] == pytest.approx(-0.2)
    assert "cut p95 time to first token by 40%" in h["text"]
    assert "and served 25% more traffic within the SLO" in h["text"]
    assert "20% lower cost per million tokens" in h["text"]
    assert "<b>" in h["html"] and "<b>" not in h["text"]


def test_headline_states_a_loss_just_as_plainly():
    h = fleet_results.headline(_chat(1.0, 1.3), _capacity(10.0, 9.0, 1.0, 1.11))
    assert "raised p95 time to first token by 30%" in h["text"]
    assert "served 10% less traffic within the SLO" in h["text"]
    assert "11% higher cost per million tokens" in h["text"]


def test_headline_handles_a_mixed_result_and_a_tie():
    mixed = fleet_results.headline(_chat(1.0, 0.5), _capacity(10.0, 9.0, 1.0, 1.11))
    assert "cut p95 time to first token by 50%" in mixed["text"]
    assert "but served 10% less traffic" in mixed["text"]
    tie = fleet_results.headline(_chat(1.0, 0.5), _capacity(10.0, 10.0, 1.0, 1.0))
    assert "served the same traffic within the SLO" in tie["text"]


def test_headline_without_a_capacity_ramp_only_reports_latency():
    h = fleet_results.headline(_chat(2.0, 1.0), {"policies": {}})
    assert h["capacity_change"] is None
    assert h["text"].endswith("cut p95 time to first token by 50% versus round-robin.")


def test_modeled_gpu_seconds_count_from_start_to_stop():
    events = [
        {"t": 100.0, "event": "start", "replica": 1},
        {"t": 180.0, "event": "ready", "replica": 1},
        {"t": 300.0, "event": "drain", "replica": 1},
        {"t": 310.0, "event": "stopped", "replica": 1},
        {"t": 400.0, "event": "start", "replica": 1},  # still running at the end
    ]
    # Replica 0 runs all 480 s; replica 1 runs 100..310 and 400..480.
    assert fleet_results.modeled_gpu_seconds(events, 480.0) == 480 + 210 + 80
    assert fleet_results.modeled_gpu_seconds([], 480.0) == 480
    # Only the traffic window counts: a replica stopped during the drain is cut at the window.
    late = [
        {"t": 400.0, "event": "start", "replica": 2},
        {"t": 520.0, "event": "stopped", "replica": 2},
        {"t": 500.0, "event": "start", "replica": 3},
    ]
    assert fleet_results.modeled_gpu_seconds(late, 480.0) == 480 + 80


# --- end to end over saved runs ------------------------------------------------------


def _request(i, policy, ttft, level=0, replica=None):
    return {
        "id": i, "kind": "chat", "group": f"conv-{i % 5}", "tenant": "tenant-0", "turn": 1,
        "phase": "measured", "level": level, "scheduled_s": 60 + i * 0.5, "sent_s": 60 + i * 0.5,
        "first_token_s": 60 + i * 0.5 + ttft, "end_s": 60 + i * 0.5 + ttft + 1.0, "ttft_s": ttft,
        "itl_s": 0.03, "e2e_s": ttft + 1.0, "prompt_tokens": 1000,
        "cached_tokens": 800 if policy == "prefix-aware" else 400, "completion_tokens": 50,
        "replica": i % 4 if replica is None else replica, "policy": policy,
        "router_overhead_us": 80 if policy == "prefix-aware" else 20, "error": "",
    }  # fmt: skip


def _save(root, run_id, meta, rows):
    runs.write_file(root / run_id, "requests.jsonl", "".join(json.dumps(r) + "\n" for r in rows))
    runs.write_file(root / run_id, "meta.json", json.dumps(meta))


@pytest.fixture
def saved_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    ttft = {"round-robin": 1.0, "least-loaded": 0.9, "prefix-aware": 0.5}
    for seed in (0, 1, 2):
        for policy, value in ttft.items():
            meta = {
                "workload": "chat", "policy": policy, "seed": seed, "replicas": 4,
                "run": {"kind": "fixed", "rate_rps": 11.2}, "cost_per_hour_usd": 4.0,
            }  # fmt: skip
            rows = [_request(i, policy, value + 0.01 * seed) for i in range(40)]
            _save(tmp_path, f"fleet-fixed-chat-{policy}-s{seed}", meta, rows)
    # Ramp: round-robin misses the SLO from level 1, prefix-aware from level 2.
    limits = {"round-robin": 1, "prefix-aware": 2}
    for policy, first_miss in limits.items():
        rows = []
        for level in range(3):
            slow = 3.0 if level >= first_miss else 0.4
            rows += [_request(level * 20 + i, policy, slow, level=level) for i in range(20)]
        meta = {
            "workload": "chat", "policy": policy, "seed": 0, "replicas": 4,
            "run": {"kind": "ramp", "rates_rps": [8.0, 10.0, 12.0], "level_s": 60.0},
            "cost_per_hour_usd": 4.0,
        }  # fmt: skip
        _save(tmp_path, f"fleet-ramp-chat-{policy}-s0", meta, rows)
    return tmp_path


def test_policy_table_recomputes_from_request_records(saved_runs):
    table = fleet_results.policy_table("chat")
    assert table["rate_rps"] == 11.2
    assert list(table["policies"]) == ["round-robin", "least-loaded", "prefix-aware"]
    pa = table["policies"]["prefix-aware"]
    assert pa["repeats"] == 3 and pa["ttft_p95_s"]["median"] == pytest.approx(0.51)
    assert pa["cache_hit_rate"]["median"] == 0.8
    assert table["policies"]["round-robin"]["cache_hit_rate"]["median"] == 0.4
    assert fleet_results.policy_table("rag")["policies"] == {}


def test_capacity_table_and_headline_follow_from_the_ramp(saved_runs):
    cap = fleet_results.capacity_table()
    assert cap["policies"]["round-robin"]["max_rps_at_slo"]["median"] == 8.0
    assert cap["policies"]["prefix-aware"]["max_rps_at_slo"]["median"] == 10.0
    assert cap["policies"]["prefix-aware"]["lower_bound"] is False
    # 20 requests x 50 tokens in a 60 s level = 60,000 tokens per hour for $4.
    assert cap["policies"]["round-robin"]["cost_per_m_output"]["median"] == pytest.approx(66.6667)
    h = fleet_results.headline(fleet_results.policy_table("chat"), cap)
    assert h["capacity_change"] == pytest.approx(0.25)
    assert "served 25% more traffic within the SLO" in h["text"]


def test_router_overhead_is_reported_per_policy(saved_runs):
    overhead = fleet_results.router_overhead()["decision_us"]
    assert overhead["prefix-aware"]["p50"] == 80 and overhead["round-robin"]["p95"] == 20


def test_results_summary_and_markdown_build_from_saved_runs(saved_runs, monkeypatch, tmp_path):
    from icr.analysis import results
    from icr.fleet import plan

    monkeypatch.setattr(plan, "CALIBRATION_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(results, "CALIBRATION_FILE", tmp_path / "missing.json")
    summary = results.build()
    assert summary["fleet"]["chat"]["policies"]["prefix-aware"]["repeats"] == 3
    assert summary["headline"]["capacity_change"] == pytest.approx(0.25)
    assert summary["prefix_pressure"]["chat"]["prefix_groups"] == 5
    text = results.render_markdown(summary)
    assert "## Fleet, fixed traffic: `chat` at 11.2 req/s" in text
    assert "## Fleet capacity at the SLO" in text and "## Router overhead" in text
    assert summary["headline"]["text"] in text
    json.dumps(summary)  # the site and the charts read it as JSON
