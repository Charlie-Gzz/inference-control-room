"""GPU spend ledger and budget guard.

`results/gpu_ledger.jsonl` is the source of truth. `docs/GPU_LEDGER.md` is rendered from it.
Every GPU run calls `check_budget` before it starts and `record` right after it ends.

Two cost figures per run:
- estimate: seconds inside the container plus a startup allowance, times the posted
  rates for the GPU, the requested CPU and the requested memory.
- actual: what `modal billing report` says the run's app cost. `reconcile` fills it in.
Totals and the budget guard use the actual cost when it is known, else the estimate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime

from icr import config

LEDGER_JSONL = config.RESULTS_DIR / "gpu_ledger.jsonl"
LEDGER_MD = config.DOCS_DIR / "GPU_LEDGER.md"
STARTUP_ALLOWANCE_S = 25.0  # container boot before our code runs (measured: about 22 s)


class BudgetError(RuntimeError):
    """Raised when a run would break a cap in PLAN.md section 1.1."""


def rows() -> list[dict]:
    if not LEDGER_JSONL.exists():
        return []
    return [json.loads(line) for line in LEDGER_JSONL.read_text("utf-8").splitlines() if line]


def cost(row: dict) -> float:
    actual = row.get("actual_cost_usd")
    return row["cost_usd"] if actual is None else actual


def spent(category: str | None = None) -> float:
    return sum(cost(r) for r in rows() if category in (None, r["category"]))


def estimate(gpu: str, gpu_count: int, cpu: float, memory_gib: float, seconds: float) -> float:
    return config.hourly_cost(gpu, gpu_count, cpu, memory_gib) * seconds / 3600


def check_budget(
    category: str, gpu: str, gpu_count: int, cpu: float, memory_gib: float, max_seconds: float
) -> float:
    """Refuse the run if its worst case (full timeout) could break a cap. Returns that cost."""
    worst = estimate(gpu, gpu_count, cpu, memory_gib, max_seconds)
    total = spent()
    if total + worst > config.BUDGET_TOTAL:
        raise BudgetError(
            f"total cap: spent ${total:.2f} + worst case ${worst:.2f} > ${config.BUDGET_TOTAL:.0f}"
        )
    cap = config.BUDGET_BY_CATEGORY[category]
    if spent(category) + worst > cap:
        raise BudgetError(
            f"{category} cap: spent ${spent(category):.2f} + worst case ${worst:.2f} > ${cap:.2f}"
        )
    if category == "dev" and total >= config.BUDGET_SOFT_STOP:
        raise BudgetError(f"soft stop: ${total:.2f} spent, no more development runs")
    return worst


def record(
    *,
    purpose: str,
    category: str,
    gpu: str,
    gpu_count: int,
    cpu: float,
    memory_gib: float,
    container_seconds: float,
    app_id: str = "",
    run_id: str = "",
    note: str = "",
) -> dict:
    """Append one run to the ledger and re-render the markdown table."""
    billed = container_seconds + STARTUP_ALLOWANCE_S
    row = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "purpose": purpose,
        "category": category,
        "gpu": gpu,
        "gpu_count": gpu_count,
        "cpu": cpu,
        "memory_gib": memory_gib,
        "billed_seconds": round(billed, 1),
        "cost_usd": round(estimate(gpu, gpu_count, cpu, memory_gib, billed), 4),
        "actual_cost_usd": None,
        "app_id": app_id,
        "run_id": run_id,
        "note": note,
    }
    _write([*rows(), row])
    return row


def _write(all_rows: list[dict]) -> None:
    LEDGER_JSONL.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r) + "\n" for r in all_rows)
    LEDGER_JSONL.write_text(text, encoding="utf-8", newline="\n")
    render()


def billing_by_app(period: str = "this month") -> dict[str, float]:
    """Cost per Modal app id, from `modal billing report`."""
    cmd = [sys.executable, "-m", "modal", "billing", "report", "--for", period, "--json"]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    costs: dict[str, float] = defaultdict(float)
    for item in json.loads(out[out.index("[") :]):
        costs[item["object_id"]] += float(item["cost"])
    return dict(costs)


def reconcile(period: str = "this month") -> list[dict]:
    """Fill in each row's actual cost from Modal's billing report. Returns the rows."""
    costs = billing_by_app(period)
    all_rows = rows()
    for row in all_rows:
        if row.get("app_id") in costs:
            row["actual_cost_usd"] = round(costs[row["app_id"]], 4)
    _write(all_rows)
    return all_rows


def settle(app_id: str, actual_cost_usd: float, note: str) -> dict:
    """Set a row's actual cost by hand, with the reason. For runs Modal never bills
    (a request that waited in the queue and never got a container has no billing entry)."""
    all_rows = rows()
    row = next(r for r in all_rows if r["app_id"] == app_id)
    row["actual_cost_usd"] = actual_cost_usd
    row["note"] = note
    _write(all_rows)
    return row


def render() -> None:
    """Write docs/GPU_LEDGER.md from the JSONL ledger."""
    lines = [
        "# GPU ledger",
        "",
        "One row per Modal run. **Billed s** is the time inside the container plus a "
        f"{STARTUP_ALLOWANCE_S:.0f} s startup allowance.",
        "**Est. $** = billed seconds x (GPU + requested CPU + requested memory) at the rates",
        "in `src/icr/config.py`. **Actual $** is what `modal billing report` shows for the",
        "run's app (it also covers CPU or memory used above the request, and network egress).",
        "Totals use the actual cost when it is known. Rendered by `icr.ledger`.",
        "",
        "| Date (UTC) | Purpose | Budget | GPU | CPU | Mem GiB | Billed s | Est. $ | Actual $ "
        "| Total $ |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    total = 0.0
    for r in rows():
        total += cost(r)
        gpu = f"{r['gpu']} x{r['gpu_count']}" if r["gpu_count"] else "none"
        actual = "pending" if r.get("actual_cost_usd") is None else f"{r['actual_cost_usd']:.3f}"
        lines.append(
            f"| {r['date']} | {r['purpose']} | {r['category']} | {gpu} | {r['cpu']:g} "
            f"| {r['memory_gib']:g} | {r['billed_seconds']:.0f} | {r['cost_usd']:.3f} "
            f"| {actual} | {total:.3f} |"
        )
    noted = [r for r in rows() if r.get("note")]
    if noted:
        lines += ["", "## Notes", ""]
        lines += [f"- {r['date']}, {r['purpose']}: {r['note']}" for r in noted]
    lines += ["", "## Totals", ""]
    for cat, cap in config.BUDGET_BY_CATEGORY.items():
        lines.append(f"- {cat}: ${spent(cat):.2f} of ${cap:.2f}")
    lines.append(f"- **all: ${total:.2f} of ${config.BUDGET_TOTAL:.2f}**")
    LEDGER_MD.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_MD.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
