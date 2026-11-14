"""Single-replica sweep results (M3): capacity, cost and quality of every server config."""

from __future__ import annotations

import re

from icr.analysis import optimizer
from icr.analysis.metrics import DEFAULT_SLO, SLO
from icr.analysis.runs import Run, all_runs
from icr.quality.checks import match_rate

SPEC_METRIC = re.compile(r"^vllm:spec_decode_num_(\w+?)(?:_total)?\{[^}]*\} ([0-9.e+]+)$", re.M)


def describe(cfg: dict) -> dict:
    """The knobs of a server config, in words for tables and the site."""
    spec = cfg.get("speculative") or {}
    weights = (
        "FP8" if cfg.get("quantization") else {"awq": "AWQ 4-bit", "bf16": "bf16"}[cfg["weights"]]
    )
    return {
        "quantization": weights,
        "speculative": {"draft_model": "draft model", None: "off"}.get(
            spec.get("method"), spec.get("method")
        ),
        "prefix_caching": bool(cfg.get("prefix_caching", True)),
        "max_num_seqs": cfg.get("max_num_seqs") or 128,
    }


def ramp_points(run: Run) -> list[dict]:
    """Operating points of one ramp run (one per traffic level)."""
    meta, ramp = run.meta, run.meta["ramp"]
    return optimizer.operating_points(
        meta["config"]["name"], run.requests, ramp["rates_rps"], ramp["level_s"],
        meta["cost_per_hour_usd"],
    )  # fmt: skip


def spec_decode(metrics_text: str) -> dict | None:
    """Speculative decoding counters from a /metrics page: drafts, proposed, accepted."""
    found = {name: float(value) for name, value in SPEC_METRIC.findall(metrics_text)}
    drafted, accepted = found.get("draft_tokens"), found.get("accepted_tokens")
    if not drafted or accepted is None:
        return None
    out = {
        "draft_tokens": round(drafted),
        "accepted_tokens": round(accepted),
        "acceptance_rate": round(accepted / drafted, 4),
    }
    if found.get("drafts"):
        out["accepted_per_draft"] = round(accepted / found["drafts"], 3)
    return out


def _suffix_runs(label: str, suffix: str) -> dict[str, Run]:
    return {
        run.meta["config"]["name"]: run
        for run in all_runs(f"sweep-{label}-")
        if run.run_id.endswith(suffix)
    }


def config_rows(label: str = "l4", workload: str = "chat", slo: SLO = DEFAULT_SLO) -> list[dict]:
    """One row per server config: capacity at the SLO, cost, latency there, and quality."""
    ramps = _suffix_runs(label, f"-ramp-{workload}")
    gsm8k = _suffix_runs(label, "-gsm8k")
    greedy = _suffix_runs(label, "-greedy")
    rows = []
    for name, run in ramps.items():
        points = ramp_points(run)
        cap = optimizer.capacity_point(points, slo)
        row = {
            "config": name,
            **describe(run.meta["config"]),
            "gpu": label,
            "workload": workload,
            "startup_s": run.meta.get("startup_s"),
            "cost_per_hour_usd": run.meta["cost_per_hour_usd"],
            "max_rps_at_slo": cap["rate_rps"] if cap else 0.0,
            "capacity_is_lower_bound": optimizer.at_top_level(points, cap),
            "points": points,
        }
        for key in ("cost_per_m_output", "cost_per_m_total", "output_tokens_per_hour",
                    "ttft_p50_s", "ttft_p95_s", "itl_p95_s", "cache_hit_rate"):  # fmt: skip
            row[key] = cap[key] if cap else None
        metrics_file = run.directory / "metrics.txt"
        if metrics_file.exists():
            row["spec_decode"] = spec_decode(metrics_file.read_text("utf-8"))
        if name in gsm8k:
            row["gsm8k"] = gsm8k[name].meta["gsm8k"]
        if name in greedy:
            row["greedy"] = _greedy_match(name, run.meta["config"], greedy)
        rows.append(row)
    return sorted(rows, key=lambda r: (r["cost_per_m_output"] is None, r["cost_per_m_output"]))


def _greedy_match(name: str, cfg: dict, greedy: dict[str, Run]) -> dict:
    """Match rates of greedy outputs: this config against itself, and against its baseline.

    The baseline is the config with the same weights and no speculative decoding. Two runs
    of the same server can differ (batching changes floating point), so the self-match
    rate is the ceiling any comparison can reach.
    """
    own = greedy[name].meta["greedy"]
    out = {"self": match_rate(own["first"], own["second"])}
    baseline = next(
        (
            run for other, run in greedy.items()
            if other != name
            and not run.meta["config"].get("speculative")
            and run.meta["config"]["weights"] == cfg["weights"]
            and run.meta["config"].get("quantization") == cfg.get("quantization")
            and run.meta["config"].get("prefix_caching", True)
            and not run.meta["config"].get("max_num_seqs")
        ),
        None,
    )  # fmt: skip
    if baseline and cfg.get("speculative"):
        out["vs_baseline"] = match_rate(baseline.meta["greedy"]["first"], own["first"])
        out["baseline"] = baseline.meta["config"]["name"]
    return out
