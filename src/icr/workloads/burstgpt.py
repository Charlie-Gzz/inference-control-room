"""BurstGPT arrival trace: pick real segments, then rescale them to a target request rate.

BurstGPT (Wang et al., KDD 2025, CC BY 4.0) logs when real ChatGPT / GPT-4 requests arrived.
We keep only arrival times. The full trace stays in the Modal Volume; two small segments
are committed in `data/burstgpt_segments.json` so tests and runs need no download.

Segment choice is mechanical, fixed before any benchmark ran:
- cut the trace into consecutive segments of SEGMENT_SIZE arrivals,
- keep the busier half (shorter real duration), where traffic is user driven,
- `steady` is the kept segment with the median burstiness,
- `bursty` is the kept segment at the 95th percentile of burstiness.
Burstiness is the coefficient of variation of arrival counts over 60 equal time bins.
"""

from __future__ import annotations

import csv
import json
import random
import statistics
from pathlib import Path

SEGMENT_SIZE = 8000
BINS = 60
SEGMENTS_FILE = Path(__file__).parent / "data" / "burstgpt_segments.json"


def burstiness(times: list[float], bins: int = BINS) -> float:
    """Coefficient of variation of arrival counts over equal time bins. Higher is burstier."""
    start, span = times[0], max(times[-1] - times[0], 1e-9)
    counts = [0] * bins
    for t in times:
        counts[min(int((t - start) / span * bins), bins - 1)] += 1
    mean = sum(counts) / bins
    return statistics.pstdev(counts) / mean if mean else 0.0


def read_trace(csv_path: str | Path) -> tuple[list[float], list[int]]:
    """Arrival times (sorted) and response token counts of the whole trace."""
    with Path(csv_path).open(newline="", encoding="utf-8") as f:
        rows = [
            (float(r["Timestamp"]), int(float(r["Response tokens"]))) for r in csv.DictReader(f)
        ]
    return sorted(t for t, _ in rows), [n for _, n in rows]


def quantiles(values: list[int], points: int = 100) -> list[int]:
    """Values at 0%, 1%, ..., 100%. A compact stand-in for the full distribution."""
    ordered = sorted(values)
    return [ordered[round(i / points * (len(ordered) - 1))] for i in range(points + 1)]


def extract_segments(timestamps: list[float], response_tokens: list[int] | None = None) -> dict:
    """Choose the `steady` and `bursty` segments. Times are stored relative to segment start."""
    segments = [
        timestamps[i : i + SEGMENT_SIZE]
        for i in range(0, len(timestamps) - SEGMENT_SIZE + 1, SEGMENT_SIZE)
    ]
    by_duration = sorted(segments, key=lambda s: s[-1] - s[0])
    kept = sorted(by_duration[: max(len(segments) // 2, 1)], key=burstiness)
    chosen = {"steady": kept[len(kept) // 2], "bursty": kept[int(0.95 * (len(kept) - 1))]}
    out = {
        "source": "BurstGPT v2.0, BurstGPT_without_fails_1.csv (CC BY 4.0)",
        "url": "https://github.com/HPMLL/BurstGPT",
        "trace_arrivals": len(timestamps),
        "segments_considered": len(segments),
        "response_token_quantiles": quantiles(response_tokens) if response_tokens else [],
        "segments": {},
    }
    for name, seg in chosen.items():
        out["segments"][name] = {
            "trace_start_s": seg[0],
            "real_duration_s": round(seg[-1] - seg[0], 3),
            "burstiness_cv": round(burstiness(seg), 4),
            "arrivals": [round(t - seg[0], 3) for t in seg],
        }
    return out


def load_segment(name: str) -> list[float]:
    return json.loads(SEGMENTS_FILE.read_text("utf-8"))["segments"][name]["arrivals"]


def response_token_quantiles() -> list[int]:
    """Real response lengths from the trace, as 101 quantiles, for sampling output lengths."""
    return json.loads(SEGMENTS_FILE.read_text("utf-8"))["response_token_quantiles"]


def scaled_arrivals(
    name: str, count: int, rate_rps: float, seed: int = 0, offset: int = 0
) -> list[float]:
    """`count` arrival times in seconds, from a real segment, rescaled to a mean of `rate_rps`.

    The trace has one-second resolution, so each arrival gets a seeded jitter inside its
    second before rescaling. Linear rescaling keeps the shape of the bursts.
    """
    segment = load_segment(name)
    n = len(segment)
    # A run that needs more arrivals than the segment has continues from its start again
    # (the long fleet capacity ramp needs slightly more than 8,000).
    period = segment[-1] + (segment[-1] - segment[0]) / (n - 1)
    picked = [segment[i % n] + (i // n) * period for i in range(offset, offset + count)]
    rng = random.Random(seed)
    raw = sorted(t + rng.random() for t in picked)
    span = raw[-1] - raw[0]
    # The last arrival lands one mean gap before the end of the window, so consecutive
    # windows (ramp levels) join without two arrivals at the same instant.
    scale = ((count - 1) / rate_rps) / span if span > 0 else 0.0
    return [(t - raw[0]) * scale for t in raw]
