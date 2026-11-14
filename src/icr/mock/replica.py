"""MOCK vLLM replica for free local development. Never a source of published numbers.

Simulates what matters to the router, autoscaler, load generator and recorder:
- prefill time proportional to the prompt tokens that are NOT in the prefix cache,
- a prefix cache of hashed 16-token blocks with LRU eviction,
- continuous batching: every engine step emits one token for every running request,
  and steps get slower as the batch grows,
- a waiting queue once `max_num_seqs` requests are running,
- the OpenAI streaming API, `/health`, `/metrics` (vLLM's names) and `/reset_prefix_cache`.
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from aiohttp import web

from icr import clock
from icr.routing.prefix import canonical_text, prefix_hashes
from icr.workloads.text import CHARS_PER_TOKEN

BLOCK_TOKENS = 16
BLOCK_BYTES = round(BLOCK_TOKENS * CHARS_PER_TOKEN)


@dataclass
class MockParams:
    """Rough L4-like timing. Only the shape matters; real numbers come from real runs."""

    prefill_tokens_per_s: float = 4000.0
    step_base_s: float = 0.025  # one decode step with one request
    step_per_seq_s: float = 0.0012  # extra step time per extra running request
    max_num_seqs: int = 48
    kv_capacity_tokens: int = 120_000
    startup_s: float = 0.0  # /health answers 503 until this long after start
    time_scale: float = 1.0  # < 1 runs the simulation faster than real time


@dataclass
class _Request:
    prompt_tokens: int
    max_tokens: int
    blocks: list[int]
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cached_tokens: int = 0
    emitted: int = 0
    cancelled: bool = False


class MockReplica:
    def __init__(self, replica_id: int, params: MockParams | None = None):
        self.id = replica_id
        self.params = params or MockParams()
        self.cache: OrderedDict[int, None] = OrderedDict()
        self.waiting: deque[_Request] = deque()
        self.running: list[_Request] = []
        self.counters = dict.fromkeys(
            ["prompt_tokens", "generation_tokens", "prefix_queries", "prefix_hits", "requests"], 0
        )
        self.started = clock.now()
        self._wake = asyncio.Event()
        self._engine_task: asyncio.Task | None = None

    # --- engine ---------------------------------------------------------------

    def _cache_lookup_and_store(self, blocks: list[int]) -> int:
        """Number of leading blocks already cached. Then cache all of them (LRU)."""
        hit = 0
        for b in blocks:
            if b not in self.cache:
                break
            hit += 1
        for b in reversed(blocks):  # shortest prefix ends up most recently used
            self.cache[b] = None
            self.cache.move_to_end(b)
        capacity = self.params.kv_capacity_tokens // BLOCK_TOKENS
        while len(self.cache) > capacity:
            self.cache.popitem(last=False)
        return hit

    async def _engine(self) -> None:
        p = self.params
        step_end = clock.now()  # when the current step ends; steps never drift
        while True:
            if not self.running and not self.waiting:
                self._wake.clear()
                await self._wake.wait()
                step_end = clock.now()
            prefill_s = 0.0
            while self.waiting and len(self.running) < p.max_num_seqs:
                req = self.waiting.popleft()
                if req.cancelled:
                    continue
                hit_blocks = self._cache_lookup_and_store(req.blocks)
                req.cached_tokens = min(hit_blocks * BLOCK_TOKENS, req.prompt_tokens)
                self.counters["prefix_queries"] += req.prompt_tokens
                self.counters["prefix_hits"] += req.cached_tokens
                self.counters["prompt_tokens"] += req.prompt_tokens
                prefill_s += (req.prompt_tokens - req.cached_tokens) / p.prefill_tokens_per_s
                self.running.append(req)
            step_s = p.step_base_s + p.step_per_seq_s * max(len(self.running) - 1, 0) + prefill_s
            step_end += step_s * p.time_scale
            await clock.sleep_until(step_end)
            await asyncio.sleep(0)  # always yield, even when running behind
            for req in list(self.running):
                req.emitted += 1
                self.counters["generation_tokens"] += 1
                done = req.emitted >= req.max_tokens or req.cancelled
                req.queue.put_nowait(done)
                if done:
                    self.running.remove(req)
                    self.counters["requests"] += 1

    # --- HTTP -----------------------------------------------------------------

    def is_ready(self) -> bool:
        return clock.now() - self.started >= self.params.startup_s * self.params.time_scale

    async def health(self, request: web.Request) -> web.Response:
        return web.Response(status=200 if self.is_ready() else 503)

    async def reset_prefix_cache(self, request: web.Request) -> web.Response:
        self.cache.clear()
        return web.json_response({"success": True})

    async def metrics(self, request: web.Request) -> web.Response:
        p, c = self.params, self.counters
        in_use = sum(r.prompt_tokens + r.emitted for r in self.running)
        label = '{engine="0",model_name="llm"}'
        values = {
            "vllm:num_requests_running": len(self.running),
            "vllm:num_requests_waiting": len(self.waiting),
            "vllm:kv_cache_usage_perc": min(in_use / p.kv_capacity_tokens, 1.0),
            "vllm:prefix_cache_queries_total": c["prefix_queries"],
            "vllm:prefix_cache_hits_total": c["prefix_hits"],
            "vllm:prompt_tokens_total": c["prompt_tokens"],
            "vllm:prompt_tokens_cached_total": c["prefix_hits"],
            "vllm:generation_tokens_total": c["generation_tokens"],
            "mock:prefix_cache_fill": len(self.cache) * BLOCK_TOKENS / p.kv_capacity_tokens,
        }
        text = "".join(f"{name}{label} {float(v)}\n" for name, v in values.items())
        return web.Response(text="# MOCK replica, not vLLM\n" + text)

    async def chat(self, request: web.Request) -> web.StreamResponse:
        if not self.is_ready():
            return web.Response(status=503)
        body = await request.json()
        text = canonical_text(body.get("messages", []))
        req = _Request(
            prompt_tokens=max(round(len(text) / CHARS_PER_TOKEN), 1),
            max_tokens=int(body.get("max_tokens", 64)),
            blocks=prefix_hashes(text, BLOCK_BYTES, 1 << 30),
        )
        self.waiting.append(req)
        self._wake.set()

        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        try:
            done = False
            while not done:
                done = await req.queue.get()
                chunk = {
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {"content": "tok "}}],
                    "usage": self._usage(req),
                }
                await resp.write(f"data: {json.dumps(chunk)}\n\n".encode())
            final = {"object": "chat.completion.chunk", "choices": [], "usage": self._usage(req)}
            await resp.write(f"data: {json.dumps(final)}\n\ndata: [DONE]\n\n".encode())
        except (ConnectionResetError, asyncio.CancelledError):
            req.cancelled = True
            raise
        return resp

    @staticmethod
    def _usage(req: _Request) -> dict:
        return {
            "prompt_tokens": req.prompt_tokens,
            "completion_tokens": req.emitted,
            "total_tokens": req.prompt_tokens + req.emitted,
            "prompt_tokens_details": {"cached_tokens": req.cached_tokens},
        }

    def app(self) -> web.Application:
        app = web.Application()
        app.add_routes(
            [
                web.get("/health", self.health),
                web.get("/metrics", self.metrics),
                web.post("/reset_prefix_cache", self.reset_prefix_cache),
                web.post("/v1/chat/completions", self.chat),
            ]
        )

        async def start_engine(_: web.Application) -> None:
            self._engine_task = asyncio.create_task(self._engine())

        async def stop_engine(_: web.Application) -> None:
            if self._engine_task:
                self._engine_task.cancel()

        app.on_startup.append(start_engine)
        app.on_cleanup.append(stop_engine)
        return app
