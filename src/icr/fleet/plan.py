"""The fleet runs of M4, in the plan's priority order. Frozen before any fleet result.

Every traffic level comes from `results/summaries/calibration.json`, which holds the
measured single-replica saturation rate R_sat of the fleet config for each workload
(written by `icr calibrate` from the M3a ramps). Nothing here is tuned on fleet results.
"""

from __future__ import annotations

import json

from icr import config

CALIBRATION_FILE = config.RESULTS_DIR / "summaries" / "calibration.json"

SEEDS = (0, 1, 2)
# Policy order per repeat, so slow drift inside a session never favors one policy.
ORDERS = (
    ("round-robin", "least-loaded", "prefix-aware"),
    ("prefix-aware", "round-robin", "least-loaded"),
    ("least-loaded", "prefix-aware", "round-robin"),
)
FIXED_LOAD = 0.7  # fixed-traffic runs: this share of (replicas x R_sat)
FIXED_WARMUP_S, FIXED_MEASURED_S = 60.0, 180.0
RAMP_LEVELS = (0.6, 0.75, 0.9, 1.05, 1.2, 1.35)
RAMP_WARMUP_S, RAMP_LEVEL_S = 60.0, 60.0
RAMP_SEEDS = (0, 1)
# Autoscaling window: the bursty trace segment from its start. The mean load equals one
# replica's saturation rate, so one replica is enough on average and bursts need the fleet.
AUTOSCALE_WARMUP_S, AUTOSCALE_MEASURED_S = 30.0, 450.0
AUTOSCALE_ROUTER_POLICY = "least-loaded"
AUTOSCALE_ORDERS = (("static", "autoscaled"), ("autoscaled", "static"), ("static", "autoscaled"))
PROXYCHECK_RATE_RPS, PROXYCHECK_S = 1.0, 60.0

ITEMS = ("proxycheck", "chat", "ramp", "rag", "no-sharing", "autoscale", "agentic")

# Single-replica config sweep (M3a): traffic levels as multiples of the baseline's R_sat.
SWEEP_LEVELS = (0.5, 0.7, 0.85, 1.0, 1.15, 1.3)


def calibration() -> dict:
    return json.loads(CALIBRATION_FILE.read_text("utf-8"))


def sweep_rates(workload: str = "chat", gpu: str = "l4") -> list[float]:
    """Frozen ramp levels of the config sweep for one workload on one GPU type."""
    key = "baseline_r_sat" if gpu == "l4" else f"baseline_r_sat_{gpu}"
    r_sat = calibration()[key][workload]
    return [round(level * r_sat, 2) for level in SWEEP_LEVELS]


def fixed_runs(workload: str, r_sat: float, replicas: int = 4) -> list[dict]:
    rate = round(FIXED_LOAD * replicas * r_sat, 2)
    return [
        {
            "kind": "fixed", "workload": workload, "policy": policy, "seed": seed,
            "rate_rps": rate, "warmup_s": FIXED_WARMUP_S, "measured_s": FIXED_MEASURED_S,
        }
        for seed in SEEDS
        for policy in ORDERS[seed]
    ]  # fmt: skip


def ramp_runs(r_sat_chat: float, replicas: int = 4) -> list[dict]:
    rates = [round(level * replicas * r_sat_chat, 2) for level in RAMP_LEVELS]
    return [
        {
            "kind": "ramp", "workload": "chat", "policy": policy, "seed": seed,
            "rates_rps": rates, "warmup_s": RAMP_WARMUP_S, "level_s": RAMP_LEVEL_S,
        }
        for seed in RAMP_SEEDS
        for policy in ORDERS[seed]
    ]  # fmt: skip


def autoscale_runs(r_sat_chat: float) -> list[dict]:
    return [
        {
            "kind": "autoscale", "workload": "chat", "policy": variant, "seed": seed,
            "router_policy": AUTOSCALE_ROUTER_POLICY, "segment": "bursty",
            "rate_rps": round(r_sat_chat, 2), "warmup_s": AUTOSCALE_WARMUP_S,
            "measured_s": AUTOSCALE_MEASURED_S,
        }
        for seed in SEEDS
        for variant in AUTOSCALE_ORDERS[seed]
    ]  # fmt: skip


def proxycheck_runs() -> list[dict]:
    return [
        {
            "kind": "proxycheck", "workload": "chat", "policy": "router", "seed": 0,
            "rate_rps": PROXYCHECK_RATE_RPS, "warmup_s": 0.0, "measured_s": PROXYCHECK_S,
        }
    ]  # fmt: skip


def runs_for(item: str, calib: dict | None = None, replicas: int = 4) -> list[dict]:
    """The runs of one plan item, in the order they are executed."""
    calib = calib or calibration()
    r_sat = calib["r_sat"]
    if item == "proxycheck":
        return proxycheck_runs()
    if item == "ramp":
        return ramp_runs(r_sat["chat"], replicas)
    if item == "autoscale":
        return autoscale_runs(r_sat["chat"])
    if item in ("chat", "rag", "no-sharing", "agentic"):
        return fixed_runs(item, r_sat[item], replicas)
    raise ValueError(f"unknown fleet item {item!r}; choose from {ITEMS}")
