"""Build `site/data/`: one replay file per fleet run, plus the index the site starts from.

`icr replay-data` regenerates everything from `results/` alone. With `--mock` it reads the
local mock runs instead and writes to `.scratch/site-data/` for site development; those
files are flagged `mock` and the site shows a banner. Mock data is never committed.
"""

from __future__ import annotations

import json
from pathlib import Path

from icr import config
from icr.analysis import replay
from icr.analysis.runs import Run, all_runs

SITE_DIR = config.ROOT / "site"
DATA_DIR = SITE_DIR / "data"
MOCK_RUNS_DIR = config.ROOT / ".scratch" / "mock-runs"
MOCK_DATA_DIR = config.ROOT / ".scratch" / "site-data"
SUMMARY_FILE = config.RESULTS_DIR / "summaries" / "summary.json"


def write_json(path: Path, data) -> int:
    """Compact JSON. Returns the size in bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"))
    path.write_text(text, encoding="utf-8", newline="\n")
    return len(text)


def _entry(data: dict, file: str) -> dict:
    meta = data["meta"]
    keys = ("id", "workload", "policy", "seed", "kind", "rate_rps", "duration_s", "replicas")
    return {**{k: meta[k] for k in keys}, "file": file, "summary": meta["summary"]}


def _pick_split(entries: list[dict]) -> dict | None:
    """Default split view: round-robin vs prefix-aware on chat, first repeat that has both."""
    fixed = [e for e in entries if e["kind"] == "fixed"]
    for workload in ("chat", *sorted({e["workload"] for e in fixed})):
        for seed in sorted({e["seed"] for e in fixed}):
            pair = {
                e["policy"]: e["id"]
                for e in fixed
                if e["workload"] == workload and e["seed"] == seed
            }
            if {"round-robin", "prefix-aware"} <= set(pair):
                return {"left": pair["round-robin"], "right": pair["prefix-aware"]}
    return None


def build_all(mock: bool = False) -> dict:
    """Write every replay file and index.json. Returns the index."""
    out = MOCK_DATA_DIR if mock else DATA_DIR
    found: list[Run] = all_runs("mock-", MOCK_RUNS_DIR) if mock else all_runs("fleet-")
    if mock:  # keep only the newest mock run of each (workload, policy)
        newest = {(r.meta["workload"], r.meta["policy"]): r for r in found}
        found = list(newest.values())
    entries, sizes = [], {}
    for run in found:
        data = replay.build(run)
        if mock:
            data["meta"]["mock"] = True
        file = f"runs/{run.run_id}.json"
        sizes[file] = write_json(out / file, data)
        entries.append(_entry(data, file))
    index = {
        "mock": mock,
        "runs": entries,
        "default_split": _pick_split(entries),
        "summary": json.loads(SUMMARY_FILE.read_text("utf-8"))
        if SUMMARY_FILE.exists() and not mock
        else None,
    }
    sizes["index.json"] = write_json(out / "index.json", index)
    return {"out": str(out), "files": len(sizes), "largest_bytes": max(sizes.values(), default=0)}
