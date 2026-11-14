"""Container facts for meta.json: GPU details, and CPU / memory use of the container."""

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


def _usage() -> tuple[float, float]:
    """(CPU seconds used so far, memory in GiB) for the whole container.

    Reads cgroup v2 counters when present. Modal's sandbox does not expose them, so the
    fallback sums over every process with psutil (installed with vLLM).
    """
    try:
        cpu_line = next(
            x for x in (CGROUP / "cpu.stat").read_text().splitlines() if x.startswith("usage_usec")
        )
        memory = int((CGROUP / "memory.current").read_text())
        return int(cpu_line.split()[1]) / 1e6, memory / 2**30
    except (OSError, StopIteration, ValueError):
        import psutil

        cpu = rss = 0.0
        for proc in psutil.process_iter(["cpu_times", "memory_info"]):
            times, mem = proc.info["cpu_times"], proc.info["memory_info"]
            if times and mem:
                cpu += times.user + times.system
                rss += mem.rss
        return cpu, rss / 2**30


class ResourceSampler:
    """Samples the container's CPU cores in use and memory once per second.

    A process that exits between two samples takes its CPU time with it, so the
    psutil fallback can undercount briefly around a server restart.
    """

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
            (last_cpu, _), last_t = _usage(), time.monotonic()
        except Exception:
            return  # no way to measure here: skip sampling
        while not self._stop.wait(self.interval):
            (cpu, memory), now = _usage(), time.monotonic()
            self.samples.append(
                {
                    "t": round(now, 2),
                    "cpu_cores": round(max(cpu - last_cpu, 0.0) / (now - last_t), 3),
                    "memory_gib": round(memory, 3),
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
