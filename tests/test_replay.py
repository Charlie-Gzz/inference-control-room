"""Replay files: request columns and replica series built only from recorded values."""

import json

from icr.analysis import replay, runs


def request(i, **extra):
    row = {
        "id": i, "kind": "chat", "group": f"conv-{i % 2}", "tenant": "tenant-0", "turn": 1,
        "phase": "measured", "level": 0, "scheduled_s": float(i), "first_token_s": i + 0.2,
        "end_s": i + 1.0, "ttft_s": 0.2, "itl_s": 0.02, "prompt_tokens": 800,
        "cached_tokens": 400, "completion_tokens": 40, "replica": i % 2,
        "reason": "prefix-hit", "matched_chunks": 3, "loads": [1, 0], "router_overhead_us": 90,
        "error": "",
    }  # fmt: skip
    return {**row, **extra}


def test_request_columns_are_in_arrival_order_and_indexed():
    rows = [request(2), request(0, phase="warmup"), request(1, error="boom", reason="")]
    cols = replay.request_columns(rows)
    req = cols["req"]
    assert req["id"] == [0, 1, 2] and req["t"] == [0.0, 1.0, 2.0]
    assert cols["groups"] == ["conv-0", "conv-1"] and req["grp"] == [0, 1, 0]
    assert req["warm"] == [1, 0, 0] and req["err"] == [0, 1, 0]
    assert [cols["reasons"][i] for i in req["why"]] == ["prefix-hit", "direct", "prefix-hit"]
    assert len({len(v) for v in req.values()}) == 1  # every column has one entry per request


def test_replica_series_uses_counter_deltas_and_marks_downtime():
    samples = [
        {"t": 0.1, "replica": 0, "running": 2, "waiting": 0, "kv_usage": 0.1,
         "generation_tokens": 1000},
        {"t": 0.6, "replica": 0, "running": 3, "waiting": 1, "kv_usage": 0.2,
         "generation_tokens": 1100},
        {"t": 6.2, "replica": 1, "running": 1, "waiting": 0, "kv_usage": 0.05,
         "generation_tokens": 50},
    ]  # fmt: skip
    series = replay.replica_series(samples, replicas=2, duration_s=8.0)
    assert series["running"][0][:2] == [2, 3] and series["waiting"][0][1] == 1
    assert series["tps"][0][1] == 200  # 100 tokens in 0.5 s
    assert series["running"][0][2] == 3  # carried forward just after the last sample
    assert series["running"][0][-1] is None  # long after the last sample: replica down
    assert series["running"][1][0] is None  # before its first sample: not started yet
    assert series["running"][1][12] == 1


def test_build_reads_a_saved_run(tmp_path):
    rows = [request(i) for i in range(6)]
    meta = {
        "workload": "chat", "policy": "prefix-aware", "seed": 1, "replicas": 2,
        "run": {"kind": "fixed", "rate_rps": 3.0, "warmup_s": 2.0}, "config": {"name": "awq"},
        "cost_per_hour_usd": 4.2, "summary": {"requests": 6},
    }  # fmt: skip
    directory = tmp_path / "fleet-fixed-chat-prefix-aware-s1"
    runs.write_file(directory, "requests.jsonl", "".join(json.dumps(r) + "\n" for r in rows))
    runs.write_file(directory, "meta.json", json.dumps(meta))
    data = replay.build(runs.load(directory.name, tmp_path))
    assert data["meta"]["policy"] == "prefix-aware" and data["meta"]["rate_rps"] == 3.0
    assert data["meta"]["duration_s"] == 6.0 and data["meta"]["mock"] is False
    assert data["meta"]["slo"] == {"ttft_s": 2.0, "itl_s": 0.1}
    assert len(data["req"]["t"]) == 6 and len(data["rep"]["running"]) == 2
    json.dumps(data)  # serializable
