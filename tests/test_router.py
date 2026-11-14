"""The Go router, end to end against the MOCK fleet."""

import json
import urllib.error
import urllib.request

import pytest

from icr.analysis import metrics
from icr.fleet.router_proc import RouterProcess
from icr.loadgen.client import LoadGenerator
from icr.workloads import generator
from tests.conftest import free_port_block


@pytest.fixture
def start_router(fleet, tmp_path):
    """Factory: start a router in front of the mock fleet, stop it after the test."""
    routers = []

    def start(policy: str, **flags) -> RouterProcess:
        router = RouterProcess(
            dict(enumerate(fleet.urls)), policy, port=free_port_block(1),
            decision_log=tmp_path / f"decisions-{len(routers)}.jsonl", flags=flags,
        )  # fmt: skip
        router.start()
        routers.append(router)
        return router

    yield start
    for router in routers:
        router.stop()


def chat(rate=20.0, duration=6.0, seed=0, mix="chat"):
    specs = generator.steady_workload(mix, seed, rate, duration)
    for s in specs:
        s.max_tokens = 8  # keep the test short
    return specs


async def test_prefix_aware_keeps_a_conversation_on_one_replica(start_router):
    router = start_router("prefix-aware")
    records = await LoadGenerator([router.url]).run(chat())
    assert not any(r.error for r in records)
    by_conv: dict[str, list] = {}
    for r in sorted(records, key=lambda r: r.id):
        if r.kind == "chat":
            by_conv.setdefault(r.group, []).append(r)
    follow_ups = [
        (a, b) for turns in by_conv.values() for a, b in zip(turns, turns[1:], strict=False)
    ]
    assert len(follow_ups) > 20
    same = sum(a.replica == b.replica for a, b in follow_ups)
    assert same / len(follow_ups) > 0.9
    assert all(b.reason == "prefix-hit" and b.matched_chunks > 0 for a, b in follow_ups
               if a.replica == b.replica)  # fmt: skip


async def test_prefix_aware_beats_round_robin_on_cache_hits_MOCK(start_router, fleet):
    """Expected direction on the mock. Not a published number."""
    specs = chat(duration=8.0)
    rates = {}
    for policy in ("round-robin", "prefix-aware"):
        for replica in fleet.replicas.values():
            replica.cache.clear()
        records = await LoadGenerator([start_router(policy).url]).run(specs)
        rates[policy] = metrics.summarize([r.to_dict() for r in records])["cache_hit_rate"]
    assert rates["prefix-aware"] > rates["round-robin"] + 0.1


async def test_no_sharing_control_never_reports_a_prefix_hit(start_router):
    router = start_router("prefix-aware")
    records = await LoadGenerator([router.url]).run(chat(mix="no-sharing", duration=3.0))
    assert {r.reason for r in records} == {"no-prefix"}
    assert all(r.cached_tokens == 0 for r in records)


async def test_overloaded_replica_falls_back_to_least_loaded(start_router):
    """One hot prefix: the load bound must spread it instead of piling on one replica."""
    router = start_router("prefix-aware", **{"min-bound": 1, "load-factor": 1.0})
    specs = chat(mix="rag", rate=60.0, duration=2.0)
    hot = specs[0].messages
    for s in specs:
        s.messages = hot  # every request shares one prefix
        s.max_tokens = 30
    records = await LoadGenerator([router.url]).run(specs)
    reasons = {r.reason for r in records}
    assert "prefix-overloaded" in reasons and "prefix-hit" in reasons
    assert len({r.replica for r in records}) == 4  # the hot prefix spread to every replica
    assert max(max(r.loads) for r in records if r.reason == "prefix-hit") < len(records) / 2


async def test_stream_is_passed_through_chunk_by_chunk(start_router, fleet):
    specs = chat(rate=5.0, duration=2.0)
    for s in specs:
        s.max_tokens = 40
    direct = await LoadGenerator([fleet.url(0)]).run(specs)
    proxied = await LoadGenerator([start_router("round-robin").url]).run(specs)
    for r in proxied:
        assert r.completion_tokens == 40 and r.itl_s > 0
        # Tokens arrive spread over time, not in one buffered burst at the end.
        assert r.end_s - r.first_token_s > 0.5 * 39 * 0.025 * fleet.params.time_scale
        assert r.max_gap_s < 0.5 * (r.end_s - r.first_token_s)
    ttft = lambda rs: metrics.percentile([r.ttft_s for r in rs], 50)  # noqa: E731
    assert ttft(proxied) < ttft(direct) + 0.05  # the router adds no visible wait


async def test_decisions_are_reported_in_headers_log_and_metrics(start_router):
    router = start_router("least-loaded")
    records = await LoadGenerator([router.url]).run(chat(duration=2.0))
    assert all(r.policy == "least-loaded" and r.reason == "least-loaded" for r in records)
    assert all(len(r.loads) == 4 and r.router_overhead_us is not None for r in records)

    router.state()  # flushes the decision log
    lines = [json.loads(x) for x in router.decision_log.read_text().splitlines()]
    assert sorted(int(x["request_id"]) for x in lines) == sorted(r.id for r in records)
    assert {"ts", "policy", "replica", "reason", "matched_chunks", "loads", "overhead_us"} <= set(
        lines[0]
    )  # noqa: E501

    text = router.metrics_text()
    assert (
        f'switchyard_decisions_total{{policy="least-loaded",reason="least-loaded"}} {len(records)}'
        in text
    )  # noqa: E501
    assert f"switchyard_overhead_seconds_count {len(records)}" in text
    assert 'switchyard_outstanding_requests{replica="0"} 0' in text


async def test_router_only_sends_to_live_replicas(start_router, fleet):
    router = start_router("round-robin")
    router.set_replicas({1: fleet.url(1), 3: fleet.url(3)})
    records = await LoadGenerator([router.url]).run(chat(duration=2.0))
    assert {r.replica for r in records} == {1, 3}
    assert router.state()["live"] == [1, 3]


async def test_policy_can_be_switched_and_bad_names_are_rejected(start_router):
    router = start_router("round-robin")
    router.set_policy("prefix-aware")
    assert router.state()["policy"] == "prefix-aware"
    with pytest.raises(urllib.error.HTTPError):
        router.set_policy("random")


async def test_no_live_replicas_returns_503(start_router):
    router = start_router("least-loaded")
    router.set_replicas({})
    req = urllib.request.Request(router.url + "/v1/chat/completions", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=5)
    assert err.value.code == 503
