"""Video storyboards: the window is chosen by rule and captions state what was measured."""

from icr.assets import story


def row(t, ttft=0.3, cached=800, tenant="tenant-1", error=""):
    return {
        "scheduled_s": t, "ttft_s": ttft, "itl_s": 0.03, "prompt_tokens": 1000,
        "cached_tokens": cached, "completion_tokens": 80, "tenant": tenant, "error": error,
        "phase": "measured",
    }  # fmt: skip


def test_window_stats_count_only_requests_in_the_window():
    rows = [row(1.0), row(5.0, ttft=3.0, cached=0), row(50.0)]
    stats = story.window_stats(rows, 0.0, 10.0)
    assert stats["requests"] == 2 and stats["goodput"] == 0.5
    assert stats["cache_hit_rate"] == 0.4
    assert story.window_stats(rows, 100.0, 110.0)["goodput"] is None


def test_the_window_is_where_round_robin_falls_furthest_behind():
    # Round-robin is slow only between 100 s and 140 s; prefix-aware is fine throughout.
    a = [row(t, ttft=3.0 if 100 <= t < 140 else 0.3) for t in range(60, 240)]
    b = [row(t) for t in range(60, 240)]
    assert story.choose_window(a, b, 60.0, 239.0) == 100.0


def test_captions_follow_the_numbers_win_or_lose():
    win = {
        "t0": 100.0,
        story.A: {"goodput": 0.60, "ttft_p95_s": 2.8, "cache_hit_rate": 0.45},
        story.B: {"goodput": 0.99, "ttft_p95_s": 0.5, "cache_hit_rate": 0.81},
    }
    assert "40% of requests miss the latency target" in story.captions_a(win)[-1]["text"]
    texts = [c["text"] for c in story.captions_b(win)]
    assert "81% of prompt tokens reused, against 45%" in texts[1]
    assert "99% of requests meet the latency target, against 60%" in texts[2]

    same = {
        "t0": 100.0,
        story.A: {"goodput": 1.0, "ttft_p95_s": 0.50, "cache_hit_rate": 0.45},
        story.B: {"goodput": 1.0, "ttft_p95_s": 0.49, "cache_hit_rate": 0.81},
    }
    assert "Only 45% of the prompt comes from cache" in story.captions_a(same)[-1]["text"]
    assert "Latency is about the same" in story.captions_b(same)[-1]["text"]

    worse = {**same, story.B: {"goodput": 1.0, "ttft_p95_s": 0.9, "cache_hit_rate": 0.81}}
    assert (
        "slower to the first token: 0.90 s, against 0.50 s" in story.captions_b(worse)[-1]["text"]
    )


def test_number_items_keep_the_measured_signs():
    items = story.number_items(
        {"ttft_p95_change": -0.41, "capacity_change": 0.25, "cost_change": None}
    )
    assert [(i["prefix"], i["value"]) for i in items] == [("-", 41), ("+", 25)]
    assert story.number_items({"ttft_p95_change": 0.1})[0]["prefix"] == "+"


def test_opening_request_is_a_real_cache_hit():
    rows = [row(1.0, tenant="none"), row(2.0, cached=100), row(70.0), row(80.0)]
    assert story.pick_request(rows, after=65.0) == 2
