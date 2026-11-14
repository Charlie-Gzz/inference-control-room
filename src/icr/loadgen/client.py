"""Open-loop load generator.

Every request is sent at its scheduled arrival time, whether or not earlier requests
have finished. Latency is measured from the *scheduled* time, so a slow system cannot
hide its queue by slowing the sender down (no coordinated omission).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field

import aiohttp

from icr import clock, config
from icr.workloads.generator import RequestSpec

HEADER_PREFIX = "X-Switchyard-"


@dataclass
class RequestRecord:
    """One line of requests.jsonl. Times are seconds from run start unless named *_s latency."""

    id: int
    kind: str
    group: str
    tenant: str
    turn: int
    phase: str
    level: int
    max_tokens: int
    scheduled_s: float
    sent_s: float = 0.0
    first_token_s: float | None = None
    end_s: float | None = None
    ttft_s: float | None = None  # first token minus scheduled time
    itl_s: float | None = None  # mean gap between output tokens
    max_gap_s: float | None = None  # longest pause between two streamed chunks
    e2e_s: float | None = None  # last token minus scheduled time
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    completion_tokens: int | None = None
    replica: int | None = None
    policy: str = "direct"
    reason: str = ""
    matched_chunks: int = 0
    loads: list[int] = field(default_factory=list)
    router_overhead_us: int | None = None
    status: int | None = None
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def payload_bytes(spec: RequestSpec) -> bytes:
    """Request body. Greedy decoding and a forced output length keep every run comparable."""
    body = {
        "model": config.SERVED_MODEL_NAME,
        "messages": spec.messages,
        "max_tokens": spec.max_tokens,
        "temperature": 0,
        "ignore_eos": True,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    return json.dumps(body).encode()


class LoadGenerator:
    """Sends specs to `targets` (a router URL, or replica URLs used in turn when direct)."""

    def __init__(self, targets: list[str], timeout_s: float = 300.0):
        self.targets = targets
        self.timeout = aiohttp.ClientTimeout(total=timeout_s)
        self.records: list[RequestRecord] = []

    async def run(self, specs: list[RequestSpec]) -> list[RequestRecord]:
        bodies = [payload_bytes(s) for s in specs]  # serialize before the clock starts
        connector = aiohttp.TCPConnector(limit=0)
        async with aiohttp.ClientSession(connector=connector, timeout=self.timeout) as session:
            self.t0 = clock.now()
            tasks = []
            for i, (spec, body) in enumerate(zip(specs, bodies, strict=True)):
                await clock.sleep_until(self.t0 + spec.scheduled_s)
                target = self.targets[i % len(self.targets)]
                direct = i % len(self.targets) if len(self.targets) > 1 else None
                tasks.append(asyncio.create_task(self._send(session, spec, body, target, direct)))
            self.records = list(await asyncio.gather(*tasks))
        return self.records

    async def _send(
        self, session, spec: RequestSpec, body: bytes, target: str, direct
    ) -> RequestRecord:  # noqa: E501
        rec = RequestRecord(
            id=spec.id, kind=spec.kind, group=spec.group, tenant=spec.tenant, turn=spec.turn,
            phase=spec.phase, level=spec.level, max_tokens=spec.max_tokens,
            scheduled_s=spec.scheduled_s, sent_s=round(clock.now() - self.t0, 4),
            replica=direct,
        )  # fmt: skip
        headers = {"Content-Type": "application/json", "X-Request-Id": str(spec.id)}
        first = last = None
        max_gap = 0.0
        try:
            url = f"{target}/v1/chat/completions"
            async with session.post(url, data=body, headers=headers) as resp:
                rec.status = resp.status
                _read_router_headers(rec, resp.headers)
                if resp.status != 200:
                    rec.error = (await resp.text())[:200]
                    return rec
                async for raw in resp.content:
                    if not raw.startswith(b"data: {"):
                        continue
                    now = clock.now()
                    chunk = json.loads(raw[6:])
                    if chunk.get("usage"):
                        _read_usage(rec, chunk["usage"])
                    if any(c.get("delta", {}).get("content") for c in chunk.get("choices", ())):
                        if first is None:
                            first = now
                        else:
                            max_gap = max(max_gap, now - last)
                        last = now
        except (aiohttp.ClientError, TimeoutError) as e:
            rec.error = f"{type(e).__name__}: {e}"[:200]
        if first is not None:
            scheduled = self.t0 + spec.scheduled_s
            rec.first_token_s = round(first - self.t0, 4)
            rec.end_s = round(last - self.t0, 4)
            rec.ttft_s = round(first - scheduled, 4)
            rec.e2e_s = round(last - scheduled, 4)
            rec.max_gap_s = round(max_gap, 4)
            if rec.completion_tokens and rec.completion_tokens > 1:
                rec.itl_s = round((last - first) / (rec.completion_tokens - 1), 5)
        elif not rec.error:
            rec.error = "no tokens received"
        return rec


def _read_usage(rec: RequestRecord, usage: dict) -> None:
    rec.prompt_tokens = usage.get("prompt_tokens")
    rec.completion_tokens = usage.get("completion_tokens")
    details = usage.get("prompt_tokens_details") or {}
    rec.cached_tokens = details.get("cached_tokens") or 0


def _read_router_headers(rec: RequestRecord, headers) -> None:
    """The router reports its decision in response headers (absent when sending direct)."""
    if HEADER_PREFIX + "Replica" not in headers:
        return
    rec.replica = int(headers[HEADER_PREFIX + "Replica"])
    rec.policy = headers.get(HEADER_PREFIX + "Policy", "")
    rec.reason = headers.get(HEADER_PREFIX + "Reason", "")
    rec.matched_chunks = int(headers.get(HEADER_PREFIX + "Matched", 0))
    rec.loads = [int(x) for x in headers.get(HEADER_PREFIX + "Loads", "").split(",") if x]
    rec.router_overhead_us = int(headers.get(HEADER_PREFIX + "Overhead-Us", 0))
