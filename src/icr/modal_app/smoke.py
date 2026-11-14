"""M0 smoke test: one vLLM replica on one L4, 20 requests, /metrics, and resource use.

Answers four questions before any real spend:
1. Does the AWQ model load in the pinned vLLM, and how long does startup take?
2. Does `usage.prompt_tokens_details.cached_tokens` come back per request?
3. What do the /metrics names and the prefix-cache reset endpoint look like?
4. How much CPU and RAM does one replica use (to size the fleet container)?
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time

import aiohttp

from icr import config
from icr.modal_app.sysinfo import ResourceSampler, nvidia_smi
from icr.modal_app.vllm_proc import ServerConfig, VllmServer

SYSTEM_PROMPT = (
    "You are the support assistant for Northwind Rail, a regional passenger railway. "
    "Answer briefly and only from the policies below.\n"
    + "\n".join(
        f"Policy {i}: Tickets in fare class {i} may be changed up to {i + 1} hours before "
        f"departure for a fee of {2 * i + 5} dollars. Refunds for class {i} take {i + 2} "
        "business days and are paid to the original payment method."
        for i in range(1, 41)
    )
)


async def chat(session: aiohttp.ClientSession, url: str, system: str, user: str) -> dict:
    """One streaming chat request. Returns timings and the usage block."""
    payload = {
        "model": config.SERVED_MODEL_NAME,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 64,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    start = time.monotonic()
    first, usage, text = None, None, []
    async with session.post(f"{url}/v1/chat/completions", json=payload) as resp:
        resp.raise_for_status()
        async for raw in resp.content:
            line = raw.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices", []):
                if choice["delta"].get("content"):
                    first = first or time.monotonic()
                    text.append(choice["delta"]["content"])
    end = time.monotonic()
    return {
        "user": user,
        "ttft_s": round((first or end) - start, 4),
        "total_s": round(end - start, 4),
        "usage": usage,
        "text": "".join(text),
    }


async def run_requests(url: str) -> dict:
    questions = [f"What is the change fee for fare class {i}?" for i in range(1, 13)]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
        # 4 one at a time: the 2nd to 4th should report cached prompt tokens.
        sequential = [await chat(session, url, SYSTEM_PROMPT, q) for q in questions[:4]]
        # 16 at once: 8 share the long system prompt, 8 have unique short ones.
        shared = [chat(session, url, SYSTEM_PROMPT, q) for q in questions[4:12]]
        unique = [
            chat(session, url, f"You are assistant number {i}. Be brief.", "Name one prime number.")
            for i in range(8)
        ]
        concurrent = await asyncio.gather(*shared, *unique)
    return {"sequential": sequential, "concurrent": list(concurrent)}


def run_smoke() -> dict:
    sampler = ResourceSampler().start()
    server = VllmServer(ServerConfig(), port=8000)
    result: dict = {"config": server.cfg.to_dict(), "gpu": nvidia_smi()}
    try:
        server.start()
        result["startup_seconds"] = round(server.wait_ready(timeout=600), 1)
        startup_mark = sampler.mark()
        result["requests"] = asyncio.run(run_requests(server.url))
        result["metrics_text"] = server.metrics_text()
        result["reset_prefix_cache_ok"] = server.reset_prefix_cache()
        after_reset = asyncio.run(_one_after_reset(server.url))
        result["after_reset"] = after_reset
        result["resources_startup"] = sampler.summary(0, startup_mark)
        result["resources_serving"] = sampler.summary(startup_mark)
        result["ok"] = True
    except Exception as e:  # return the failure with logs instead of losing them
        result["ok"] = False
        result["error"] = repr(e)
    finally:
        sampler.stop()
        server.stop()
        result["vllm_log_tail"] = server.log_tail(250)
        result["vllm_version"] = subprocess.run(
            ["vllm", "--version"], capture_output=True, text=True
        ).stdout.strip()
    return result


async def _one_after_reset(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        return await chat(session, url, SYSTEM_PROMPT, "What is the change fee for fare class 1?")
