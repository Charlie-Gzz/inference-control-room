"""Start, wait for, and stop `vllm serve` processes. Runs only inside the Modal image.

This file never imports vllm or torch: it launches the server as a subprocess.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from icr import config


@dataclass(frozen=True)
class ServerConfig:
    """One vLLM server configuration. `name` is the config's id in results."""

    name: str = "awq"
    weights: str = "awq"  # key in config.MODELS: "awq" or "bf16"
    quantization: str | None = None  # online scheme, e.g. "fp8_per_tensor"
    speculative: dict | None = None  # passed as --speculative-config
    prefix_caching: bool = True
    max_num_seqs: int | None = None  # None = vLLM default batch limit
    max_model_len: int = 8192
    gpu_memory_utilization: float = 0.90
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)


def build_command(cfg: ServerConfig, port: int) -> list[str]:
    model = config.MODELS[cfg.weights]
    cmd = [
        "vllm",
        "serve",
        model["repo"],
        "--revision",
        model["revision"],
        "--served-model-name",
        config.SERVED_MODEL_NAME,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--max-model-len",
        str(cfg.max_model_len),
        "--gpu-memory-utilization",
        str(cfg.gpu_memory_utilization),
        "--seed",
        "0",
        "--enable-prompt-tokens-details",
        "--uvicorn-log-level",
        "warning",
    ]
    cmd.append("--enable-prefix-caching" if cfg.prefix_caching else "--no-enable-prefix-caching")
    if cfg.quantization:
        cmd += ["--quantization", cfg.quantization]
    if cfg.speculative:
        cmd += ["--speculative-config", json.dumps(cfg.speculative)]
    if cfg.max_num_seqs:
        cmd += ["--max-num-seqs", str(cfg.max_num_seqs)]
    return cmd + list(cfg.extra_args)


class VllmServer:
    """One vLLM process pinned to one GPU, listening on a localhost port."""

    def __init__(self, cfg: ServerConfig, port: int, gpu_index: int = 0, log_dir: str = "/tmp"):
        self.cfg, self.port, self.gpu_index = cfg, port, gpu_index
        self.url = f"http://127.0.0.1:{port}"
        self.log_path = Path(log_dir) / f"vllm-{port}.log"
        self.process: subprocess.Popen | None = None
        self.started_at = 0.0
        self.startup_seconds: float | None = None

    def start(self) -> None:
        env = {
            **os.environ,
            "CUDA_VISIBLE_DEVICES": str(self.gpu_index),
            "VLLM_SERVER_DEV_MODE": "1",  # enables POST /reset_prefix_cache
            "HF_HUB_OFFLINE": "1",  # weights come from the Volume, never the network
        }
        self.started_at = time.monotonic()
        log = self.log_path.open("w")
        self.process = subprocess.Popen(
            build_command(self.cfg, self.port),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def is_ready(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=2) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def wait_ready(self, timeout: float = 600) -> float:
        """Block until /health answers. Returns startup seconds. Raises if the process dies."""
        assert self.process is not None
        while time.monotonic() - self.started_at < timeout:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"vLLM exited with {self.process.returncode}:\n{self.log_tail()}"
                )
            if self.is_ready():
                self.startup_seconds = time.monotonic() - self.started_at
                return self.startup_seconds
            time.sleep(1)
        raise TimeoutError(f"vLLM not ready after {timeout}s:\n{self.log_tail()}")

    def reset_prefix_cache(self) -> bool:
        req = urllib.request.Request(f"{self.url}/reset_prefix_cache", method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode() or "{}"
            return resp.status == 200 and json.loads(body).get("success", True)

    def metrics_text(self) -> str:
        with urllib.request.urlopen(f"{self.url}/metrics", timeout=10) as resp:
            return resp.read().decode()

    def log_tail(self, lines: int = 60) -> str:
        if not self.log_path.exists():
            return ""
        return "\n".join(self.log_path.read_text(errors="replace").splitlines()[-lines:])

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        os.killpg(self.process.pid, signal.SIGTERM)
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=10)
