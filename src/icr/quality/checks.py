"""Quality checks that go next to the speed numbers.

- GSM8K accuracy for each quantization (does going cheaper cost answers?).
- Greedy-output match for speculative decoding. Speculative decoding should not change
  greedy outputs, but batching alone makes two baseline runs differ slightly, so the
  spec-vs-baseline match rate is reported next to a baseline-vs-baseline match rate.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import aiohttp

from icr import config

GSM8K_INSTRUCTION = (
    "Solve the problem step by step. Finish with a final line of the form "
    "'Answer: <number>' with only the number."
)
NUMBER = r"-?\d[\d,]*(?:\.\d+)?"


def gold_answer(row: dict) -> str:
    """GSM8K stores the final answer after '####'."""
    return row["answer"].split("####")[-1].strip().replace(",", "")


def parse_answer(text: str) -> str | None:
    """The number after the last 'Answer:', else the last number in the text."""
    tagged = re.findall(rf"Answer:\s*\$?\s*({NUMBER})", text)
    found = tagged or re.findall(NUMBER, text)
    return found[-1].replace(",", "").rstrip(".") if found else None


def is_correct(predicted: str | None, gold: str) -> bool:
    if predicted is None:
        return False
    try:
        return abs(float(predicted) - float(gold)) < 1e-6
    except ValueError:
        return False


async def complete(session, url: str, messages: list[dict], max_tokens: int) -> str:
    """One non-streaming greedy completion that stops at the model's natural end."""
    body = {
        "model": config.SERVED_MODEL_NAME,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    async with session.post(f"{url}/v1/chat/completions", json=body) as resp:
        resp.raise_for_status()
        data = await resp.json()
    return data["choices"][0]["message"]["content"] or ""


async def complete_all(url: str, prompts: list[list[dict]], max_tokens: int, concurrency: int):
    """Greedy outputs for every prompt, at most `concurrency` in flight."""
    gate = asyncio.Semaphore(concurrency)
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as session:

        async def one(messages: list[dict]) -> str:
            async with gate:
                return await complete(session, url, messages, max_tokens)

        return list(await asyncio.gather(*(one(p) for p in prompts)))


def load_gsm8k(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text("utf-8").splitlines() if line]


async def gsm8k_accuracy(url: str, rows: list[dict], concurrency: int = 32) -> dict:
    prompts = [
        [
            {"role": "system", "content": GSM8K_INSTRUCTION},
            {"role": "user", "content": r["question"]},
        ]
        for r in rows
    ]
    outputs = await complete_all(url, prompts, max_tokens=512, concurrency=concurrency)
    predictions = [parse_answer(o) for o in outputs]
    correct = sum(is_correct(p, gold_answer(r)) for p, r in zip(predictions, rows, strict=True))
    return {
        "questions": len(rows),
        "correct": correct,
        "accuracy": round(correct / len(rows), 4),
        "unparsed": sum(p is None for p in predictions),
    }


def match_rate(a: list[str], b: list[str]) -> dict:
    """How often two sets of greedy outputs agree exactly, and how far they agree on average."""
    exact = sum(x == y for x, y in zip(a, b, strict=True))
    prefix = [_common_prefix(x, y) / max(len(x), len(y), 1) for x, y in zip(a, b, strict=True)]
    return {
        "prompts": len(a),
        "exact_match": round(exact / len(a), 4),
        "mean_common_prefix": round(sum(prefix) / len(prefix), 4),
    }


def _common_prefix(x: str, y: str) -> int:
    n = 0
    for cx, cy in zip(x, y, strict=False):
        if cx != cy:
            break
        n += 1
    return n
