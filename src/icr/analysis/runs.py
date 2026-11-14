"""Read and write saved runs in `results/runs/<run_id>/`.

JSONL files are stored gzip-compressed (`requests.jsonl.gz`, `replicas.jsonl.gz`) to keep
the repository small. The gzip header carries no timestamp, so the same data always gives
the same bytes.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

from icr import config


def write_file(directory: Path, name: str, text: str) -> None:
    """Save one run file. `*.jsonl` files are compressed."""
    directory.mkdir(parents=True, exist_ok=True)
    if name.endswith(".jsonl"):
        (directory / (name + ".gz")).write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        (directory / name).write_text(text, encoding="utf-8", newline="\n")


def read_jsonl(directory: Path, name: str) -> list[dict]:
    """Rows of `name` (plain or .gz). An absent file gives an empty list."""
    plain, packed = directory / name, directory / (name + ".gz")
    if packed.exists():
        text = gzip.decompress(packed.read_bytes()).decode("utf-8")
    elif plain.exists():
        text = plain.read_text("utf-8")
    else:
        return []
    return [json.loads(line) for line in text.splitlines() if line]


@dataclass
class Run:
    run_id: str
    directory: Path
    meta: dict

    @property
    def requests(self) -> list[dict]:
        return read_jsonl(self.directory, "requests.jsonl")

    @property
    def replicas(self) -> list[dict]:
        return read_jsonl(self.directory, "replicas.jsonl")


def load(run_id: str, root: Path | None = None) -> Run:
    directory = (root or config.RUNS_DIR) / run_id
    name = "meta.json" if (directory / "meta.json").exists() else "result.json"
    return Run(run_id, directory, json.loads((directory / name).read_text("utf-8")))


def all_runs(prefix: str = "", root: Path | None = None) -> list[Run]:
    """Every saved run whose id starts with `prefix`, sorted by id."""
    root = root or config.RUNS_DIR
    found = []
    for directory in sorted(root.glob(f"{prefix}*")):
        if (directory / "meta.json").exists() or (directory / "result.json").exists():
            found.append(load(directory.name, root))
    return found
