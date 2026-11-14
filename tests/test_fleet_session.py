"""Dry run of the fleet session (M4) against MOCK replicas, one process per replica.

The same `run_session` code runs on Modal with real vLLM servers. This test exists so
that a logic bug shows up here, for free, and not in a paid 4-GPU session.
"""

import subprocess
import sys
import time

import pytest

from icr.analysis import metrics, runs
from icr.autoscale.autoscaler import AutoscalerConfig
from icr.fleet import plan
from icr.modal_app import fleet
from icr.modal_app.vllm_proc import ServerConfig, VllmServer
from tests.conftest import free_port_block

CALIB = {"r_sat": {"chat": 3.0, "rag": 1.5, "no-sharing": 2.0, "agentic": 1.0}}


class MockServer(VllmServer):
    """A mock replica process with the interface of a vLLM server."""

    def start(self) -> None:
        self.started_at = time.monotonic()
        cmd = [sys.executable, "-m", "icr.mock.serve_one", "--port", str(self.port),
               "--replica", str(self.gpu_index), "--startup-s", "0.4"]  # fmt: skip
        self.process = subprocess.Popen(cmd)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)

    def log_tail(self, lines: int = 60) -> str:
        return ""


def short(run: dict, **changes) -> dict:
    return {**run, **changes}


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    chat = plan.runs_for("chat", CALIB)
    rr = next(r for r in chat if r["policy"] == "round-robin" and r["seed"] == 0)
    pa = next(r for r in chat if r["policy"] == "prefix-aware" and r["seed"] == 0)
    static, scaled = plan.runs_for("autoscale", CALIB)[:2]
    quick = {"rate_rps": 16.0, "warmup_s": 2.0, "measured_s": 6.0}
    base = free_port_block(6)
    return {
        "session_id": "dry-run", "label": "mock", "replicas": 4,
        "config": ServerConfig().to_dict(), "table_chunks": 4000,
        "base_port": base, "router_port": base + 5, "budget_s": 900,
        "autoscaler": AutoscalerConfig(
            interval_s=0.25, up_load=3.0, up_sustain_s=0.5, down_load=2.0, down_sustain_s=1.5
        ).to_dict(),
        "runs": [
            short(plan.runs_for("proxycheck", CALIB)[0], rate_rps=4.0, measured_s=3.0),
            short(rr, **quick),
            short(scaled, rate_rps=20.0, warmup_s=1.0, measured_s=8.0),
            short(pa, **quick),
            short(static, rate_rps=20.0, warmup_s=1.0, measured_s=8.0),
            short(plan.runs_for("ramp", CALIB)[0], rates_rps=[6.0, 10.0, 14.0], warmup_s=2.0,
                  level_s=2.0),
        ],
        "root": tmp_path_factory.mktemp("fleet-runs"),
    }  # fmt: skip


@pytest.fixture(scope="module")
def result(session):
    commits = []
    out = fleet.run_session(
        session, lambda: commits.append(1), make_server=MockServer, runs_root=session["root"]
    )
    out["commits"] = len(commits)
    return out


def test_every_run_finishes_and_is_committed(result, session):
    assert "error" not in result, result.get("error")
    assert result["skipped"] == []
    expected = {fleet.run_id(r) for r in session["runs"]} | {
        "fleet-proxycheck-chat-router-s0-direct"
    }
    assert set(result["runs"]) == expected
    assert result["commits"] == len(session["runs"])  # one Volume commit per finished run
    assert sorted(result["startup_s"]) == [0, 1, 2, 3]
    for files in result["runs"].values():
        assert {"requests.jsonl", "replicas.jsonl", "meta.json"} <= set(files)


def test_fixed_runs_use_all_replicas_and_prefix_aware_reuses_more_cache(result, session):
    saved = {
        p: runs.load(f"fleet-fixed-chat-{p}-s0", session["root"])
        for p in ("round-robin", "prefix-aware")
    }
    for run in saved.values():
        rows = run.requests
        assert not [r for r in rows if r["error"]]
        assert {r["replica"] for r in rows} == {0, 1, 2, 3}
        assert run.meta["run"]["rate_rps"] == 16.0 and run.meta["replicas"] == 4
    hits = {p: metrics.summarize(r.requests)["cache_hit_rate"] for p, r in saved.items()}
    assert hits["prefix-aware"] > hits["round-robin"]  # MOCK: direction only
    # Same seed, same traffic: both policies got byte-identical arrival times.
    times = [[r["scheduled_s"] for r in run.requests] for run in saved.values()]
    assert times[0] == times[1]


def test_autoscaled_run_starts_at_one_replica_and_scales_up(result, session):
    run = runs.load("fleet-autoscale-chat-autoscaled-s0", session["root"])
    events = run.meta["autoscaler_events"]
    assert [e["event"] for e in events][:2] == ["start", "ready"]
    first_ready = next(e["t"] for e in events if e["event"] == "ready")
    early = [r for r in run.requests if r["scheduled_s"] < min(first_ready, 1.0)]
    assert early and {r["replica"] for r in early} == {0}
    assert len({r["replica"] for r in run.requests}) > 1
    # The run after it (prefix-aware, fixed) had the whole fleet back.
    after = runs.load("fleet-fixed-chat-prefix-aware-s0", session["root"])
    assert {r["replica"] for r in after.requests} == {0, 1, 2, 3}


def test_static_autoscale_variant_keeps_four_replicas(result, session):
    run = runs.load("fleet-autoscale-chat-static-s0", session["root"])
    assert "autoscaler_events" not in run.meta
    assert {r["policy"] for r in run.requests} == {"least-loaded"}
    assert {r["replica"] for r in run.requests} == {0, 1, 2, 3}


def test_proxycheck_sends_the_same_traffic_direct_and_through_the_router(result, session):
    routed = runs.load("fleet-proxycheck-chat-router-s0", session["root"])
    direct = runs.load("fleet-proxycheck-chat-router-s0-direct", session["root"])
    assert {r["replica"] for r in routed.requests} == {0}
    assert {r["policy"] for r in direct.requests} == {"direct"}
    assert len(routed.requests) == len(direct.requests) > 5


def test_ramp_run_records_levels(result, session):
    run = runs.load("fleet-ramp-chat-round-robin-s0", session["root"])
    assert sorted({r["level"] for r in run.requests if r["phase"] == "measured"}) == [0, 1, 2]


def test_a_rerun_skips_finished_runs_and_a_short_budget_skips_the_rest(result, session):
    again = fleet.run_session(
        {**session, "budget_s": 1}, lambda: None, make_server=MockServer,
        runs_root=session["root"],
    )  # fmt: skip
    assert set(again["runs"]) >= {fleet.run_id(r) for r in session["runs"]}  # read back, not rerun
    fresh = {**session, "budget_s": 1, "runs": [short(session["runs"][1], seed=7)]}
    out = fleet.run_session(fresh, lambda: None, make_server=MockServer, runs_root=session["root"])
    assert out["skipped"] == ["fleet-fixed-chat-round-robin-s7"] and not out["runs"]
