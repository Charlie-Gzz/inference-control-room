"""Local runs against the MOCK fleet. For development only: never published."""

from __future__ import annotations

import time
from pathlib import Path

import aiohttp

from icr import config
from icr.autoscale.autoscaler import Autoscaler, AutoscalerConfig
from icr.fleet import experiment
from icr.fleet.router_proc import RouterProcess
from icr.mock.fleet import MockFleet
from icr.mock.replica import MockParams
from icr.routing.policy import POLICIES
from icr.workloads import generator
from icr.workloads.text import CHARS_PER_TOKEN

MOCK_RUNS = config.ROOT / ".scratch" / "mock-runs"


def table_chunks_for(kv_tokens: int, chars_per_token: float = CHARS_PER_TOKEN,
                     chunk_size: int = 256, fill: float = 0.8) -> int:  # fmt: skip
    """Router prefix-table size that matches a replica's KV cache (in text chunks)."""
    return int(kv_tokens * chars_per_token / chunk_size * fill)


async def reset_caches(urls: list[str]) -> None:
    async with aiohttp.ClientSession() as session:
        for url in urls:
            async with session.post(f"{url}/reset_prefix_cache") as resp:
                resp.raise_for_status()


async def mock_comparison(
    workload: str = "chat",
    policies: tuple[str, ...] = POLICIES,
    seed: int = 0,
    rate_rps: float = 30.0,
    duration_s: float = 40.0,
    warmup_s: float = 10.0,
    params: MockParams | None = None,
    base_port: int = 8001,
    router_port: int = 8080,
    out_root: Path = MOCK_RUNS,
) -> dict[str, dict]:
    """Same traffic through every policy, on the mock fleet. Returns policy -> summary."""
    params = params or MockParams()
    fleet = MockFleet(4, base_port, params)
    await fleet.start()
    backends = dict(enumerate(fleet.urls))
    flags = {"table-chunks": table_chunks_for(params.kv_capacity_tokens)}
    router = RouterProcess(backends, policies[0], router_port, flags=flags)
    router.start()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = {}
    try:
        specs = generator.steady_workload(workload, seed, rate_rps, duration_s, warmup_s)
        for policy in policies:
            await reset_caches(fleet.urls)
            router.set_policy(policy)
            router.reset()
            meta = {"mock": True, "workload": workload, "policy": policy, "seed": seed}
            meta |= {"rate_rps": rate_rps, "duration_s": duration_s, "warmup_s": warmup_s}
            out = out_root / f"mock-{stamp}-{workload}-{policy}"
            results[policy] = await experiment.run(
                specs, targets=[router.url], replica_urls=backends, out_dir=out, meta=meta
            )
    finally:
        router.stop()
        await fleet.stop()
    return results


class MockManager:
    """ReplicaManager for the mock fleet: replicas take `startup_s` to become healthy."""

    def __init__(self, fleet: MockFleet, startup_s: float):
        self.fleet, self.startup_s = fleet, startup_s

    def url(self, index: int) -> str:
        return self.fleet.url(index)

    async def start(self, index: int) -> None:
        import asyncio

        await self.fleet.start_replica(index, startup_s=self.startup_s)
        while not self.fleet.replicas[index].is_ready():
            await asyncio.sleep(0.02)

    async def stop(self, index: int) -> None:
        await self.fleet.stop_replica(index)


async def mock_autoscale(
    specs: list,
    scaler_config: AutoscalerConfig,
    params: MockParams,
    startup_s: float,
    out_dir: Path,
    base_port: int = 8001,
    router_port: int = 8080,
    initial: int = 1,
) -> tuple[dict, list[dict]]:
    """Run `specs` through an autoscaled mock fleet. Returns (summary, autoscaler events)."""
    fleet = MockFleet(4, base_port, params)
    await fleet.start(initial)
    live = {i: fleet.url(i) for i in range(initial)}
    router = RouterProcess(live, "least-loaded", router_port)
    router.start()
    scaler = Autoscaler(MockManager(fleet, startup_s), router, scaler_config, list(live))
    try:
        summary = await experiment.run(
            specs, targets=[router.url], replica_urls=live, out_dir=out_dir,
            meta={"mock": True, "autoscaled": True}, autoscaler=scaler,
        )  # fmt: skip
    finally:
        router.stop()
        await fleet.stop()
    return summary, scaler.events
