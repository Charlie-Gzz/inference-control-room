"""Shared fixtures: a fast MOCK fleet on free localhost ports."""

import socket

import pytest_asyncio

from icr.mock.fleet import MockFleet
from icr.mock.replica import MockParams


def free_port_block(size: int = 8) -> int:
    """A base port with `size` consecutive free ports after it."""
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            base = s.getsockname()[1]
        if base + size < 65000 and all(_is_free(base + i) for i in range(size)):
            return base


def _is_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


FAST = MockParams(time_scale=0.05)  # simulated time runs 20x faster than real time


@pytest_asyncio.fixture
async def fleet():
    """Four mock replicas, started and ready."""
    f = MockFleet(4, base_port=free_port_block(), params=FAST)
    await f.start()
    yield f
    await f.stop()
