"""The MOCK replica behaves like vLLM where it matters: prefix cache, queueing, metrics."""

import asyncio

import aiohttp

from icr.loadgen.client import LoadGenerator
from icr.loadgen.recorder import parse_metrics
from icr.mock.fleet import MockFleet
from icr.mock.replica import MockParams
from icr.workloads.generator import RequestSpec
from icr.workloads.text import passage
from tests.conftest import free_port_block


def spec(i: int, text: str, at: float = 0.0, max_tokens: int = 4) -> RequestSpec:
    return RequestSpec(
        id=i, scheduled_s=at, kind="chat", group="g", tenant="t", turn=1,
        messages=[{"role": "user", "content": text}], max_tokens=max_tokens,
    )  # fmt: skip


async def send(url: str, specs: list[RequestSpec]):
    return await LoadGenerator([url]).run(specs)


async def metrics(url: str) -> dict:
    async with aiohttp.ClientSession() as s, s.get(f"{url}/metrics") as resp:
        return parse_metrics(await resp.text())


async def test_second_identical_prompt_hits_the_prefix_cache():
    import random

    fleet = MockFleet(1, base_port=free_port_block(), params=MockParams(time_scale=0.2))
    await fleet.start()
    try:
        text = passage(random.Random(0), 4000)  # 1 s of simulated prefill when uncached
        first = (await send(fleet.url(0), [spec(0, text)]))[0]
        second = (await send(fleet.url(0), [spec(1, text + " And one more question.")]))[0]
    finally:
        await fleet.stop()
    assert first.cached_tokens == 0
    assert second.cached_tokens >= 0.9 * first.prompt_tokens
    assert second.ttft_s < 0.5 * first.ttft_s  # far less prefill work


async def test_cache_is_per_replica_and_reset_clears_it(fleet):
    import random

    text = passage(random.Random(1), 400)
    await send(fleet.url(0), [spec(0, text)])
    other = (await send(fleet.url(1), [spec(1, text)]))[0]
    assert other.cached_tokens == 0  # replica 1 never saw it
    async with aiohttp.ClientSession() as s, s.post(f"{fleet.url(0)}/reset_prefix_cache") as r:
        assert r.status == 200
    again = (await send(fleet.url(0), [spec(2, text)]))[0]
    assert again.cached_tokens == 0


async def test_lru_eviction_when_the_cache_is_full():
    import random

    params = MockParams(time_scale=0.02, kv_capacity_tokens=1000)
    fleet = MockFleet(1, base_port=free_port_block(), params=params)
    await fleet.start()
    try:
        rng = random.Random(2)
        a, b, c = (passage(rng, 450) for _ in range(3))
        for i, text in enumerate([a, b, c]):  # c pushes a out
            await send(fleet.url(0), [spec(i, text)])
        hit_b = (await send(fleet.url(0), [spec(3, b)]))[0]
        miss_a = (await send(fleet.url(0), [spec(4, a)]))[0]
        assert hit_b.cached_tokens > 0.9 * hit_b.prompt_tokens
        # Tail blocks are evicted first, so only the first few blocks of `a` survive.
        assert miss_a.cached_tokens < 0.3 * miss_a.prompt_tokens
    finally:
        await fleet.stop()


async def test_requests_queue_beyond_max_num_seqs():
    params = MockParams(time_scale=0.2, max_num_seqs=2)
    fleet = MockFleet(1, base_port=free_port_block(), params=params)
    await fleet.start()
    try:
        specs = [spec(i, f"unique prompt number {i} " * 5, max_tokens=100) for i in range(6)]
        task = asyncio.create_task(send(fleet.url(0), specs))
        await asyncio.sleep(0.05)
        mid = await metrics(fleet.url(0))
        records = await task
        assert mid["running"] == 2 and mid["waiting"] == 4
        assert all(r.completion_tokens == 100 and not r.error for r in records)
        ttfts = sorted(r.ttft_s for r in records)
        assert ttfts[2] > 5 * ttfts[0]  # the third request waited for a free slot
    finally:
        await fleet.stop()


async def test_metrics_page_uses_vllm_names(fleet):
    await send(fleet.url(0), [spec(0, "hello there " * 30)])
    m = await metrics(fleet.url(0))
    assert m["prompt_tokens"] > 0 and m["generation_tokens"] == 4
    assert {"running", "waiting", "kv_usage", "prefix_queries", "prefix_hits"} <= set(m)


async def test_replica_is_not_ready_during_startup():
    fleet = MockFleet(1, base_port=free_port_block(), params=MockParams())
    await fleet.start_replica(0, startup_s=0.3)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{fleet.url(0)}/health") as r:
                assert r.status == 503
            await asyncio.sleep(0.35)
            async with s.get(f"{fleet.url(0)}/health") as r:
                assert r.status == 200
    finally:
        await fleet.stop()
