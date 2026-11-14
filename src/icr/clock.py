"""One high-resolution clock for all timing.

`time.perf_counter` is monotonic and fine-grained on every platform. On Windows with
Python 3.12, `time.monotonic` ticks every 15.6 ms and asyncio timers can fire early by
that much, so `sleep_until` re-checks the clock until the deadline has really passed.
"""

from __future__ import annotations

import asyncio
import time

now = time.perf_counter


async def sleep_until(deadline: float) -> None:
    """Sleep until `now()` reaches `deadline`. Returns at once if it already has."""
    while (delay := deadline - now()) > 0:
        await asyncio.sleep(delay)
