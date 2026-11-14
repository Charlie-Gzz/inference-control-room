"""Container facts for meta.json: GPU details and CPU / memory use from cgroup counters."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

CGROUP = Path("/sys/fs/cgroup")


def nvidia_smi() -> dict:
    """GPU name, memory, driver, plus the plain `nvidia-smi` table."""

    def run(args: list[str]) -> str:
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError) as e:
            return f"error: {e}"

    query = "name,memory.total,driver_version"
    return {
        "gpus": run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader"]).splitlines(),
        "table": run(["nvidia-smi"]),
    }


def _cpu_seconds() -> float:
    for line in (CGROUP / "cpu.stat").read_text().splitlines():
        if line.startswith("usage_usec"):
            return int(line.split()[1]) / 1e6
    return 0.0


def _memory_gib() -> float:
    return int((CGROUP / "memory.current").read_text()) / 2**30


class ResourceSampler:
    """Samples the container's CPU cores in use and memory once per second."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> ResourceSampler:
        self._thread.start()
        return self

    def _loop(self) -> None:
        try:
            last_cpu, last_t = _cpu_seconds(), time.monotonic()
        except OSError:
            return  # no cgroup v2 files: skip sampling
        while not self._stop.wait(self.interval):
            cpu, now = _cpu_seconds(), time.monotonic()
            self.samples.append(
                {
                    "t": round(now, 2),
                    "cpu_cores": round((cpu - last_cpu) / (now - last_t), 3),
                    "memory_gib": round(_memory_gib(), 3),
                }
            )
            last_cpu, last_t = cpu, now

    def mark(self) -> int:
        """Index of the next sample, to summarize a phase later."""
        return len(self.samples)

    def summary(self, start: int = 0, end: int | None = None) -> dict:
        window = self.samples[start:end]
        if not window:
            return {"samples": 0}
        cpus = sorted(s["cpu_cores"] for s in window)
        return {
            "samples": len(window),
            "cpu_cores_mean": round(sum(cpus) / len(cpus), 3),
            "cpu_cores_p95": cpus[int(0.95 * (len(cpus) - 1))],
            "cpu_cores_max": cpus[-1],
            "memory_gib_max": max(s["memory_gib"] for s in window),
        }

    def stop(self) -> None:
        self._stop.set()
