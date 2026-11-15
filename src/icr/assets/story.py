"""Storyboards for the videos, built from the real results.

The story follows the numbers. Which run and which moment are shown is decided by a
rule (the window where the two routers differ most), and every caption that states a
result is filled in from the measured values. If prefix-aware routing does not win, the
captions say so.

Outputs (read by the site's record mode):
- `site/data/story-main.json`      about 90 s, 1920x1080
- `site/data/story-loop.json`      20 s loop for the README GIF
- `site/data/story-vertical.json`  the main story at 1080x1920
"""

from __future__ import annotations

import json

from icr.analysis import metrics
from icr.analysis.runs import Run, load
from icr.analysis.site_data import DATA_DIR

REPO_URL = "github.com/Charlie-Gzz/inference-control-room"
WINDOW_S = 40.0  # replay seconds shown in the comparison scenes
STEP_S = 5.0
A, B = "round-robin", "prefix-aware"
NUMBER_WORDS = {2: "Two", 4: "Four"}


def window_stats(rows: list[dict], t0: float, t1: float) -> dict:
    """Goodput, p95 TTFT and cache hit rate of the requests arriving in [t0, t1)."""
    inside = [r for r in rows if t0 <= r["scheduled_s"] < t1]
    ok = [r for r in inside if not metrics.failed(r)]
    prompt = sum(r.get("prompt_tokens") or 0 for r in ok)
    return {
        "requests": len(inside),
        "goodput": sum(metrics.is_good(r) for r in inside) / len(inside) if inside else None,
        "ttft_p95_s": metrics.percentile([r["ttft_s"] for r in ok], 95),
        "cache_hit_rate": sum(r.get("cached_tokens") or 0 for r in ok) / prompt if prompt else 0.0,
    }


def choose_window(a_rows: list[dict], b_rows: list[dict], start: float, end: float) -> float:
    """Start of the WINDOW_S window where policy A falls furthest behind policy B.

    The gap is measured in goodput first and p95 time to first token second. When the
    two never differ, this is simply the busiest window.
    """
    best, best_key = start, None
    t = start
    while t + WINDOW_S <= end:
        a, b = window_stats(a_rows, t, t + WINDOW_S), window_stats(b_rows, t, t + WINDOW_S)
        if a["requests"] and b["requests"]:
            gap = (b["goodput"] or 0) - (a["goodput"] or 0)
            slower = (a["ttft_p95_s"] or 0) - (b["ttft_p95_s"] or 0)
            key = (round(gap, 3), round(slower, 3), a["requests"])
            if best_key is None or key > best_key:
                best, best_key = t, key
        t += STEP_S
    return best


def pick_request(rows: list[dict], after: float) -> int:
    """Arrival-order index of a typical cache-hit request for the opening shot.

    It has to be a real request that tells the story on its own: a chat turn with most of
    its prompt cached, a normal time to first token, and enough output to watch.
    """
    ordered = sorted(rows, key=lambda r: r["scheduled_s"])
    for k, r in enumerate(ordered):
        prompt = r.get("prompt_tokens") or 0
        if (
            r["scheduled_s"] >= after
            and r.get("tenant") != "none"
            and prompt > 600
            and (r.get("cached_tokens") or 0) / prompt > 0.6
            and (r.get("ttft_s") or 9) < 0.8
            and (r.get("completion_tokens") or 0) >= 60
        ):
            return k
    return 0


def _scene_base(run: Run) -> dict:
    spec = run.meta["run"]
    return {"scenario": f"{spec['kind']}:{run.meta['workload']}", "seed": run.meta["seed"]}


def comparison(a: Run, b: Run) -> dict:
    """The window to show and what happened in it, for both policies."""
    a_rows, b_rows = a.requests, b.requests
    warmup = a.meta["run"].get("warmup_s", 0.0)
    end = max(r["scheduled_s"] for r in a_rows)
    t0 = choose_window(a_rows, b_rows, warmup, end)
    return {
        "t0": t0,
        A: window_stats(a_rows, t0, t0 + WINDOW_S),
        B: window_stats(b_rows, t0, t0 + WINDOW_S),
    }


def captions_a(c: dict) -> list[dict]:
    a = c[A]
    out = [
        {"at": 0.6, "for": 5.0, "top": True, "text": "Round-robin routing: every GPU takes its turn."},
        {"at": 6.4, "for": 5.6, "top": True,
         "text": "A follow-up question often lands on a GPU that never saw the conversation."},
    ]  # fmt: skip
    if a["goodput"] is not None and a["goodput"] < 0.97:
        text = f"The GPUs fall behind. {(1 - a['goodput']) * 100:.0f}% of requests miss the latency target."
    else:
        text = f"Only {a['cache_hit_rate'] * 100:.0f}% of the prompt comes from cache. The rest is read again."
    out.append({"at": 12.8, "for": 5.6, "top": True, "text": text})
    return out


def captions_b(c: dict) -> list[dict]:
    a, b = c[A], c[B]
    out = [
        {"at": 0.6, "for": 5.4, "top": True,
         "text": "Same requests, same GPUs. This router knows where each cache is."},
        {"at": 6.8, "for": 5.8, "top": True,
         "text": f"{b['cache_hit_rate'] * 100:.0f}% of prompt tokens reused, against "
                 f"{a['cache_hit_rate'] * 100:.0f}% with round-robin."},
    ]  # fmt: skip
    ta, tb = a["ttft_p95_s"], b["ttft_p95_s"]
    if a["goodput"] is not None and b["goodput"] is not None and b["goodput"] - a["goodput"] > 0.03:
        text = (f"{b['goodput'] * 100:.0f}% of requests meet the latency target, "
                f"against {a['goodput'] * 100:.0f}%.")  # fmt: skip
    elif ta and tb and tb < 0.9 * ta:
        text = f"p95 time to first token: {tb:.2f} s, against {ta:.2f} s."
    elif ta and tb and tb > 1.1 * ta:
        text = f"Here it is slower to the first token: {tb:.2f} s, against {ta:.2f} s."
    else:
        text = "Latency is about the same here. What changes is how much work is reused."
    out.append({"at": 13.4, "for": 6.0, "top": True, "text": text})
    return out


def number_items(headline: dict) -> list[dict]:
    """The headline numbers as they were measured, with their real signs."""
    items = []
    for key, label in (
        ("ttft_p95_change", "p95 time to first token"),
        ("capacity_change", "traffic served within the latency target"),
        ("cost_change", "cost per million tokens"),
    ):
        value = headline.get(key)
        if value is not None:
            items.append({"value": round(abs(value) * 100), "prefix": "+" if value > 0 else "-",
                          "suffix": "%", "label": label})  # fmt: skip
    return items


def build(summary: dict, a: Run, b: Run, vertical: bool = False, loop: bool = False) -> dict:
    c = comparison(a, b)
    base = _scene_base(a)
    speed = 2.0
    headline = summary.get("headline", {})
    n = a.meta.get("replicas", 4)
    gpu = summary.get("facts", {}).get("gpu", f"{n} GPUs")
    room_b = {"view": "room", **base, "policies": {"room": B}}
    room_a = {"view": "room", **base, "policies": {"room": A}}
    split = {"view": "split", **base, "policies": {"left": A, "right": B}}
    number = {
        "kind": "number", "seconds": 9.0, "items": number_items(headline),
        "line": f"Same {n} GPUs. Same traffic. Prefix-aware routing against round-robin:",
        "foot": f"Measured on {gpu} with Qwen2.5-7B. Medians of repeated runs.",
        "fade_in": 0.4,
    }  # fmt: skip
    if loop:
        scenes = [
            {"kind": "replay", "seconds": 14.0, **split, "t0": c["t0"], "speed": speed, "fade_in": 0.5,
             "captions": [{"at": 0.8, "for": 5.5, "top": True, "text": "Same traffic, two routers."},
                          captions_b(c)[1] | {"at": 7.0, "for": 6.0}]},
            {**number, "seconds": 6.0, "fade_out": 0.5},
        ]  # fmt: skip
    else:
        request = pick_request(b.requests, b.meta["run"].get("warmup_s", 0.0) + 5.0)
        best = (summary.get("sweep", {}).get("l4", {}).get("chat", {}) or {}).get(
            "cheapest_at_default_slo"
        )
        scenes = [
            {"kind": "cold", "seconds": 8.0, "run": b.run_id, "request": request, **room_b, "fade_in": 1.2,
             "captions": [{"at": 1.8, "for": 5.2, "text": "Every LLM request has a cost."}]},
            {"kind": "zoomout", "seconds": 8.0, "cold_seconds": 8.0, "run": b.run_id, "request": request,
             "speed": speed, **room_b,
             "captions": [{"at": 1.6, "for": 5.6, "text": f"{NUMBER_WORDS.get(n, n)} GPUs, one model, real traffic patterns."}]},
            {"kind": "replay", "seconds": 19.0, **room_a, "t0": c["t0"], "speed": speed, "fade_in": 0.5,
             "captions": captions_a(c)},
            {"kind": "rewind", "seconds": 2.6, **room_a, "t_from": c["t0"] + 19.0 * speed, "t_to": c["t0"]},
            {"kind": "replay", "seconds": 20.5, **split, "t0": c["t0"], "speed": speed,
             "captions": captions_b(c)},
            number,
        ]  # fmt: skip
        if best:
            scenes.append(
                {"kind": "whatif", "seconds": 11.0, "from": {"ttft": 3.0, "itl": 0.3},
                 "to": {"ttft": 2.0, "itl": 0.1}, "fade_in": 0.4,
                 "captions": [
                     {"at": 0.8, "for": 4.6, "top": True,
                      "text": "Every setup we measured: cost against latency."},
                     {"at": 6.0, "for": 4.6, "top": True,
                      "text": f"For this latency target, the cheapest one is {best}."},
                 ]}
            )  # fmt: skip
        scenes.append(
            {"kind": "end", "seconds": 6.5, "url": REPO_URL, "fade_out": 1.0,
             "line": "A 4-GPU LLM serving fleet, measured on real traffic and replayed request by request."}
        )  # fmt: skip
    size = (1080, 1920) if vertical else (1920, 1080)
    return {"fps": 60, "width": size[0], "height": size[1], "vertical": vertical, "scenes": scenes,
            "window": c}  # fmt: skip


def source_runs(summary: dict) -> tuple[Run, Run]:
    """The pair of runs the story is told with: first repeat of the fixed chat comparison."""
    return load(f"fleet-fixed-chat-{A}-s0"), load(f"fleet-fixed-chat-{B}-s0")


def write_all(summary: dict) -> dict[str, dict]:
    a, b = source_runs(summary)
    stories = {
        "story-main": build(summary, a, b),
        "story-loop": build(summary, a, b, loop=True),
        "story-vertical": build(summary, a, b, vertical=True),
    }
    for name, story in stories.items():
        path = DATA_DIR / f"{name}.json"
        path.write_text(json.dumps(story, indent=1), encoding="utf-8", newline="\n")
    return stories
