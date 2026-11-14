"""GPU spend ledger and budget guard.

`results/gpu_ledger.jsonl` is the source of truth. `docs/GPU_LEDGER.md` is rendered from it.
Every GPU run calls `check_budget` before it starts and `record` right after it ends.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from icr import config

LEDGER_JSONL = config.RESULTS_DIR / "gpu_ledger.jsonl"
LEDGER_MD = config.DOCS_DIR / "GPU_LEDGER.md"


class BudgetError(RuntimeError):
    """Raised when a run would break a cap in PLAN.md section 1.1."""


def rows() -> list[dict]:
    if not LEDGER_JSONL.exists():
        return []
    return [json.loads(line) for line in LEDGER_JSONL.read_text("utf-8").splitlines() if line]


def spent(category: str | None = None) -> float:
    return sum(r["cost_usd"] for r in rows() if category in (None, r["category"]))


def estimate(gpu: str, gpu_count: int, cpu: float, memory_gib: float, seconds: float) -> float:
    return config.hourly_cost(gpu, gpu_count, cpu, memory_gib) * seconds / 3600


def check_budget(
    category: str, gpu: str, gpu_count: int, cpu: float, memory_gib: float, max_seconds: float
) -> float:
    """Refuse the run if its worst case (full timeout) could break a cap. Returns that cost."""
    worst = estimate(gpu, gpu_count, cpu, memory_gib, max_seconds)
    total = spent()
    if total + worst > config.BUDGET_TOTAL:
        raise BudgetError(f"total cap: spent ${total:.2f} + worst case ${worst:.2f} > $35")
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
    billed_seconds: float,
    run_id: str = "",
    note: str = "",
) -> dict:
    """Append one run to the ledger and re-render the markdown table."""
    cost = estimate(gpu, gpu_count, cpu, memory_gib, billed_seconds)
    row = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "purpose": purpose,
        "category": category,
        "gpu": gpu,
        "gpu_count": gpu_count,
        "cpu": cpu,
        "memory_gib": memory_gib,
        "billed_seconds": round(billed_seconds, 1),
        "cost_usd": round(cost, 4),
        "run_id": run_id,
        "note": note,
    }
    LEDGER_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_JSONL.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row) + "\n")
    render()
    return row


def render() -> None:
    """Write docs/GPU_LEDGER.md from the JSONL ledger."""
    lines = [
        "# GPU ledger",
        "",
        "One row per GPU run. Billed seconds are wall-clock seconds of the remote call",
        "(queue + container startup + execution), so they are an upper bound on what Modal bills.",
        "Cost = seconds x (GPU + requested CPU + requested memory) at the rates in",
        "`src/icr/config.py`. Rendered from `results/gpu_ledger.jsonl` by `icr.ledger`.",
        "",
        "| Date (UTC) | Purpose | Budget | GPU | CPU | Mem GiB | Billed s | Cost $ | Total $ |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    total = 0.0
    for r in rows():
        total += r["cost_usd"]
        gpu = f"{r['gpu']} x{r['gpu_count']}"
        lines.append(
            f"| {r['date']} | {r['purpose']} | {r['category']} | {gpu} | {r['cpu']:g} "
            f"| {r['memory_gib']:g} | {r['billed_seconds']:.0f} | {r['cost_usd']:.3f} "
            f"| {total:.3f} |"
        )
    lines += ["", "## Totals", ""]
    for cat, cap in config.BUDGET_BY_CATEGORY.items():
        lines.append(f"- {cat}: ${spent(cat):.2f} of ${cap:.2f}")
    lines.append(f"- **all: ${total:.2f} of ${config.BUDGET_TOTAL:.2f}**")
    recon = config.DOCS_DIR / "GPU_LEDGER_RECONCILIATION.md"
    if recon.exists():
        lines += [
            "",
            "Reconciliation with Modal's billing report: see `GPU_LEDGER_RECONCILIATION.md`.",
        ]
    LEDGER_MD.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_MD.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
