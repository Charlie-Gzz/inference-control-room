"""Seeded English-like filler text with a known approximate token count.

The text is grammatical but meaningless. What matters for serving is its length and
which requests share which prefixes, and both are controlled exactly.
"""

from __future__ import annotations

import random

# Measured once with the Qwen2.5 tokenizer on this generator's output (6.12 to 6.14 for
# passages of 100 to 2,000 tokens). Real token counts come back from vLLM in every result.
CHARS_PER_TOKEN = 6.13

ADJECTIVES = (
    "regional quarterly primary shared internal external pending archived verified delayed "
    "priority standard premium seasonal temporary permanent manual automated critical minor "
    "local remote annual weekly updated legacy partial complete duplicate original"
).split()
NOUNS = (
    "ticket invoice schedule platform carriage signal depot timetable passenger refund "
    "account order shipment warehouse customer supplier contract policy report ledger "
    "sensor gateway cluster replica request session token budget forecast audit route "
    "booking payment voucher station crossing junction terminal inspection permit record"
).split()
VERBS = (
    "confirms updates delays reroutes cancels approves rejects escalates archives reviews "
    "schedules validates forwards records flags resolves reopens assigns merges splits "
    "refunds charges notifies inspects transfers reserves releases renews suspends audits"
).split()
TAILS = (
    "before the next departure|within two business days|after a manual review|"
    "unless the supervisor objects|during the overnight window|for every affected customer|"
    "according to the published policy|when capacity allows|without further notice|"
    "as soon as the report is filed|until the audit is complete|on the following morning|"
    "in the regional office|across all connected systems|at no additional cost"
).split("|")


def estimate_tokens(text: str) -> int:
    return round(len(text) / CHARS_PER_TOKEN)


def sentence(rng: random.Random) -> str:
    return (
        f"The {rng.choice(ADJECTIVES)} {rng.choice(NOUNS)} {rng.choice(VERBS)} "
        f"the {rng.choice(ADJECTIVES)} {rng.choice(NOUNS)} {rng.choice(TAILS)}."
    )


def passage(rng: random.Random, tokens: int) -> str:
    """Sentences until the estimated token count reaches `tokens`."""
    target_chars = tokens * CHARS_PER_TOKEN
    parts: list[str] = []
    length = 0
    while length < target_chars:
        parts.append(sentence(rng))
        length += len(parts[-1]) + 1
    return " ".join(parts)
