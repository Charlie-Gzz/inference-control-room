"""The four workload mixes. Sizes come from the workload descriptions and are frozen.

Token counts are estimates from text length (see `text.CHARS_PER_TOKEN`).
Prefix pools are sized so the distinct shared prefixes exceed what one replica can cache
(PLAN.md section 1.6). The measured KV cache use is reported with the results.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mix:
    name: str
    kinds: dict[str, float]  # session kind -> share of new sessions
    tenants: int = 0
    zipf: float = 1.0  # popularity skew for tenants, documents, agent types
    system_tokens: tuple[int, int] = (400, 800)
    user_tokens: tuple[int, int] = (40, 120)
    reply_tokens: tuple[int, int] = (60, 250)  # scripted assistant replies in the history
    mean_turns: float = 5.0
    max_turns: int = 8
    continue_prob: float = 0.8  # chance a ready session takes the next arrival slot
    think_s: tuple[float, float] = (8.0, 25.0)  # user think time between turns
    docs: int = 0  # documents per tenant (rag)
    doc_tokens: tuple[int, int] = (1500, 2500)
    agent_types: int = 0
    preamble_tokens: int = 2500  # tool definitions shared by one agent type
    task_tokens: int = 150
    step_tokens: int = 250  # tool result appended at every agent step
    min_output: int = 16
    max_output: int = 400
    notes: str = field(default="", compare=False)


MIXES: dict[str, Mix] = {
    "chat": Mix(
        name="chat",
        kinds={"chat": 0.9, "oneoff": 0.1},
        tenants=24,
        notes="Multi-turn chat. 24 tenants with their own system prompt. 10% short one-offs.",
    ),
    "rag": Mix(
        name="rag",
        kinds={"rag": 1.0},
        tenants=8,
        system_tokens=(200, 400),
        docs=20,
        notes="Single-turn questions over 160 documents (8 tenants x 20), Zipf popularity.",
    ),
    "agentic": Mix(
        name="agentic",
        kinds={"agentic": 1.0},
        agent_types=6,
        mean_turns=6.0,
        max_turns=10,
        think_s=(2.0, 6.0),  # tools answer faster than people
        max_output=150,  # agent steps are short tool calls
        notes="Agent loops. 6 agent types share a long tool preamble; each task grows by steps.",
    ),
    "no-sharing": Mix(
        name="no-sharing",
        kinds={"unique": 1.0},
        notes="Control. Same length profile as chat, but no two requests share a prefix.",
    ),
}
