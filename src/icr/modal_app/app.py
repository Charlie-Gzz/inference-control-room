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
ROUTER_BINARY = SRC.parents[1] / "router" / "bin" / "switchyard-router"  # linux build
ENV = {
    "HF_HOME": config.VOL_HF,
    "HF_XET_HIGH_PERFORMANCE": "1",
    # JIT and compile caches live in the Volume, so later containers start faster.
    "VLLM_CACHE_ROOT": config.VOL_VLLM_CACHE,
    "FLASHINFER_WORKSPACE_BASE": f"{config.VOLUME_MOUNT}/flashinfer",
    "TRITON_CACHE_DIR": f"{config.VOLUME_MOUNT}/triton-cache",
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
)
if ROUTER_BINARY.exists():  # built by `icr build-router --linux`
    gpu_image = gpu_image.add_local_file(
        ROUTER_BINARY, "/usr/local/bin/switchyard-router", copy=True
    )
    gpu_image = gpu_image.run_commands("chmod +x /usr/local/bin/switchyard-router")
gpu_image = gpu_image.add_local_dir(SRC, "/root/icr", ignore=IGNORE)

VOLUMES = {config.VOLUME_MOUNT: volume}

# Requested resources per function (billed even if unused, so keep them tight).
CPU_DOWNLOAD = {"cpu": 2.0, "memory": 4096}
L4_SINGLE = {"cpu": 4.0, "memory": 16384}
L4_FLEET = {"cpu": config.FLEET_CPU, "memory": config.FLEET_MEMORY_MIB}


def _resources(spec: dict) -> dict:
    return {"cpu": spec["cpu"], "memory_gib": spec["memory"] / 1024}


# --- remote functions -------------------------------------------------------


@app.function(image=cpu_image, volumes=VOLUMES, timeout=config.TIMEOUT_SWEEP_S, max_containers=1,
              **CPU_DOWNLOAD)  # fmt: skip
def download_fn() -> dict:
    from icr.modal_app import download

    start = time.monotonic()
    out = {"models": download.download_models()}
    volume.commit()
    out["burstgpt"] = download.download_burstgpt()
    out["gsm8k"] = download.download_gsm8k()
    volume.commit()
    out["container_seconds"] = time.monotonic() - start
    return out


@app.function(image=gpu_image, gpu=config.GPU_L4, volumes=VOLUMES,
              timeout=config.TIMEOUT_DEFAULT_S, max_containers=1, **L4_SINGLE)  # fmt: skip
def smoke_fn(run_id: str) -> dict:
    from icr.modal_app import smoke

    start = time.monotonic()
    result = smoke.run_smoke()
    out = Path(config.VOL_RUNS) / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "smoke.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    volume.commit()
    result["container_seconds"] = time.monotonic() - start
    return result


@app.function(image=gpu_image, gpu=config.GPU_L4, volumes=VOLUMES,
              timeout=config.TIMEOUT_SWEEP_S, max_containers=1, **L4_SINGLE)  # fmt: skip
def sweep_l4_fn(session: dict) -> dict:
    from icr.modal_app import sweep

    start = time.monotonic()
    result = sweep.run_session(session, volume.commit)
    volume.commit()
    result["container_seconds"] = time.monotonic() - start
    return result


@app.function(image=gpu_image, gpu=config.GPU_L4_FLEET, volumes=VOLUMES,
              timeout=config.TIMEOUT_FLEET_S, max_containers=1, **L4_FLEET)  # fmt: skip
def fleet_l4_fn(session: dict) -> dict:
    from icr.modal_app import fleet

    start = time.monotonic()
    result = fleet.run_session(session, volume.commit)
    volume.commit()
    result["container_seconds"] = time.monotonic() - start
    return result


# --- local entry points -----------------------------------------------------


def _save_runs(runs: dict[str, dict], extra_meta: dict) -> None:
    """Write run files returned by a remote function into results/runs/."""
    from icr.analysis import runs as saved

    for run_id, files in runs.items():
        for name, text in files.items():
            if name in ("meta.json", "result.json"):
                text = json.dumps({**json.loads(text), **extra_meta}, indent=1)
            saved.write_file(config.RUNS_DIR / run_id, name, text)


@app.local_entrypoint()
def download():
    """CPU only: models, BurstGPT and the GSM8K subset into the Volume."""
    from icr import ledger
    from icr.workloads import burstgpt

    result = download_fn.remote()
    segments = result["burstgpt"].pop("segments")
    burstgpt.SEGMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    burstgpt.SEGMENTS_FILE.write_text(json.dumps(segments), encoding="utf-8", newline="\n")
    for name, seg in segments["segments"].items():
        print(name, {k: v for k, v in seg.items() if k != "arrivals"})
    print(json.dumps(result, indent=1))
    ledger.record(
        purpose="download models + data (CPU only)", category="dev", gpu="none", gpu_count=0,
        container_seconds=result["container_seconds"], app_id=app.app_id or "",
        **_resources(CPU_DOWNLOAD),
    )  # fmt: skip


@app.local_entrypoint()
def smoke():
    """One L4: start vLLM (AWQ), 20 requests, /metrics, resource use."""
    from icr import ledger

    res = _resources(L4_SINGLE)
    ledger.check_budget("dev", "L4", 1, max_seconds=config.TIMEOUT_DEFAULT_S, **res)
    run_id = time.strftime("smoke-%Y%m%d-%H%M%S", time.gmtime())
    result = smoke_fn.remote(run_id)

    out = config.RUNS_DIR / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.txt").write_text(result.pop("metrics_text", ""), "utf-8", newline="\n")
    (out / "vllm_log_tail.txt").write_text(result.pop("vllm_log_tail", ""), "utf-8", newline="\n")
    row = ledger.record(
        purpose="M0 smoke test (AWQ, 20 requests)", category="dev", gpu="L4", gpu_count=1,
        container_seconds=result["container_seconds"], app_id=app.app_id or "", run_id=run_id,
        **res,
    )  # fmt: skip
    result["billed_seconds"], result["estimated_cost_usd"] = row["billed_seconds"], row["cost_usd"]
    (out / "meta.json").write_text(json.dumps(result, indent=1), "utf-8", newline="\n")
    print(f"ok={result['ok']} startup={result.get('startup_seconds')}s cost=${row['cost_usd']:.3f}")
    if not result["ok"]:
        raise SystemExit(result.get("error"))


@app.local_entrypoint()
def sweep(
    configs: str,
    tasks: str = "ramp:chat",
    rates: str = "",
    level_s: float = 40.0,
    warmup_s: float = 30.0,
    seed: int = 0,
    purpose: str = "",
):
    """One L4 session of the config sweep: `--configs awq,fp8 --tasks ramp:chat,gsm8k`.

    Without `--rates`, ramps use the frozen sweep levels (multiples of the baseline's
    saturation rate from results/summaries/calibration.json).
    """
    from icr import ledger
    from icr.fleet import plan
    from icr.modal_app.configs import CONFIGS

    res = _resources(L4_SINGLE)
    ledger.check_budget("dev", "L4", 1, max_seconds=config.TIMEOUT_SWEEP_S, **res)
    names = [n.strip() for n in configs.split(",")]
    default_rates = [float(r) for r in rates.split(",") if r]

    def with_rates(task: str) -> str:
        """Give a plain `ramp:<mix>` task the frozen sweep levels of its workload."""
        if not task.startswith("ramp:") or "@" in task or default_rates:
            return task
        body, _, tag = task.partition("=")
        levels = ";".join(str(r) for r in plan.sweep_rates(body.split(":", 1)[1]))
        return f"{body}@{levels}" + (f"={tag}" if tag else "")

    session = {
        "session_id": time.strftime("l4-%Y%m%d-%H%M%S", time.gmtime()),
        "label": "l4",
        "configs": [CONFIGS[n].to_dict() for n in names],
        "tasks": [with_rates(t.strip()) for t in tasks.split(",")],
        "seed": seed,
        "ramp": {"rates_rps": default_rates, "level_s": level_s, "warmup_s": warmup_s},
        "budget_s": config.SWEEP_SESSION_BUDGET_S,
    }
    purpose = purpose or f"sweep {configs} [{tasks}]"
    ledger_args = dict(category="dev", gpu="L4", gpu_count=1, app_id=app.app_id or "",
                       run_id=session["session_id"], **res)  # fmt: skip
    try:
        result = sweep_l4_fn.remote(session)
    except BaseException as e:  # still record the spend; finished tasks are in the Volume
        ledger.record(purpose=purpose, container_seconds=config.TIMEOUT_SWEEP_S,
                      note=f"FAILED ({type(e).__name__}); billed time is the worst case",
                      **ledger_args)  # fmt: skip
        raise
    row = ledger.record(
        purpose=purpose, container_seconds=result["container_seconds"], **ledger_args
    )
    hourly = config.hourly_cost("L4", 1, res["cpu"], res["memory_gib"])
    _save_runs(result.pop("runs"), {"cost_per_hour_usd": round(hourly, 4)})
    log = config.RESULTS_DIR / "sessions" / f"{session['session_id']}.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        json.dumps({**session, **result, "ledger": row}, indent=1), "utf-8", newline="\n"
    )
    for name, info in result["startups"].items():
        print(name, {k: v for k, v in info.items() if k != "log"})
        if "log" in info:
            print(info["log"][-3000:])
    print(f"container {result['container_seconds']:.0f}s, est ${row['cost_usd']:.3f}")
    print("resources:", result["resources"], "skipped:", result.get("skipped"))


@app.local_entrypoint()
def fleet(items: str, purpose: str = "", max_runs: int = 0):
    """One L4:4 session of fleet runs: `--items chat` or `--items proxycheck,ramp`."""
    from icr import ledger
    from icr.fleet import plan
    from icr.fleet.local import table_chunks_for
    from icr.modal_app.configs import CONFIGS

    res = _resources(L4_FLEET)
    n = config.FLEET_REPLICAS
    ledger.check_budget("fleet", "L4", n, max_seconds=config.TIMEOUT_FLEET_S, **res)
    calib = plan.calibration()
    runs = [r for item in items.split(",") for r in plan.runs_for(item.strip(), calib, n)]
    session = {
        "session_id": time.strftime("fleet-%Y%m%d-%H%M%S", time.gmtime()),
        "label": f"l4x{n}",
        "replicas": n,
        "config": CONFIGS[calib["fleet_config"]].to_dict(),
        "runs": runs[:max_runs] if max_runs else runs,
        "table_chunks": table_chunks_for(calib["kv_cache_tokens"]),
        "autoscaler": calib["autoscaler"],
        "budget_s": config.FLEET_SESSION_BUDGET_S,
    }
    purpose = purpose or f"fleet {items}"
    ledger_args = dict(category="fleet", gpu="L4", gpu_count=n, app_id=app.app_id or "",
                       run_id=session["session_id"], **res)  # fmt: skip
    try:
        result = fleet_l4_fn.remote(session)
    except BaseException as e:  # still record the spend; finished runs are in the Volume
        ledger.record(purpose=purpose, container_seconds=config.TIMEOUT_FLEET_S,
                      note=f"FAILED ({type(e).__name__}); billed time is the worst case",
                      **ledger_args)  # fmt: skip
        raise
    row = ledger.record(
        purpose=purpose, container_seconds=result["container_seconds"], **ledger_args
    )
    hourly = config.hourly_cost("L4", n, res["cpu"], res["memory_gib"])
    _save_runs(result.pop("runs"), {"cost_per_hour_usd": round(hourly, 4)})
    log = config.RESULTS_DIR / "sessions" / f"{session['session_id']}.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        json.dumps({**session, **result, "ledger": row}, indent=1), "utf-8", newline="\n"
    )
    print(f"startup: {result.get('startup_s')}  skipped: {result['skipped']}")
    if "error" in result:
        print("ERROR:", result["error"])
        for i, text in result.get("logs", {}).items():
            print(f"--- replica {i}\n{text[-2000:]}")
    print(f"container {result['container_seconds']:.0f}s, est ${row['cost_usd']:.3f}")
    print("resources:", result["resources"])
