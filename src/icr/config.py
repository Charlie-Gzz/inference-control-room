"""Pinned versions, prices and budget caps. Version-sensitive facts live here, not in code.

Sources (looked up 2026-11-13):
- Modal prices: https://modal.com/pricing and `modal billing rates --json`
- vLLM release: https://pypi.org/project/vllm/
- Model revisions and licenses: Hugging Face model cards
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "results"
RUNS_DIR = RESULTS_DIR / "runs"
DOCS_DIR = ROOT / "docs"

# --- Modal -----------------------------------------------------------------
APP_NAME = "inference-control-room"
VOLUME_NAME = "inference-control-room"
VOLUME_MOUNT = "/vol"
PYTHON_VERSION = "3.12"
CUDA_IMAGE = "nvidia/cuda:12.9.0-devel-ubuntu22.04"

# USD per hour, Modal list prices.
PRICE_PER_HOUR = {
    "L4": 0.80,
    "H100": 3.95,
    "none": 0.0,  # CPU-only functions
    "cpu_core": 0.0473,
    "mem_gib": 0.008,
}

# GPU strings. "H100!" stops Modal from silently upgrading to an H200.
GPU_L4 = "L4"
GPU_L4_FLEET = "L4:4"
GPU_L4_FLEET_FALLBACK = "L4:2"
GPU_H100 = "H100!"

# --- Budget (USD), PLAN.md section 1.1 --------------------------------------
# The plan's caps. Charlie raised the fleet reserve by $17 (total 52, soft stop 45,
# fleet 35) on 2026-11-15 for a 4-GPU rerun. Five requests for 4 GPUs never got a
# container, so the raise was taken back on 2026-11-16 unspent (docs/DECISIONS.md).
BUDGET_TOTAL = 35.0
BUDGET_SOFT_STOP = 28.0  # after this: only remaining fleet runs, then H100 if affordable
BUDGET_BY_CATEGORY = {"dev": 10.0, "fleet": 18.0, "h100": 7.0}

# Fleet container: 4 vLLM replicas + router + load generator + recorder.
# Sized from the measured CPU and RAM of one replica (docs/DECISIONS.md, "Fleet sizing").
# The plan's fleet is 4 L4s in one container. Modal never scheduled `L4:4` during the build
# (five requests on three days, 50 to 80 minutes of queue each), so the plan's fallback is
# in use: 2 L4s. Set this back to 4 to analyse 4-GPU runs if they are made later.
FLEET_REPLICAS = 2
FLEET_CPU = 8.0
FLEET_MEMORY_MIB = 65536
FLEET_SESSION_BUDGET_S = 50 * 60  # stop starting new runs after this; the timeout is 60 min
SWEEP_SESSION_BUDGET_S = 27 * 60  # same idea for single-replica sessions (timeout 30 min)

TIMEOUT_DEFAULT_S = 15 * 60
TIMEOUT_SWEEP_S = 30 * 60
TIMEOUT_FLEET_S = 60 * 60

# --- vLLM and models --------------------------------------------------------
VLLM_VERSION = "0.33.0"
SERVED_MODEL_NAME = "llm"

MODELS = {
    "bf16": {
        "repo": "Qwen/Qwen2.5-7B-Instruct",
        "revision": "a09a35458c702b33eeacc393d103063234e8bc28",
    },
    "awq": {
        "repo": "Qwen/Qwen2.5-7B-Instruct-AWQ",
        "revision": "b25037543e9394b818fdfca67ab2a00ecc7dd641",
    },
    "draft": {
        "repo": "Qwen/Qwen2.5-0.5B-Instruct",
        "revision": "7ae557604adf67be50417f59c2c2f167def9a775",
    },
}

# --- Data -------------------------------------------------------------------
BURSTGPT_URL = (
    "https://github.com/HPMLL/BurstGPT/releases/download/v2.0/BurstGPT_without_fails_1.csv"
)
GSM8K_REPO = "openai/gsm8k"
GSM8K_REVISION = "740312add88f781978c0658806c59bc2815b9866"
GSM8K_FILE = "main/test-00000-of-00001.parquet"
GSM8K_SUBSET_SIZE = 250
GSM8K_SEED = 0

# Paths inside the Modal Volume.
VOL_HF = f"{VOLUME_MOUNT}/hf"
VOL_DATA = f"{VOLUME_MOUNT}/data"
VOL_RUNS = f"{VOLUME_MOUNT}/runs"
VOL_VLLM_CACHE = f"{VOLUME_MOUNT}/vllm-cache"


def fleet_prefix(replicas: int | None = None) -> str:
    """Run-id prefix of fleet runs: `fleet-` for 4 GPUs, `fleetx2-` for the 2-GPU fallback."""
    n = replicas or FLEET_REPLICAS
    return "fleet-" if n == 4 else f"fleetx{n}-"


def hourly_cost(gpu: str, gpu_count: int, cpu_cores: float, memory_gib: float) -> float:
    """Cost of one container per hour: GPUs + requested CPU + requested memory."""
    gpu_rate = PRICE_PER_HOUR[gpu.rstrip("!")]
    return (
        gpu_rate * gpu_count
        + cpu_cores * PRICE_PER_HOUR["cpu_core"]
        + memory_gib * PRICE_PER_HOUR["mem_gib"]
    )
