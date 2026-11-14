"""One experiment run: send a workload, sample replica metrics, write the run files.

The same code drives the local mock fleet and the real vLLM fleet on Modal.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from icr.analysis import metrics
from icr.loadgen.client import LoadGenerator
from icr.loadgen.recorder import MetricsSampler, write_run
from icr.workloads.generator import RequestSpec


async def run(
    specs: list[RequestSpec],
    *,
    targets: list[str],
    replica_urls: dict[int, str],
    out_dir: Path,
    meta: dict,
    autoscaler=None,
    drain_s: float = 120.0,
) -> dict:
    """Send `specs` to `targets` (the router URL, or replica URLs when direct).

    Returns the summary that is also stored in meta.json.
    """
    sampler = MetricsSampler(replica_urls)
    generator = LoadGenerator(targets, timeout_s=drain_s + specs[-1].scheduled_s + 60)
    started = time.time()
    sampler.start()
    scaler_task = asyncio.create_task(autoscaler.run(sampler)) if autoscaler else None
    try:
        records = await generator.run(specs)
    finally:
        if scaler_task:
            scaler_task.cancel()
            await asyncio.gather(scaler_task, return_exceptions=True)
        await sampler.stop()
    rows = [r.to_dict() for r in records]
    summary = metrics.summarize(rows, replicas=len(replica_urls))
    meta = {
        **meta,
        "started_unix": round(started, 3),
        "duration_s": round(time.time() - started, 2),
        "requests_total": len(records),
        "summary": summary,
    }
    if autoscaler:
        meta["autoscaler_events"] = autoscaler.events
    write_run(out_dir, records, sampler.samples, meta)
    return summary
