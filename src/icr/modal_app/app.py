"""Modal entry points. Run with `uv run modal run -m icr.modal_app.app::<entrypoint>`.

Rules from PLAN.md section 1.1 that this file enforces:
- `modal run` only, one container at a time (`max_containers=1`), nothing exposed.
- Every GPU function has a timeout and a budget check before it starts.
- Downloads happen on CPU. Results go to the Volume and are committed there right away.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import modal

from icr import config

app = modal.App(config.APP_NAME, include_source=False)
volume = modal.Volume.from_name(config.VOLUME_NAME, create_if_missing=True, version=2)

SRC = Path(__file__).resolve().parents[1]  # src/icr
IGNORE = ["**/__pycache__", "**/*.pyc"]
ENV = {
    "HF_HOME": config.VOL_HF,
    "VLLM_CACHE_ROOT": config.VOL_VLLM_CACHE,
    "HF_XET_HIGH_PERFORMANCE": "1",
}

cpu_image = (
    modal.Image.debian_slim(python_version=config.PYTHON_VERSION)
    .uv_pip_install("huggingface_hub>=0.30", "pyarrow>=17")
    .env(ENV)
    .add_local_dir(SRC, "/root/icr", ignore=IGNORE)
)

gpu_image = (
    modal.Image.from_registry(config.CUDA_IMAGE, add_python=config.PYTHON_VERSION)
    .entrypoint([])
    .uv_pip_install(f"vllm=={config.VLLM_VERSION}")
    .env(ENV)
    .add_local_dir(SRC, "/root/icr", ignore=IGNORE)
)

VOLUMES = {config.VOLUME_MOUNT: volume}

# Requested resources per function (billed even if unused, so keep them tight).
CPU_DOWNLOAD = {"cpu": 2.0, "memory": 4096}
L4_SINGLE = {"cpu": 4.0, "memory": 16384}


# --- remote functions -------------------------------------------------------


@app.function(image=cpu_image, volumes=VOLUMES, timeout=config.TIMEOUT_SWEEP_S, max_containers=1,
              **CPU_DOWNLOAD)  # fmt: skip
def download_fn() -> dict:
    from icr.modal_app import download

    out = {"models": download.download_models()}
    volume.commit()
    out["burstgpt"] = download.download_burstgpt()
    out["gsm8k"] = download.download_gsm8k()
    volume.commit()
    return out


@app.function(image=gpu_image, gpu=config.GPU_L4, volumes=VOLUMES,
              timeout=config.TIMEOUT_DEFAULT_S, max_containers=1, **L4_SINGLE)  # fmt: skip
def smoke_fn(run_id: str) -> dict:
    from icr.modal_app import smoke

    result = smoke.run_smoke()
    out = Path(config.VOL_RUNS) / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "smoke.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    volume.commit()
    return result


# --- local entry points -----------------------------------------------------


def _timed(fn, *args):
    """Call a remote function and return (result, wall-clock seconds including startup)."""
    start = time.monotonic()
    result = fn.remote(*args)
    return result, time.monotonic() - start


@app.local_entrypoint()
def download():
    """CPU only: models, BurstGPT and the GSM8K subset into the Volume."""
    from icr import ledger
    from icr.workloads import burstgpt

    result, seconds = _timed(download_fn)
    segments = result["burstgpt"].pop("segments")
    burstgpt.SEGMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    burstgpt.SEGMENTS_FILE.write_text(json.dumps(segments), encoding="utf-8", newline="\n")
    for name, seg in segments["segments"].items():
        seg.pop("arrivals")
        print(name, seg)
    print(json.dumps(result, indent=1))
    ledger.record(
        purpose="download models + data (CPU only)", category="dev", gpu="none", gpu_count=0,
        cpu=CPU_DOWNLOAD["cpu"], memory_gib=CPU_DOWNLOAD["memory"] / 1024, billed_seconds=seconds,
    )  # fmt: skip


@app.local_entrypoint()
def smoke():
    """One L4: start vLLM (AWQ), 20 requests, /metrics, resource use."""
    from icr import ledger

    res = {"cpu": L4_SINGLE["cpu"], "memory_gib": L4_SINGLE["memory"] / 1024}
    ledger.check_budget("dev", "L4", 1, max_seconds=config.TIMEOUT_DEFAULT_S, **res)
    run_id = time.strftime("smoke-%Y%m%d-%H%M%S", time.gmtime())
    result, seconds = _timed(smoke_fn, run_id)

    out = config.RUNS_DIR / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.txt").write_text(result.pop("metrics_text", ""), "utf-8", newline="\n")
    (out / "vllm_log_tail.txt").write_text(result.pop("vllm_log_tail", ""), "utf-8", newline="\n")
    row = ledger.record(
        purpose="M0 smoke test (AWQ, 20 requests)", category="dev", gpu="L4", gpu_count=1,
        billed_seconds=seconds, run_id=run_id, **res,
    )  # fmt: skip
    result["billed_seconds"], result["estimated_cost_usd"] = row["billed_seconds"], row["cost_usd"]
    (out / "meta.json").write_text(json.dumps(result, indent=1), "utf-8", newline="\n")
    print(f"ok={result['ok']} startup={result.get('startup_seconds')}s billed={seconds:.0f}s")
    print(f"cost=${row['cost_usd']:.3f} -> {out}")
    if not result["ok"]:
        raise SystemExit(result.get("error"))
