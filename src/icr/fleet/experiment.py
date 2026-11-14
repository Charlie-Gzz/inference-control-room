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
    request_timeout_s: float = 120.0,
) -> dict:
    """Send `specs` to `targets` (the router URL, or replica URLs when direct).

    A request that has not finished `request_timeout_s` after it was sent is aborted
    and recorded as an error, so an overloaded run still ends.
    Returns the summary that is also stored in meta.json.
    """
    sampler = MetricsSampler(replica_urls)
    generator = LoadGenerator(targets, timeout_s=request_timeout_s)
    started = time.time()
    sampler.start()
    scaler_task = asyncio.create_task(autoscaler.run(sampler)) if autoscaler else None
    try:
        records = await generator.run(specs)
    finally:
        if scaler_task:
            failed = scaler_task.exception() if scaler_task.done() else None
            scaler_task.cancel()
            await asyncio.gather(scaler_task, return_exceptions=True)
            if failed:
                raise failed  # an autoscaler crash must not pass silently
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
