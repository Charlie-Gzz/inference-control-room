"""Seeded workload generator: who sends what, and which requests share a prefix.

A workload is a list of `RequestSpec`, one per arrival time. Same mix + seed + arrivals
gives byte-identical requests, so every routing policy is tested on the same traffic.

Sessions produce turns. For each arrival slot the generator either continues a session
whose think time has passed, or starts a new one. Chat history uses scripted assistant
replies (not the model's real output), so the request sequence never depends on the policy.
"""

from __future__ import annotations

import bisect
import random
from collections import deque
from dataclasses import asdict, dataclass, field

from icr.workloads import burstgpt
from icr.workloads.mixes import MIXES, Mix
from icr.workloads.text import passage, sentence


@dataclass
class RequestSpec:
    id: int
    scheduled_s: float  # arrival time, seconds from run start
    kind: str  # chat | oneoff | rag | agentic | unique
    group: str  # prefix group (conversation, document or task): colors the car in the replay
    tenant: str
    turn: int
    messages: list[dict]
    max_tokens: int
    phase: str = "measured"  # warmup | measured
    level: int = 0  # traffic level index in a capacity ramp

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Session:
    """A source of related requests. `next_turn` returns messages for the next request."""

    kind: str
    group: str
    tenant: str
    turns_left: int
    messages: list[dict]
    rng: random.Random
    mix: Mix
    turn: int = 0
    ready_at: float = 0.0
    extra: dict = field(default_factory=dict)

    def next_turn(self) -> list[dict]:
        """Append this turn's new content and return a copy of the full message list."""
        r, m = self.rng, self.mix
        if self.turn > 0:  # scripted reply to the previous turn becomes history
            if self.kind == "agentic":
                self.messages.append(_msg("assistant", "Calling tool. " + sentence(r)))
                self.messages.append(_msg("user", "Tool result: " + passage(r, m.step_tokens)))
            else:
                self.messages.append(_msg("assistant", passage(r, r.randint(*m.reply_tokens))))
        if self.kind in ("chat", "oneoff"):
            self.messages.append(_msg("user", passage(r, r.randint(*m.user_tokens))))
        self.turn += 1
        self.turns_left -= 1
        return [dict(x) for x in self.messages]


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _zipf_pick(rng: random.Random, n: int, s: float) -> int:
    """Index in [0, n) with probability proportional to 1 / (rank ^ s)."""
    weights = [1 / (i + 1) ** s for i in range(n)]
    return rng.choices(range(n), weights)[0]


class Generator:
    """Builds sessions for one mix. All randomness comes from the seed."""

    def __init__(self, mix: Mix, seed: int):
        self.mix, self.rng = mix, random.Random(seed)
        r, m = random.Random(f"{seed}-static"), mix
        self.systems = [
            f"You are assistant {i} for tenant {i}. " + passage(r, r.randint(*m.system_tokens))
            for i in range(m.tenants)
        ]
        self.documents = [
            [f"Document {t}-{d}. " + passage(r, r.randint(*m.doc_tokens)) for d in range(m.docs)]
            for t in range(m.tenants if m.docs else 0)
        ]
        self.preambles = [
            f"Agent type {a}. Tool definitions follow. " + passage(r, m.preamble_tokens)
            for a in range(m.agent_types)
        ]
        self.counter = 0

    def _turns(self, mean: float, cap: int) -> int:
        """Geometric number of turns with the given mean, between 1 and cap."""
        turns = 1
        while turns < cap and self.rng.random() > 1 / mean:
            turns += 1
        return turns

    def new_session(self) -> Session:
        r, m = self.rng, self.mix
        self.counter += 1
        sid = self.counter
        srng = random.Random(f"{r.random()}")  # per-session stream, drawn from the main one
        kind = r.choices(list(m.kinds), list(m.kinds.values()))[0]
        base = dict(turns_left=1, rng=srng, mix=m)
        if kind == "chat":
            t = _zipf_pick(r, m.tenants, m.zipf)
            return Session(
                "chat", f"conv-{sid}", f"tenant-{t}", messages=[_msg("system", self.systems[t])],
                **{**base, "turns_left": self._turns(m.mean_turns, m.max_turns)},
            )  # fmt: skip
        if kind == "oneoff":
            return Session("oneoff", f"oneoff-{sid}", "none", messages=[], **base)
        if kind == "rag":
            t = _zipf_pick(r, m.tenants, m.zipf)
            d = _zipf_pick(r, m.docs, m.zipf)
            question = "Using the document, answer this question. " + sentence(srng)
            messages = [
                _msg("system", self.systems[t] + "\n\n" + self.documents[t][d]),
                _msg("user", question),
            ]
            return Session("rag", f"doc-{t}-{d}", f"tenant-{t}", messages=messages, **base)
        if kind == "agentic":
            a = _zipf_pick(r, m.agent_types, m.zipf)
            messages = [
                _msg("system", self.preambles[a]),
                _msg("user", f"Task {sid}. " + passage(srng, m.task_tokens)),
            ]
            return Session(
                "agentic", f"task-{sid}", f"agent-{a}", messages=messages,
                **{**base, "turns_left": self._turns(m.mean_turns, m.max_turns)},
            )  # fmt: skip
        # "unique": the no-sharing control. Same length profile as chat, nothing shared.
        tokens = r.randint(*m.system_tokens)
        for _ in range(self._turns(m.mean_turns, m.max_turns) - 1):
            tokens += r.randint(*m.user_tokens) + r.randint(*m.reply_tokens)
        text = f"Request {sid}-{srng.getrandbits(48):x}. " + passage(srng, tokens)
        return Session("unique", f"unique-{sid}", "none", messages=[_msg("user", text)], **base)


def build(
    mix_name: str | Mix,
    seed: int,
    arrivals: list[float],
    warmup_s: float = 0.0,
    level_starts: list[float] | None = None,
) -> list[RequestSpec]:
    """One request per arrival time. Deterministic for a given mix, seed and arrivals."""
    mix = MIXES[mix_name] if isinstance(mix_name, str) else mix_name
    gen = Generator(mix, seed)
    lengths = burstgpt.response_token_quantiles()
    waiting: deque[Session] = deque()  # sessions with turns left, oldest first
    specs: list[RequestSpec] = []
    for i, t in enumerate(arrivals):
        ready = next((s for s in waiting if s.ready_at <= t), None)
        if ready is not None and gen.rng.random() < mix.continue_prob:
            waiting.remove(ready)
            session = ready
        else:
            session = gen.new_session()
        messages = session.next_turn()
        out = lengths[gen.rng.randrange(len(lengths))]
        specs.append(
            RequestSpec(
                id=i,
                scheduled_s=round(t, 4),
                kind=session.kind,
                group=session.group,
                tenant=session.tenant,
                turn=session.turn,
                messages=messages,
                max_tokens=min(max(out, mix.min_output), mix.max_output),
                phase="warmup" if t < warmup_s else "measured",
                level=bisect.bisect_right(level_starts, t) - 1 if level_starts else 0,
            )
        )
        if session.turns_left > 0:
            session.ready_at = t + gen.rng.uniform(*mix.think_s)
            waiting.append(session)
    return specs


def steady_workload(
    mix: str | Mix,
    seed: int,
    rate_rps: float,
    duration_s: float,
    warmup_s: float = 0.0,
    segment: str = "steady",
) -> list[RequestSpec]:
    """Fixed-traffic run: BurstGPT arrivals rescaled to a mean of `rate_rps`."""
    count = round(rate_rps * duration_s)
    arrivals = burstgpt.scaled_arrivals(segment, count, rate_rps, seed)
    return build(mix, seed, arrivals, warmup_s)


def ramp_workload(
    mix: str | Mix,
    seed: int,
    rates_rps: list[float],
    level_s: float,
    warmup_s: float = 0.0,
    segment: str = "steady",
) -> list[RequestSpec]:
    """Stepped ramp: consecutive slices of the trace, each rescaled to its level's rate.

    The warmup runs at the first level's rate and is not part of any level.
    """
    arrivals: list[float] = []
    level_starts: list[float] = []
    offset, clock = 0, 0.0
    plan = ([(rates_rps[0], warmup_s)] if warmup_s else []) + [(r, level_s) for r in rates_rps]
    for i, (rate, seconds) in enumerate(plan):
        count = round(rate * seconds)
        times = burstgpt.scaled_arrivals(segment, count, rate, seed, offset)
        arrivals += [clock + t for t in times]
        if not (warmup_s and i == 0):
            level_starts.append(clock)
        offset += count
        clock += seconds
    return build(mix, seed, arrivals, warmup_s, level_starts)
