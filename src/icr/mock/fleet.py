"""MOCK fleet: several mock replicas on localhost ports, startable and stoppable one by one."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from aiohttp import web

from icr.mock.replica import MockParams, MockReplica


class MockFleet:
    """Replica i listens on 127.0.0.1:(base_port + i). Used by tests and local runs."""

    def __init__(self, size: int, base_port: int = 8001, params: MockParams | None = None):
        self.size, self.base_port = size, base_port
        self.params = params or MockParams()
        self.replicas: dict[int, MockReplica] = {}
        self._runners: dict[int, web.AppRunner] = {}

    def url(self, index: int) -> str:
        return f"http://127.0.0.1:{self.base_port + index}"

    @property
    def urls(self) -> list[str]:
        return [self.url(i) for i in range(self.size)]

    async def start_replica(self, index: int, startup_s: float | None = None) -> None:
        """Start one replica. It answers /health with 503 until its startup time has passed."""
        if index in self._runners:
            return
        params = self.params if startup_s is None else replace(self.params, startup_s=startup_s)
        replica = MockReplica(index, params)
        runner = web.AppRunner(replica.app())
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", self.base_port + index).start()
        self.replicas[index], self._runners[index] = replica, runner

    async def stop_replica(self, index: int) -> None:
        runner = self._runners.pop(index, None)
        self.replicas.pop(index, None)
        if runner:
            await runner.cleanup()

    async def start(self, count: int | None = None) -> None:
        for i in range(self.size if count is None else count):
            await self.start_replica(i, startup_s=0.0)

    async def stop(self) -> None:
        for i in list(self._runners):
            await self.stop_replica(i)


async def serve_forever(size: int, base_port: int, params: MockParams) -> None:
    fleet = MockFleet(size, base_port, params)
    await fleet.start()
    print(f"MOCK fleet (not vLLM): {', '.join(fleet.urls)}")
    try:
        await asyncio.Event().wait()
    finally:
        await fleet.stop()
