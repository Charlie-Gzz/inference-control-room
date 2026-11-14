"""Turn a saved run into the compact replay file the control room plays back.

Requests become column arrays (one entry per request, in arrival order). Replica metrics
are resampled to a fixed step. Times are seconds from run start. Nothing is invented:
every value comes from the run's requests.jsonl and replicas.jsonl.
"""

from __future__ import annotations

from icr.analysis.metrics import DEFAULT_SLO
from icr.analysis.runs import Run

REPLICA_STEP_S = 0.5


def _index(values: list) -> tuple[list, list[int]]:
    """Distinct values in first-seen order, and each value's index."""
    names: dict = {}
    ids = [names.setdefault(v, len(names)) for v in values]
    return list(names), ids


def _r(value, digits: int = 3):
    return None if value is None else round(value, digits)


def request_columns(rows: list[dict]) -> dict:
    rows = sorted(rows, key=lambda r: r["scheduled_s"])
    groups, group_ids = _index([r["group"] for r in rows])
    tenants, tenant_ids = _index([r["tenant"] for r in rows])
    kinds, kind_ids = _index([r["kind"] for r in rows])
    reasons, reason_ids = _index([r.get("reason") or "direct" for r in rows])
    return {
        "groups": groups,
        "tenants": tenants,
        "kinds": kinds,
        "reasons": reasons,
        "req": {
            "id": [r["id"] for r in rows],
            "t": [_r(r["scheduled_s"]) for r in rows],
            "first": [_r(r.get("first_token_s")) for r in rows],
            "end": [_r(r.get("end_s")) for r in rows],
            "ttft": [_r(r.get("ttft_s")) for r in rows],
            "itl": [_r(r.get("itl_s"), 4) for r in rows],
            "rep": [r.get("replica") for r in rows],
            "grp": group_ids,
            "ten": tenant_ids,
            "kind": kind_ids,
            "turn": [r["turn"] for r in rows],
            "ptok": [r.get("prompt_tokens") or 0 for r in rows],
            "ctok": [r.get("cached_tokens") or 0 for r in rows],
            "otok": [r.get("completion_tokens") or 0 for r in rows],
            "why": reason_ids,
            "match": [r.get("matched_chunks") or 0 for r in rows],
            "loads": [r.get("loads") or [] for r in rows],
            "ovh": [r.get("router_overhead_us") for r in rows],
            "err": [1 if r.get("error") else 0 for r in rows],
            "warm": [1 if r.get("phase") == "warmup" else 0 for r in rows],
            "level": [r.get("level", 0) for r in rows],
        },
    }


def replica_series(samples: list[dict], replicas: int, duration_s: float) -> dict:
    """Per replica: running, waiting, KV cache use and tokens/s on a fixed time grid.

    A grid cell holds the last sample inside it (or the previous cell's value). Cells
    before a replica's first sample or after its last one are null: the replica was down.
    """
    steps = int(duration_s / REPLICA_STEP_S) + 1
    out = {
        "dt": REPLICA_STEP_S,
        "running": [[None] * steps for _ in range(replicas)],
        "waiting": [[None] * steps for _ in range(replicas)],
        "kv": [[None] * steps for _ in range(replicas)],
        "tps": [[None] * steps for _ in range(replicas)],
    }
    for replica in range(replicas):
        mine = sorted((s for s in samples if s["replica"] == replica), key=lambda s: s["t"])
        previous = None
        for s in mine:
            cell = int(s["t"] / REPLICA_STEP_S)
            if not 0 <= cell < steps:
                continue
            out["running"][replica][cell] = int(s.get("running", 0))
            out["waiting"][replica][cell] = int(s.get("waiting", 0))
            out["kv"][replica][cell] = round(s.get("kv_usage", 0.0), 3)
            if previous and s["t"] > previous["t"]:
                tokens = s.get("generation_tokens", 0) - previous.get("generation_tokens", 0)
                out["tps"][replica][cell] = round(max(tokens, 0) / (s["t"] - previous["t"]))
            previous = s
        _fill_gaps(out, replica, mine)
    return out


def _fill_gaps(out: dict, replica: int, samples: list[dict]) -> None:
    """Carry values forward across empty cells, but only while the replica was being sampled."""
    if not samples:
        return
    times = [s["t"] for s in samples]
    for key in ("running", "waiting", "kv", "tps"):
        series = out[key][replica]
        last, k = None, 0
        for cell in range(len(series)):
            start = cell * REPLICA_STEP_S
            if series[cell] is not None:
                last = series[cell]
                continue
            while k < len(times) and times[k] < start:
                k += 1
            # A sample within 2 s before or after means the replica was up at this moment.
            near = (k < len(times) and times[k] - start < 2.0) or (
                k > 0 and start - times[k - 1] < 2.0
            )
            if last is not None and near:
                series[cell] = last


def build(run: Run) -> dict:
    """The replay file for one run."""
    meta, rows = run.meta, run.requests
    cfg = meta.get("config") or {}
    replicas = meta.get("replicas") or max((r.get("replica") or 0 for r in rows), default=0) + 1
    duration = max((r.get("end_s") or r["scheduled_s"] for r in rows), default=0.0)
    spec = meta.get("run") or {}
    info = {
        "id": run.run_id,
        "mock": bool(meta.get("mock")),
        "workload": meta.get("workload"),
        "policy": meta.get("policy"),
        "seed": meta.get("seed"),
        "kind": spec.get("kind", meta.get("kind", "fixed")),
        "rate_rps": spec.get("rate_rps", meta.get("rate_rps")),
        "rates_rps": spec.get("rates_rps"),
        "level_s": spec.get("level_s"),
        "warmup_s": spec.get("warmup_s", meta.get("warmup_s", 0.0)),
        "replicas": replicas,
        "duration_s": round(duration, 2),
        "config": cfg.get("name"),
        "gpu": (meta.get("gpu") or {}).get("gpus", []),
        "cost_per_hour_usd": meta.get("cost_per_hour_usd"),
        "slo": {"ttft_s": DEFAULT_SLO.ttft_s, "itl_s": DEFAULT_SLO.itl_s},
        "summary": meta.get("summary", {}),
        "autoscaler_events": meta.get("autoscaler_events"),
    }
    return {
        "meta": info,
        **request_columns(rows),
        "rep": replica_series(run.replicas, replicas, duration),
    }
