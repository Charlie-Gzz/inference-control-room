"""Workload generator: determinism, prefix structure, arrival scaling."""

import pytest

from icr.routing.prefix import canonical_text
from icr.workloads import burstgpt, generator
from icr.workloads.mixes import MIXES
from icr.workloads.text import estimate_tokens


def workload(mix, seed=1, rate=5.0, duration=60.0):
    return generator.steady_workload(mix, seed, rate, duration, warmup_s=10.0)


@pytest.mark.parametrize("mix", MIXES)
def test_same_seed_gives_identical_requests(mix):
    a, b = workload(mix), workload(mix)
    assert [s.to_dict() for s in a] == [s.to_dict() for s in b]


def test_different_seed_gives_different_requests():
    assert [s.messages for s in workload("chat", 1)] != [s.messages for s in workload("chat", 2)]


@pytest.mark.parametrize("mix", MIXES)
def test_one_request_per_arrival_in_time_order(mix):
    specs = workload(mix)
    times = [s.scheduled_s for s in specs]
    assert len(specs) == 300
    assert times == sorted(times)
    assert {s.phase for s in specs} == {"warmup", "measured"}
    assert all(s.phase == "warmup" for s in specs if s.scheduled_s < 10.0)


def test_chat_turns_resend_the_history():
    sessions: dict[str, list] = {}
    for s in workload("chat", duration=120.0):
        if s.kind == "chat":
            sessions.setdefault(s.group, []).append(s)
    multi = [turns for turns in sessions.values() if len(turns) > 1]
    assert len(multi) > 10
    for turns in multi:
        for prev, cur in zip(turns, turns[1:], strict=False):
            assert cur.turn == prev.turn + 1
            assert cur.scheduled_s > prev.scheduled_s  # think time passed
            assert cur.messages[: len(prev.messages)] == prev.messages
            assert canonical_text(cur.messages).startswith(canonical_text(prev.messages))


def test_no_sharing_control_shares_no_prefix():
    heads = [canonical_text(s.messages)[:64] for s in workload("no-sharing")]
    assert len(set(heads)) == len(heads)


def test_rag_requests_reuse_documents():
    specs = workload("rag")
    groups = [s.group for s in specs]
    assert len(set(groups)) < len(groups) / 2  # documents are reused a lot
    by_doc: dict[str, set] = {}
    for s in specs:
        by_doc.setdefault(s.group, set()).add(s.messages[0]["content"])
    assert all(len(prefixes) == 1 for prefixes in by_doc.values())


def test_agentic_tasks_share_a_long_preamble_and_grow():
    specs = workload("agentic", duration=120.0)
    preambles = {s.messages[0]["content"] for s in specs}
    assert len(preambles) <= MIXES["agentic"].agent_types
    assert all(estimate_tokens(p) > 2000 for p in preambles)
    later = [s for s in specs if s.turn > 1]
    assert later and all(len(s.messages) == 2 + 2 * (s.turn - 1) for s in later)


def test_prompts_fit_the_context_window():
    for mix in MIXES:
        for s in workload(mix, duration=120.0):
            tokens = estimate_tokens(canonical_text(s.messages).decode()) + s.max_tokens
            assert tokens < 7500, (mix, s.id, tokens)


def test_scaled_arrivals_hit_the_target_rate():
    arrivals = burstgpt.scaled_arrivals("steady", 600, rate_rps=10.0, seed=3)
    assert len(arrivals) == 600 and arrivals[0] == 0.0
    assert arrivals == sorted(arrivals)
    assert arrivals[-1] == pytest.approx(60.0, rel=0.01)
    assert arrivals == burstgpt.scaled_arrivals("steady", 600, rate_rps=10.0, seed=3)


def test_bursty_segment_is_burstier_than_steady():
    steady = burstgpt.burstiness(burstgpt.load_segment("steady"))
    bursty = burstgpt.burstiness(burstgpt.load_segment("bursty"))
    assert bursty > 2 * steady


def test_ramp_levels_step_up():
    rates = [2.0, 4.0, 6.0]
    specs = generator.ramp_workload("chat", 1, rates, level_s=30.0, warmup_s=10.0)
    assert sum(s.phase == "warmup" for s in specs) == 20
    for level, rate in enumerate(rates):
        rows = [s for s in specs if s.phase == "measured" and s.level == level]
        assert len(rows) == round(rate * 30.0)
        assert all(10.0 + 30.0 * level <= s.scheduled_s <= 10.0 + 30.0 * (level + 1) for s in rows)
