"""Autoscaler: decision logic, and scaling up and down on a burst against the MOCK fleet."""

from icr.autoscale.autoscaler import Autoscaler, AutoscalerConfig
from icr.fleet.local import mock_autoscale
from icr.mock.replica import MockParams
from icr.workloads import generator
from tests.conftest import free_port_block

CONFIG = AutoscalerConfig(up_load=10, up_waiting=1, down_load=4, up_sustain_s=3, down_sustain_s=20)


def scaler(live: list[int]) -> Autoscaler:
    return Autoscaler(manager=None, router=None, config=CONFIG, live=live)


def signal(load=0.0, waiting=0.0, kv=0.0, live=1):
    return {"load": load, "waiting": waiting, "kv": kv, "total": load * live}


def test_scales_up_only_after_sustained_load():
    s = scaler([0])
    assert s.decide(signal(load=15), now=0.0) == "hold"
    assert s.decide(signal(load=15), now=2.0) == "hold"
    assert s.decide(signal(load=15), now=3.0) == "up"


def test_a_brief_spike_does_not_scale_up():
    s = scaler([0])
    s.decide(signal(load=15), now=0.0)
    assert s.decide(signal(load=2), now=1.0) == "hold"
    assert s.decide(signal(load=15), now=3.5) == "hold"  # the timer restarted


def test_waiting_requests_or_kv_pressure_also_scale_up():
    for sig in (signal(load=3, waiting=2), signal(load=3, kv=0.95)):
        s = scaler([0, 1])
        s.decide(sig, now=0.0)
        assert s.decide(sig, now=3.0) == "up"


def test_never_exceeds_max_or_drops_below_min():
    full = scaler([0, 1, 2, 3])
    full.decide(signal(load=50, live=4), now=0.0)
    assert full.decide(signal(load=50, live=4), now=10.0) == "hold"
    one = scaler([0])
    one.decide(signal(load=0), now=0.0)
    assert one.decide(signal(load=0), now=100.0) == "hold"


def test_scales_down_only_if_the_rest_can_carry_the_load():
    s = scaler([0, 1, 2])
    s.decide(signal(load=1, live=3), now=0.0)  # 3 total over 2 remaining = 1.5 < 4
    assert s.decide(signal(load=1, live=3), now=19.0) == "hold"
    assert s.decide(signal(load=1, live=3), now=20.0) == "down"
    busy = scaler([0, 1, 2])
    busy.decide(signal(load=3, live=3), now=0.0)  # 9 total over 2 remaining = 4.5 > 4
    assert busy.decide(signal(load=3, live=3), now=30.0) == "hold"


async def test_scales_up_on_a_burst_and_down_after_it_MOCK(tmp_path):
    """Quiet, then a burst, then quiet again, at 10x speed on the mock fleet."""
    params = MockParams(time_scale=0.1)
    quiet = generator.steady_workload("chat", 0, rate_rps=20.0, duration_s=3.0)
    burst = generator.steady_workload("chat", 1, rate_rps=400.0, duration_s=4.0)
    tail = generator.steady_workload("chat", 2, rate_rps=10.0, duration_s=5.0)
    specs = []
    for offset, part in ((0.0, quiet), (3.0, burst), (7.0, tail)):
        for s in part:
            s.scheduled_s += offset
            s.id = len(specs)
            s.max_tokens = 60
            specs.append(s)
    config = AutoscalerConfig(interval_s=0.1, up_load=6, up_sustain_s=0.3, down_load=3,
                              down_sustain_s=1.0, drain_timeout_s=5.0)  # fmt: skip
    summary, events = await mock_autoscale(
        specs, config, params, startup_s=5.0, out_dir=tmp_path,
        base_port=free_port_block(), router_port=free_port_block(1),
    )  # fmt: skip
    assert summary["errors"] == 0

    names = [e["event"] for e in events]
    assert "ready" in names and "stopped" in names
    first_ready = next(e for e in events if e["event"] == "ready")
    assert 3.0 < first_ready["t"] < 7.5  # reacted to the burst
    assert first_ready["startup_s"] >= 0.45  # and waited for the replica to be healthy
    assert names.index("ready") < names.index("drain") < names.index("stopped")
    assert max(e["live"] for e in events) >= 2

    # No request reached a replica before the router was told it was ready.
    import json

    ready_at = {e["replica"]: e["t"] for e in events if e["event"] == "ready"}
    for line in (tmp_path / "requests.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["replica"] in ready_at and r["replica"] != 0:
            assert r["sent_s"] >= ready_at[r["replica"]] - 0.05
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["autoscaler_events"] == events
