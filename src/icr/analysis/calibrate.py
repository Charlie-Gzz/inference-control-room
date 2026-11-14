"""Calibration: measured single-replica saturation rates, written to calibration.json.

R_sat(config, workload) is the highest traffic level of a single-replica ramp that meets
the SLO with every lower level meeting it too. The fine calibration ramp (`-fine`) is
used when it exists, else the coarse one (`-cal`).

`calibration.json` is read by the sweep (its ramp levels are multiples of the baseline's
R_sat) and by the fleet plan (its traffic levels are multiples of the fleet config's R_sat).
It is written before any fleet run and not changed afterwards.
"""

from __future__ import annotations

import json
import re

from icr.analysis import metrics, runs
from icr.autoscale.autoscaler import AutoscalerConfig
from icr.fleet.plan import CALIBRATION_FILE

BASELINE = "awq"
WORKLOADS = ("chat", "rag", "no-sharing", "agentic")


def ramp_capacity(run: runs.Run) -> dict:
    ramp = run.meta["ramp"]
    levels = metrics.by_level(run.requests)
    cap = metrics.capacity(levels, ramp["rates_rps"], ramp["level_s"])
    first_miss = next(
        (ramp["rates_rps"][lv["level"]] for lv in levels if not lv["meets_slo"]), None
    )
    return {"r_sat": cap["max_rps_at_slo"], "first_miss": first_miss, "rates": ramp["rates_rps"]}


def r_sat(config_name: str, workload: str, label: str = "l4") -> dict | None:
    """Best available calibration of one config on one workload: fine, else coarse.

    A fine ramp starts at a high rate on an empty prefix cache. If its very first level
    misses the SLO for that reason, the ramp says nothing about saturation (the capacity
    rule gives 0), and the coarse ramp's value is kept. Seen on rag, where one replica
    cannot warm 160 documents in the 30 s warmup at 2 req/s.
    """
    found = {}
    for tag in ("fine", "cal"):
        rid = f"sweep-{label}-{config_name}-ramp-{workload}-{tag}"
        if (runs.config.RUNS_DIR / rid).exists():
            found[tag] = {**ramp_capacity(runs.load(rid)), "source": rid, "stage": tag}
    fine, coarse = found.get("fine"), found.get("cal")
    if fine and coarse and fine["r_sat"] == 0 and coarse["r_sat"] > 0:
        note = "the fine ramp's first level missed the SLO on a cold cache; coarse value kept"
        return {**coarse, "note": note, "fine_source": fine["source"]}
    return fine or coarse


def fine_levels(coarse: dict, steps: int = 6) -> list[float]:
    """Six equal steps from the last coarse level that met the SLO to the first that missed."""
    lo, hi = coarse["r_sat"], coarse["first_miss"]
    if hi is None:
        raise ValueError("the coarse ramp never missed the SLO: extend it upwards first")
    if lo == 0:
        lo = hi / 2  # even the lowest coarse level missed: search below it
    return [round(lo + (hi - lo) * k / (steps - 1), 2) for k in range(steps)]


def kv_cache_tokens(config_name: str) -> int | None:
    """Size of one replica's KV cache in tokens, from vLLM's own /metrics page."""
    for run in runs.all_runs(f"sweep-l4-{config_name}-ramp-"):
        page = run.directory / "metrics.txt"
        found = (
            re.search(r'kv_cache_size_tokens="(\d+)"', page.read_text("utf-8"))
            if page.exists()
            else None
        )
        if found:
            return int(found.group(1))
    return None


def build(fleet_config: str | None = None) -> dict:
    """Everything calibration.json holds. `fleet_config=None` keeps the earlier choice."""
    previous = json.loads(CALIBRATION_FILE.read_text("utf-8")) if CALIBRATION_FILE.exists() else {}
    fleet_config = fleet_config or previous.get("fleet_config") or BASELINE
    out = {
        "baseline": BASELINE,
        "baseline_r_sat": {},
        "fleet_config": fleet_config,
        "r_sat": {},
        "sources": {"baseline": {}, "fleet": {}},
        "kv_cache_tokens": kv_cache_tokens(fleet_config),
        "autoscaler": AutoscalerConfig().to_dict(),
    }
    for workload in WORKLOADS:
        for key, name, where in (
            ("baseline_r_sat", BASELINE, "baseline"),
            ("r_sat", fleet_config, "fleet"),
        ):
            found = r_sat(name, workload)
            if found:
                out[key][workload] = found["r_sat"]
                out["sources"][where][workload] = found
    # M3b: the baseline's saturation rate on one H100, when that calibration ramp exists.
    h100 = {w: found for w in WORKLOADS if (found := r_sat(BASELINE, w, "h100"))}
    if h100:
        out["baseline_r_sat_h100"] = {w: found["r_sat"] for w, found in h100.items()}
        out["sources"]["baseline_h100"] = h100
    return out


def write(fleet_config: str | None = None) -> dict:
    data = build(fleet_config)
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8", newline="\n")
    return data
