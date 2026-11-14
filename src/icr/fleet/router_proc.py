"""Build, start and control the Go router process."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from icr import config

ROUTER_DIR = config.ROOT / "router"
BIN_DIR = ROUTER_DIR / "bin"
_PINNED_GO = config.ROOT / ".tools" / "go" / "bin" / ("go.exe" if os.name == "nt" else "go")
GO = _PINNED_GO if _PINNED_GO.exists() else Path(shutil.which("go") or "go")  # CI uses PATH
LINUX_BINARY = BIN_DIR / "switchyard-router"
IMAGE_BINARY = "/usr/local/bin/switchyard-router"


def build(linux: bool = False) -> Path:
    """Compile the router. `linux=True` cross-compiles the static binary for the Modal image."""
    out = (
        LINUX_BINARY
        if linux
        else BIN_DIR / ("switchyard-router.exe" if os.name == "nt" else "switchyard-router-native")
    )  # noqa: E501
    env = {**os.environ, "CGO_ENABLED": "0"}
    if linux:
        env |= {"GOOS": "linux", "GOARCH": "amd64"}
    BIN_DIR.mkdir(exist_ok=True)
    cmd = [str(GO), "build", "-trimpath", "-ldflags=-s -w", "-o", str(out), "."]
    subprocess.run(cmd, cwd=ROUTER_DIR, env=env, check=True)
    return out


def find_binary() -> Path:
    """The router binary for this machine: the image's, or a fresh local build."""
    if Path(IMAGE_BINARY).exists():
        return Path(IMAGE_BINARY)
    found = shutil.which("switchyard-router")
    return Path(found) if found else build()


class RouterProcess:
    """One router on a localhost port, with helpers for its admin endpoints."""

    def __init__(self, backends: dict[int, str], policy: str, port: int = 8080,
                 decision_log: Path | None = None, flags: dict | None = None):  # fmt: skip
        self.backends, self.policy, self.port = backends, policy, port
        self.url = f"http://127.0.0.1:{port}"
        self.decision_log = decision_log
        self.flags = flags or {}  # e.g. {"table-chunks": 2048}
        self.process: subprocess.Popen | None = None

    def start(self, timeout: float = 10.0) -> None:
        urls = [self.backends[i] for i in sorted(self.backends)]
        cmd = [str(find_binary()), "-listen", f"127.0.0.1:{self.port}", "-policy", self.policy,
               "-backends", ",".join(urls)]  # fmt: skip
        if self.decision_log:
            cmd += ["-decision-log", str(self.decision_log)]
        for name, value in self.flags.items():
            cmd += [f"-{name}", str(value)]
        self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self._call("GET", "/health")
                return
            except (urllib.error.URLError, OSError):
                time.sleep(0.05)
        raise RuntimeError("router did not start")

    def _call(self, method: str, path: str, body: dict | None = None) -> bytes:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read()

    def set_policy(self, policy: str) -> None:
        self._call("POST", "/admin/policy", {"policy": policy})
        self.policy = policy

    def set_replicas(self, live: dict[int, str]) -> None:
        replicas = [{"id": i, "url": u} for i, u in sorted(live.items())]
        self._call("POST", "/admin/replicas", {"replicas": replicas})

    def reset(self) -> None:
        self._call("POST", "/admin/reset")

    def state(self) -> dict:
        return json.loads(self._call("GET", "/admin/state"))

    def metrics_text(self) -> str:
        return self._call("GET", "/metrics").decode()

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
