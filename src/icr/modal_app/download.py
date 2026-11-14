"""CPU-only downloads into the Modal Volume: model weights, BurstGPT, and a GSM8K subset."""

from __future__ import annotations

import json
import random
import urllib.request
from pathlib import Path

from icr import config
from icr.workloads import burstgpt


def _dir_size_gib(path: str | Path) -> float:
    return round(sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) / 2**30, 2)


def download_models() -> dict:
    from huggingface_hub import snapshot_download

    sizes = {}
    for key, model in config.MODELS.items():
        path = snapshot_download(model["repo"], revision=model["revision"])
        sizes[key] = {"repo": model["repo"], "gib": _dir_size_gib(path)}
    return sizes


def download_burstgpt() -> dict:
    """Fetch the trace once, then return the two small arrival segments we commit."""
    dst = Path(config.VOL_DATA) / "burstgpt" / "BurstGPT_without_fails_1.csv"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        urllib.request.urlretrieve(config.BURSTGPT_URL, dst)
    with dst.open(encoding="utf-8") as f:
        head = [next(f).strip() for _ in range(4)]
    segments = burstgpt.extract_segments(*burstgpt.read_trace(dst))
    return {"csv_mib": round(dst.stat().st_size / 2**20, 1), "head": head, "segments": segments}


def download_gsm8k() -> dict:
    """Seeded subset of the GSM8K test split, written as JSONL."""
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    parquet = hf_hub_download(
        config.GSM8K_REPO,
        config.GSM8K_FILE,
        repo_type="dataset",
        revision=config.GSM8K_REVISION,
    )
    rows = pq.read_table(parquet).to_pylist()
    subset = random.Random(config.GSM8K_SEED).sample(rows, config.GSM8K_SUBSET_SIZE)
    dst = Path(config.VOL_DATA) / "gsm8k" / f"test_{config.GSM8K_SUBSET_SIZE}.jsonl"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("".join(json.dumps(r) + "\n" for r in subset), encoding="utf-8")
    return {"test_rows": len(rows), "subset_rows": len(subset), "path": str(dst)}
