"""Recorder: samples replica /metrics every 250 ms and writes the run files."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp

from icr import clock
from icr.loadgen.client import RequestRecord

# vLLM metric name -> field in replicas.jsonl
METRICS = {
    "vllm:num_requests_running": "running",
    "vllm:num_requests_waiting": "waiting",
    "vllm:kv_cache_usage_perc": "kv_usage",
    "vllm:prefix_cache_queries_total": "prefix_queries",
    "vllm:prefix_cache_hits_total": "prefix_hits",
    "vllm:prompt_tokens_total": "prompt_tokens",
    "vllm:generation_tokens_total": "generation_tokens",
}


def parse_metrics(text: str) -> dict:
    """Pick the metrics we track out of a Prometheus text page."""
    out: dict = {}
    for line in text.splitlines():
        if not line.startswith("vllm:"):
            continue
        name = line.split("{", 1)[0].split(" ", 1)[0]
        field = METRICS.get(name)
        if field:
            out[field] = float(line.rsplit(" ", 1)[1])
    return out


class MetricsSampler:
    """Polls every replica's /metrics. `latest` feeds the autoscaler; `samples` is saved."""

    def __init__(self, replica_urls: dict[int, str], interval_s: float = 0.25):
        self.urls = dict(replica_urls)  # replica id -> url; the autoscaler may add or remove
        self.interval = interval_s
        self.samples: list[dict] = []
        self.latest: dict[int, dict] = {}
        self.t0 = clock.now()
        self._task: asyncio.Task | None = None

    async def _scrape(self, session: aiohttp.ClientSession, replica: int, url: str) -> None:
        try:
            async with session.get(f"{url}/metrics") as resp:
                if resp.status != 200:
                    return
                sample = parse_metrics(await resp.text())
        except (aiohttp.ClientError, TimeoutError):
            return
        sample = {"t": round(clock.now() - self.t0, 3), "replica": replica, **sample}
        self.latest[replica] = sample
        self.samples.append(sample)

    async def _loop(self) -> None:
        timeout = aiohttp.ClientTimeout(total=2)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                tick = clock.now()
                await asyncio.gather(*(self._scrape(session, r, u) for r, u in self.urls.items()))
                await clock.sleep_until(tick + self.interval)

    def start(self, t0: float | None = None) -> None:
        self.t0 = t0 or clock.now()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


def write_run(out_dir: Path, records: list[RequestRecord], samples: list[dict], meta: dict) -> None:
    """Write requests.jsonl, replicas.jsonl and meta.json for one run."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "requests.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in sorted(records, key=lambda r: r.id):
            f.write(json.dumps(r.to_dict(), separators=(",", ":")) + "\n")
    with (out_dir / "replicas.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for s in samples:
            f.write(json.dumps(s, separators=(",", ":")) + "\n")
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
