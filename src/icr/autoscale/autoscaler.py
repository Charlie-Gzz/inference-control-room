"""Autoscaler: starts and stops replicas (1 to 4) from queue depth and KV cache pressure.

Every second it reads the latest replica metrics from the recorder's sampler:
- scale up when the fleet is busy (requests waiting, high load per replica, or KV cache
  nearly full) for `up_sustain_s`. The new replica joins the router only after it is healthy.
- scale down when the remaining replicas could carry the load with room to spare for
  `down_sustain_s`. The replica is first removed from the router (drain), then stopped
  once it has no requests in flight.

The same loop drives the mock fleet in tests and vLLM processes on Modal, through a
small `ReplicaManager` with `start`, `stop` and `url`.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Protocol

from icr import clock


@dataclass(frozen=True)
class AutoscalerConfig:
    min_replicas: int = 1
    max_replicas: int = 4
    interval_s: float = 1.0
    up_load: float = 12.0  # mean (running + waiting) per live replica that triggers scale up
    up_waiting: float = 1.0  # mean waiting requests per live replica that triggers scale up
    up_kv: float = 0.90  # mean KV cache usage that triggers scale up
    up_sustain_s: float = 3.0
    down_load: float = 6.0  # scale down if the load per remaining replica would stay below this
    down_sustain_s: float = 20.0
    drain_timeout_s: float = 60.0

    def to_dict(self) -> dict:
        return asdict(self)


class ReplicaManager(Protocol):
    def url(self, index: int) -> str: ...
    async def start(self, index: int) -> None: ...  # returns when the replica is healthy
    async def stop(self, index: int) -> None: ...


class Autoscaler:
    def __init__(self, manager: ReplicaManager, router, config: AutoscalerConfig, live: list[int]):
        self.manager, self.router, self.config = manager, router, config
        self.live = sorted(live)
        self.events: list[dict] = []
        self._busy_since: float | None = None
        self._idle_since: float | None = None
        self._t0 = clock.now()

    def _event(self, name: str, replica: int, **extra) -> None:
        t = round(clock.now() - self._t0, 2)
        self.events.append(
            {"t": t, "event": name, "replica": replica, "live": len(self.live), **extra}
        )  # noqa: E501

    def signals(self, latest: dict[int, dict]) -> dict:
        """Fleet-level signals from the newest sample of every live replica."""
        rows = [latest[i] for i in self.live if i in latest]
        n = max(len(rows), 1)
        running = sum(r.get("running", 0) for r in rows)
        waiting = sum(r.get("waiting", 0) for r in rows)
        return {
            "load": (running + waiting) / n,
            "waiting": waiting / n,
            "kv": sum(r.get("kv_usage", 0) for r in rows) / n,
            "total": running + waiting,
        }

    def decide(self, sig: dict, now: float) -> str:
        """'up', 'down' or 'hold'. Pure logic, so it can be tested without a fleet."""
        c = self.config
        busy = sig["load"] > c.up_load or sig["waiting"] > c.up_waiting or sig["kv"] > c.up_kv
        remaining = max(len(self.live) - 1, 1)
        idle = not busy and sig["total"] / remaining < c.down_load
        self._busy_since = (self._busy_since or now) if busy else None
        self._idle_since = (self._idle_since or now) if idle else None
        if busy and len(self.live) < c.max_replicas and now - self._busy_since >= c.up_sustain_s:
            return "up"
        if idle and len(self.live) > c.min_replicas and now - self._idle_since >= c.down_sustain_s:
            return "down"
        return "hold"

    async def run(self, sampler) -> None:
        """Control loop. Runs until cancelled."""
        self._t0 = sampler.t0
        while True:
            await asyncio.sleep(self.config.interval_s)
            sig = self.signals(sampler.latest)
            action = self.decide(sig, clock.now())
            if action == "up":
                await self._scale_up(sampler, sig)
            elif action == "down":
                await self._scale_down(sampler, sig)

    async def _scale_up(self, sampler, sig: dict) -> None:
        index = next(i for i in range(self.config.max_replicas) if i not in self.live)
        self._event("start", index, load=round(sig["load"], 2), waiting=round(sig["waiting"], 2))
        started = clock.now()
        await self.manager.start(index)  # blocks this loop: one scaling action at a time
        self.live = sorted([*self.live, index])
        await self._publish()
        sampler.urls[index] = self.manager.url(index)
        self._event("ready", index, startup_s=round(clock.now() - started, 2))
        self._busy_since = self._idle_since = None

    async def _scale_down(self, sampler, sig: dict) -> None:
        index = self.live[-1]
        self.live = self.live[:-1]
        await self._publish()  # router stops sending to it
        self._event("drain", index, load=round(sig["load"], 2))
        deadline = clock.now() + self.config.drain_timeout_s
        while clock.now() < deadline:
            state = await asyncio.to_thread(self.router.state)
            if state["outstanding"].get(str(index), 0) == 0:
                break
            await asyncio.sleep(0.2)
        sampler.urls.pop(index, None)
        sampler.latest.pop(index, None)
        await self.manager.stop(index)
        self._event("stopped", index)
        self._busy_since = self._idle_since = None

    async def _publish(self) -> None:
        live = {i: self.manager.url(i) for i in self.live}
        await asyncio.to_thread(self.router.set_replicas, live)
