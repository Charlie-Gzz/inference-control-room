"""One MOCK replica as its own process: `python -m icr.mock.serve_one --port 8001`.

Used by local dry runs of the fleet session, where every replica is a separate process
that can be started and stopped, like a real vLLM server. Never a source of real numbers.
"""

from __future__ import annotations

import argparse
import asyncio

from aiohttp import web

from icr.mock.replica import MockParams, MockReplica


async def serve(port: int, replica_id: int, params: MockParams) -> None:
    runner = web.AppRunner(MockReplica(replica_id, params).app())
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    await asyncio.Event().wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--replica", type=int, default=0)
    parser.add_argument("--startup-s", type=float, default=0.0)
    args = parser.parse_args()
    asyncio.run(serve(args.port, args.replica, MockParams(startup_s=args.startup_s)))


if __name__ == "__main__":
    main()
