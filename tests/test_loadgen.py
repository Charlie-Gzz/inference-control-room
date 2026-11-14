"""Open-loop timing and recorder output, against the MOCK fleet."""

import json

from icr.fleet import experiment
from icr.loadgen.client import LoadGenerator
from icr.mock.fleet import MockFleet
from icr.mock.replica import MockParams
from icr.workloads import generator
from tests.conftest import free_port_block

REQUEST_FIELDS = {
    "id", "kind", "group", "tenant", "turn", "phase", "level", "max_tokens", "scheduled_s",
    "sent_s", "first_token_s", "end_s", "ttft_s", "itl_s", "max_gap_s", "e2e_s", "prompt_tokens",
    "cached_tokens", "completion_tokens", "replica", "policy", "reason", "matched_chunks", "loads",
    "router_overhead_us", "status", "error",
}  # fmt: skip


async def test_requests_are_sent_on_schedule_even_when_the_server_is_slow():
    """Open loop: a server that takes ~1 s per request must not delay later sends."""
    slow = MockParams(step_base_s=0.05, time_scale=1.0, max_num_seqs=4)
    fleet = MockFleet(1, base_port=free_port_block(), params=slow)
    await fleet.start()
    try:
        specs = generator.steady_workload("no-sharing", seed=0, rate_rps=40.0, duration_s=2.0)
        for s in specs:
            s.max_tokens = 20
        records = await LoadGenerator([fleet.url(0)]).run(specs)
    finally:
        await fleet.stop()
    lags = sorted(r.sent_s - r.scheduled_s for r in records)
    assert lags[int(0.95 * len(lags))] < 0.03  # sends track the schedule
    assert max(r.e2e_s for r in records) > 1.0  # while the server was far behind
    # Latency counts from the scheduled time, so queueing shows up in TTFT.
    assert all(r.ttft_s >= r.first_token_s - r.scheduled_s - 1e-3 for r in records)


async def test_run_writes_all_three_files_with_every_field(fleet, tmp_path):
    specs = generator.steady_workload("chat", seed=0, rate_rps=20.0, duration_s=3.0, warmup_s=1.0)
    summary = await experiment.run(
        specs,
        targets=fleet.urls,
        replica_urls=dict(enumerate(fleet.urls)),
        out_dir=tmp_path,
        meta={"mock": True, "workload": "chat", "policy": "direct", "seed": 0},
    )
    requests = [json.loads(x) for x in (tmp_path / "requests.jsonl").read_text().splitlines()]
    samples = [json.loads(x) for x in (tmp_path / "replicas.jsonl").read_text().splitlines()]
    meta = json.loads((tmp_path / "meta.json").read_text())

    assert len(requests) == len(specs) == 60
    assert all(set(r) == REQUEST_FIELDS for r in requests)
    assert all(r["error"] == "" and r["completion_tokens"] == r["max_tokens"] for r in requests)
    assert all(r["ttft_s"] > 0 and r["e2e_s"] >= r["ttft_s"] for r in requests)
    assert {s["replica"] for s in samples} == {0, 1, 2, 3}
    assert {"t", "running", "waiting", "kv_usage", "prefix_hits"} <= set(samples[0])
    per_replica = len(samples) / 4
    assert per_replica > 0.6 * meta["duration_s"] / 0.25  # sampled about every 250 ms
    assert meta["mock"] is True and meta["summary"] == summary
    assert summary["requests"] == 40 and summary["errors"] == 0  # warmup is excluded
