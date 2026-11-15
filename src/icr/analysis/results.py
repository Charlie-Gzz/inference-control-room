"""`icr results`: recompute every number from `results/runs/` and write the summaries.

Outputs:
- `results/summaries/summary.json`  everything the charts, the site and the README use
- `results/RESULTS.md`              the same numbers as tables

No GPU and no network: only the saved run files and the ledger are read.
"""

from __future__ import annotations

import json

from icr import config, ledger
from icr.analysis import fleet_results, optimizer, sweeps
from icr.analysis.metrics import DEFAULT_SLO
from icr.analysis.runs import all_runs
from icr.fleet.plan import CALIBRATION_FILE

SUMMARY_FILE = config.RESULTS_DIR / "summaries" / "summary.json"
RESULTS_MD = config.RESULTS_DIR / "RESULTS.md"
MODEL_NAMES = {"awq": "Qwen2.5-7B-Instruct-AWQ (4-bit)", "bf16": "Qwen2.5-7B-Instruct (bf16)"}


def _facts(calib: dict) -> dict:
    """What every view's footer states: GPU, model, engine."""
    fleet = all_runs("fleet-fixed-")
    sample = fleet[0] if fleet else next(iter(all_runs("sweep-")), None)
    if sample is None:
        return {}
    gpus = sample.meta.get("gpu", {}).get("gpus", [])
    name = gpus[0].split(",")[0].strip() if gpus else "GPU"
    cfg = sample.meta.get("config", {})
    model = MODEL_NAMES.get(cfg.get("weights"), cfg.get("weights", ""))
    if cfg.get("quantization"):
        model = "Qwen2.5-7B-Instruct (FP8)"
    return {
        "gpu": f"{len(gpus)} x {name}" if len(gpus) > 1 else name,
        "replicas": len(gpus),
        "model": model,
        "engine": f"vLLM {sample.meta.get('vllm_version', '')}".strip(),
        "fleet_config": calib.get("fleet_config"),
    }


def _sweep(label: str) -> dict:
    """Config table and frontier for one GPU type."""
    out: dict = {}
    for workload in ("chat", "rag"):
        rows = sweeps.config_rows(label, workload)
        if not rows:
            continue
        points = [p for row in rows for p in row["points"]]
        best = optimizer.cheapest({row["config"]: row["points"] for row in rows})
        out[workload] = {
            "configs": rows,
            "frontier": [
                {"config": p["config"], "level": p["level"]} for p in optimizer.pareto(points)
            ],
            "cheapest_at_default_slo": best["config"] if best else None,
        }
    return out


def _prefix_pressure(calib: dict) -> dict:
    """Distinct prefix tokens in each fixed fleet workload against one replica's KV cache.

    The longest prompt of a prefix group (conversation, document or task) contains all
    its shorter ones, so the sum of those maxima is the cache needed to hold everything.
    """
    kv = calib.get("kv_cache_tokens")
    out = {}
    for run in all_runs("fleet-fixed-"):
        if run.meta["seed"] != 0 or run.meta["policy"] != "round-robin":
            continue
        longest: dict[str, int] = {}
        for r in run.requests:
            longest[r["group"]] = max(longest.get(r["group"], 0), r.get("prompt_tokens") or 0)
        total = sum(longest.values())
        peak = max((s.get("kv_usage", 0.0) for s in run.replicas), default=0.0)
        out[run.meta["workload"]] = {
            "prefix_groups": len(longest),
            "distinct_prefix_tokens": total,
            "kv_cache_tokens": kv,
            "ratio_to_one_replica": round(total / kv, 2) if kv else None,
            "peak_kv_in_use": round(peak, 3),
        }
    return out


def build() -> dict:
    calib = json.loads(CALIBRATION_FILE.read_text("utf-8")) if CALIBRATION_FILE.exists() else {}
    summary: dict = {
        "slo": {"ttft_s": DEFAULT_SLO.ttft_s, "itl_s": DEFAULT_SLO.itl_s},
        "calibration": calib,
        "facts": _facts(calib),
        "sweep": {label: data for label in ("l4", "h100") if (data := _sweep(label))},
        "fleet": {},
        "spend": {
            "total_usd": round(ledger.spent(), 2),
            "by_category": {c: round(ledger.spent(c), 2) for c in config.BUDGET_BY_CATEGORY},
            "runs": len(ledger.rows()),
        },
    }
    for workload in fleet_results.WORKLOADS:
        table = fleet_results.policy_table(workload)
        if table["policies"]:
            summary["fleet"][workload] = table
    capacity = fleet_results.capacity_table()
    if capacity["policies"]:
        summary["capacity"] = capacity
    if "chat" in summary["fleet"]:
        summary["headline"] = fleet_results.headline(summary["fleet"]["chat"], capacity)
    autoscale = fleet_results.autoscale_table()
    if autoscale:
        summary["autoscale"] = autoscale
    overhead = fleet_results.router_overhead()
    if overhead["decision_us"] or "proxycheck" in overhead:
        summary["router_overhead"] = overhead
    pressure = _prefix_pressure(calib)
    if pressure:
        summary["prefix_pressure"] = pressure
    return summary


# --- markdown ------------------------------------------------------------------------


def _fmt(value, digits: int = 3, unit: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}{unit}"
    return f"{value}{unit}"


def _range(s: dict, digits: int = 3, scale: float = 1.0, unit: str = "") -> str:
    """median (min to max), with a mark when the repeats spread more than 10%."""
    if s["median"] is None:
        return "-"
    text = f"{s['median'] * scale:.{digits}f}{unit} ({s['min'] * scale:.{digits}f} to {s['max'] * scale:.{digits}f})"
    return text + (" ⚠" if s["wide"] else "")


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
        *("| " + " | ".join(r) + " |" for r in rows),
        "",
    ]


def render_markdown(s: dict) -> str:
    lines = [
        "# Results",
        "",
        "Generated by `icr results` from `results/runs/`. Do not edit by hand.",
        "",
        f"SLO: p95 time to first token <= {s['slo']['ttft_s']} s and p95 inter-token latency "
        f"<= {s['slo']['itl_s'] * 1000:.0f} ms, with no failed requests.",
        "",
    ]
    if s.get("headline"):
        lines += ["## Headline", "", s["headline"]["text"], ""]
    for workload, table in s.get("fleet", {}).items():
        lines += [
            f"## Fleet, fixed traffic: `{workload}` at {table['rate_rps']} req/s",
            "",
            "Median over the repeats (min to max). ⚠ marks a spread above 10% of the median.",
            "",
        ]
        rows = [
            [
                f"`{policy}`", str(t["repeats"]),
                _range(t["ttft_p50_s"]), _range(t["ttft_p95_s"]),
                _range(t["itl_p95_s"], 1, 1000, " ms"), _range(t["goodput"], 1, 100, "%"),
                _range(t["cache_hit_rate"], 1, 100, "%"), _range(t["imbalance"], 2),
            ]
            for policy, t in table["policies"].items()
        ]  # fmt: skip
        lines += _table(
            ["Policy", "Repeats", "TTFT p50 (s)", "TTFT p95 (s)", "ITL p95", "Goodput",
             "Cache hit rate", "Imbalance (max / mean)"],
            rows,
        )  # fmt: skip
    if s.get("capacity"):
        cap = s["capacity"]
        lines += [
            "## Fleet capacity at the SLO (`chat` ramp)",
            "",
            f"Levels: {', '.join(str(r) for r in cap['rates_rps'])} req/s, 60 s each. Capacity is "
            "the highest level that meets the SLO with every lower level meeting it too.",
            "",
        ]
        rows = [
            [
                f"`{policy}`",
                ", ".join(_fmt(r["max_rps_at_slo"], 2) for r in t["repeats"]),
                _fmt(t["max_rps_at_slo"]["median"], 2) + (" or more" if t["lower_bound"] else ""),
                _fmt(t["cost_per_m_output"]["median"], 3, ""),
                _fmt(t["cost_per_m_total"]["median"], 4, ""),
            ]
            for policy, t in cap["policies"].items()
        ]
        lines += _table(
            ["Policy", "Max req/s at SLO, per repeat", "Median", "$ per M output tokens at SLO",
             "$ per M total tokens at SLO"],
            rows,
        )  # fmt: skip
    for label, per_workload in s.get("sweep", {}).items():
        for workload, data in per_workload.items():
            lines += [f"## Single-replica configs on {label.upper()}: `{workload}`", ""]
            rows = []
            for c in data["configs"]:
                gsm = c.get("gsm8k")
                greedy = c.get("greedy", {})
                spec = c.get("spec_decode") or {}
                rows.append(
                    [
                        f"`{c['config']}`", c["quantization"], str(c["speculative"]),
                        _fmt(c["prefix_caching"]), str(c["max_num_seqs"]),
                        _fmt(c["max_rps_at_slo"], 2)
                        + (" or more" if c["capacity_is_lower_bound"] else ""),
                        _fmt(c["cost_per_m_output"], 3), _fmt(c["ttft_p95_s"]),
                        _fmt(c["itl_p95_s"] * 1000 if c["itl_p95_s"] else None, 1),
                        _fmt(gsm["accuracy"] * 100, 1, "%") if gsm else "-",
                        _fmt(spec.get("acceptance_rate", None) and spec["acceptance_rate"] * 100, 1, "%"),
                        _fmt(greedy["vs_baseline"]["exact_match"] * 100, 0, "%")
                        if "vs_baseline" in greedy
                        else (_fmt(greedy["self"]["exact_match"] * 100, 0, "% (self)") if greedy else "-"),
                    ]
                )  # fmt: skip
            lines += _table(
                ["Config", "Weights", "Spec. decoding", "Prefix cache", "Max seqs",
                 "Max req/s at SLO", "$ per M output at SLO", "TTFT p95 (s)", "ITL p95 (ms)",
                 "GSM8K", "Draft acceptance", "Greedy match"],
                rows,
            )  # fmt: skip
            lines += [
                f"Cheapest config that meets the SLO: `{data['cheapest_at_default_slo']}`.",
                "",
            ]
    if s.get("autoscale"):
        a = s["autoscale"]
        lines += ["## Autoscaling on the bursty window", ""]
        rows = [
            [
                variant, _range(a[variant]["ttft_p95_s"]), _range(a[variant]["goodput"], 1, 100, "%"),
                _range(a[variant]["gpu_seconds"], 0),
            ]
            for variant in ("static", "autoscaled")
            if variant in a
        ]  # fmt: skip
        lines += _table(["Fleet", "TTFT p95 (s)", "Goodput", "GPU-seconds (modeled)"], rows)
        if a.get("modeled_gpu_seconds_saved") is not None:
            lines += [
                f"Modeled GPU-seconds saved by autoscaling: {a['modeled_gpu_seconds_saved'] * 100:.0f}%. "
                "Modeled: in the real container all four GPUs are billed for the whole run.",
                "",
            ]
    if s.get("router_overhead"):
        o = s["router_overhead"]
        lines += ["## Router overhead", ""]
        rows = [
            [f"`{p}`", str(v["requests"]), str(v["p50"]), str(v["p95"]), str(v["p99"])]
            for p, v in o["decision_us"].items()
        ]
        lines += _table(["Policy", "Requests", "p50 (µs)", "p95 (µs)", "p99 (µs)"], rows)
        if "proxycheck" in o:
            c = o["proxycheck"]
            lines += [
                f"Direct vs through the router, same {c['requests']} requests on one replica: TTFT p50 "
                f"{c['direct']['ttft_p50_s'] * 1000:.1f} ms direct, {c['router']['ttft_p50_s'] * 1000:.1f} ms "
                f"through the router ({c['added_ttft_p50_ms']:+.2f} ms).",
                "",
            ]
    if s.get("prefix_pressure"):
        lines += ["## Cache pressure", ""]
        rows = [
            [
                f"`{w}`", str(p["prefix_groups"]), f"{p['distinct_prefix_tokens']:,}",
                f"{p['kv_cache_tokens']:,}" if p["kv_cache_tokens"] else "-",
                _fmt(p["ratio_to_one_replica"], 2, "x"), _fmt(p["peak_kv_in_use"] * 100, 1, "%"),
            ]
            for w, p in s["prefix_pressure"].items()
        ]  # fmt: skip
        lines += _table(
            ["Workload", "Prefix groups", "Distinct prefix tokens", "One replica's KV cache (tokens)",
             "Ratio", "Peak KV in use (running requests)"],
            rows,
        )  # fmt: skip
    spend = s["spend"]
    lines += [
        "## Spend",
        "",
        f"Total: ${spend['total_usd']:.2f} over {spend['runs']} Modal runs "
        f"({', '.join(f'{c} ${v:.2f}' for c, v in spend['by_category'].items())}). "
        "See `docs/GPU_LEDGER.md`.",
        "",
    ]
    return "\n".join(lines)


def write() -> dict:
    summary = build()
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_FILE.write_text(json.dumps(summary, indent=1), encoding="utf-8", newline="\n")
    RESULTS_MD.write_text(render_markdown(summary), encoding="utf-8", newline="\n")
    return summary
