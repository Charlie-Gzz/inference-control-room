"""Single-replica config sweep (M3). Runs inside one GPU container.

One session = a few jobs. A job is one server config and its tasks: start vLLM once, run
the tasks against it, stop it. Each finished (config, task) is written to the Volume right away,
and a rerun skips what is already there.

Tasks:
- `ramp:<mix>`  stepped traffic ramp at the session's rates, to find the capacity at the SLO
- `ramp:<mix>@<r1>;<r2>;...=<tag>`  the same with its own rates; the tag (`cal`, `fine`)
                names calibration ramps, so they never collide with the sweep's own ramp
- `calib:<mix>@<r1>;<r2>;...`  both calibration ramps in one go: the coarse ramp at these
                rates (`-cal`), then the fine ramp between its last passing and first
                failing level (`-fine`)
- `gsm8k`       accuracy on the GSM8K subset
- `greedy`      greedy outputs for a fixed prompt sample, twice (for the match-rate check)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from icr import clock, config
from icr.fleet import experiment
from icr.modal_app.sysinfo import ResourceSampler, nvidia_smi, vllm_version
from icr.modal_app.vllm_proc import ServerConfig, VllmServer
from icr.quality import checks
from icr.workloads import generator

GREEDY_PROMPTS = 100
GREEDY_SEED = 123
STARTUP_ALLOWANCE_S = 215.0  # measured: 83 to 200 s for AWQ with warm JIT caches
RUN_FILES = ("requests.jsonl", "replicas.jsonl", "meta.json", "result.json", "metrics.txt")


def parse_task(task: str) -> dict:
    """`ramp:chat@4;5;6=fine` -> kind, mix, rates (or None) and tag (or '')."""
    body, _, tag = task.partition("=")
    body, _, rates = body.partition("@")
    kind, _, mix = body.partition(":")
    return {
        "kind": kind,
        "mix": mix,
        "rates": [float(r) for r in rates.split(";")] if rates else None,
        "tag": tag,
    }


def run_id(label: str, cfg_name: str, task: str) -> str:
    t = parse_task(task)
    parts = ["sweep", label, cfg_name, t["kind"], t["mix"], t["tag"]]
    return "-".join(p for p in parts if p)


def task_seconds(task: str, ramp: dict) -> float:
    """Rough time one task needs, for the session's time guard."""
    t = parse_task(task)
    if t["kind"] in ("ramp", "calib", "fine-of"):
        levels = len(t["rates"] or ramp["rates_rps"])
        one = ramp["warmup_s"] + levels * ramp["level_s"] + 90  # measured: about 40 s over
        return 2 * one if t["kind"] == "calib" else one
    return 120 if t["kind"] == "gsm8k" else 90  # measured: 46 s and about 30 s


def coarse_task(task: str) -> str:
    """The coarse ramp of a `calib` task, as an ordinary tagged ramp task."""
    return "ramp:" + task.split(":", 1)[1] + "=cal"


def fine_task(label: str, cfg_name: str, task: str) -> str | None:
    """The fine ramp that follows a finished coarse ramp, or None if it never missed the SLO."""
    from icr.analysis import calibrate, runs

    directory = Path(config.VOL_RUNS) / run_id(label, cfg_name, coarse_task(task))
    meta = json.loads((directory / "meta.json").read_text("utf-8"))
    coarse = calibrate.ramp_capacity(runs.Run(directory.name, directory, meta))
    if coarse["first_miss"] is None:
        return None
    levels = ";".join(str(r) for r in calibrate.fine_levels(coarse))
    return f"ramp:{parse_task(task)['mix']}@{levels}=fine"


def read_run(directory: Path) -> dict:
    """The run's files as {name: text}, to send back to the local machine."""
    return {f.name: f.read_text("utf-8") for f in directory.iterdir() if f.name in RUN_FILES}


def greedy_prompts() -> list[list[dict]]:
    """A fixed sample of chat prompts for the greedy-output check."""
    specs = generator.steady_workload("chat", GREEDY_SEED, rate_rps=5.0, duration_s=60.0)
    return [s.messages for s in specs[:GREEDY_PROMPTS]]


def run_session(session: dict, commit) -> dict:
    """Run every (config, task) of the session. `commit` persists the Volume."""
    label = session["label"]
    sampler = ResourceSampler().start()
    environment = {"gpu": nvidia_smi(), "vllm_version": vllm_version()}
    runs: dict[str, dict] = {}
    startups: dict[str, dict] = {}
    skipped: list[str] = []
    deadline = time.monotonic() + session["budget_s"]

    def fits(task: str, startup: float = 0.0) -> bool:
        return time.monotonic() + startup + task_seconds(task, session["ramp"]) < deadline

    for job in session["jobs"]:  # one job = one server config and the tasks to run on it
        cfg_dict = job["config"]
        cfg = ServerConfig.from_dict(cfg_dict)
        todo = [t for t in job["tasks"] if not _done(label, cfg.name, t)]
        for task in job["tasks"]:
            if task not in todo:
                for rid in _result_ids(label, cfg.name, task):
                    runs[rid] = read_run(Path(config.VOL_RUNS) / rid)
        if not todo:
            continue
        if not fits(todo[0], startup=STARTUP_ALLOWANCE_S):  # no time to start another server
            skipped += [run_id(label, cfg.name, t) for t in todo]
            continue
        server = VllmServer(cfg, port=8000)
        try:
            server.start()
            startup_s = round(server.wait_ready(timeout=session.get("startup_timeout_s", 420)), 1)
        except Exception as e:
            startups[cfg.name] = {"ok": False, "error": repr(e)[:300], "log": server.log_tail(80)}
            server.stop()
            continue
        startups[cfg.name] = {"ok": True, "startup_s": startup_s}
        try:
            queue = list(todo)
            while queue:
                task = queue.pop(0)
                rid = run_id(label, cfg.name, task)
                if not fits(task):
                    skipped.append(rid)  # rerun the session later: finished tasks are kept
                    continue
                if parse_task(task)["kind"] == "calib":  # coarse ramp now, fine ramp right after
                    steps = (
                        [coarse_task(task)] if not _done(label, cfg.name, coarse_task(task)) else []
                    )
                    queue = [*steps, f"fine-of:{task}", *queue]
                    continue
                if task.startswith("fine-of:"):
                    fine = fine_task(label, cfg.name, task.removeprefix("fine-of:"))
                    if fine is None:
                        startups[cfg.name]["note"] = f"{task}: the coarse ramp never missed the SLO"
                        continue
                    task, rid = fine, run_id(label, cfg.name, fine)
                out = Path(config.VOL_RUNS) / rid
                meta = {
                    "run_id": rid, "kind": "sweep", "label": label, "config": cfg.to_dict(),
                    "task": task, "seed": session["seed"], "startup_s": startup_s,
                    "session_id": session["session_id"], **environment,
                }  # fmt: skip
                mark = sampler.mark()
                asyncio.run(_run_task(task, server, session, out, meta))
                _annotate(out, {"container_resources": sampler.summary(mark)})
                (out / "metrics.txt").write_text(server.metrics_text(), encoding="utf-8")
                commit()
                runs[rid] = read_run(out)
        except Exception as e:  # keep finished tasks; report the failure
            startups[cfg.name]["task_error"] = repr(e)[:300]
            startups[cfg.name]["log"] = server.log_tail(80)
        finally:
            server.stop()
    sampler.stop()
    return {
        "runs": runs, "startups": startups, "skipped": skipped,
        "resources": sampler.summary(), **environment,
    }  # fmt: skip


def _done(label: str, cfg_name: str, task: str) -> bool:
    if parse_task(task)["kind"] == "calib":  # done when its fine ramp exists
        task = f"ramp:{parse_task(task)['mix']}=fine"
    out = Path(config.VOL_RUNS) / run_id(label, cfg_name, task)
    return (out / "meta.json").exists() or (out / "result.json").exists()


def _result_ids(label: str, cfg_name: str, task: str) -> list[str]:
    """Run ids a finished task left behind (a `calib` task leaves two ramps)."""
    if parse_task(task)["kind"] != "calib":
        return [run_id(label, cfg_name, task)]
    mix = parse_task(task)["mix"]
    return [run_id(label, cfg_name, f"ramp:{mix}={tag}") for tag in ("cal", "fine")]


def _annotate(out: Path, extra: dict) -> None:
    """Add fields to the run's meta.json (or result.json for non-load tasks)."""
    path = out / "meta.json" if (out / "meta.json").exists() else out / "result.json"
    data = json.loads(path.read_text("utf-8"))
    path.write_text(json.dumps({**data, **extra}, indent=1), encoding="utf-8")


async def _run_task(task: str, server: VllmServer, session: dict, out: Path, meta: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    parsed = parse_task(task)
    if parsed["kind"] == "ramp":
        mix = parsed["mix"]
        ramp = {**session["ramp"], "rates_rps": parsed["rates"] or session["ramp"]["rates_rps"]}
        server.reset_prefix_cache()
        specs = generator.ramp_workload(
            mix, session["seed"], ramp["rates_rps"], ramp["level_s"], ramp["warmup_s"]
        )
        meta = {**meta, "workload": mix, "policy": "direct", "ramp": ramp}
        await experiment.run(
            specs, targets=[server.url], replica_urls={0: server.url}, out_dir=out, meta=meta
        )
    elif task == "gsm8k":
        rows = checks.load_gsm8k(Path(config.VOL_DATA) / "gsm8k" / "test_250.jsonl")
        start = clock.now()
        result = await checks.gsm8k_accuracy(server.url, rows)
        result["seconds"] = round(clock.now() - start, 1)
        _write_result(out, {**meta, "gsm8k": result})
    elif task == "greedy":
        prompts = greedy_prompts()
        first = await checks.complete_all(server.url, prompts, max_tokens=96, concurrency=16)
        second = await checks.complete_all(server.url, prompts, max_tokens=96, concurrency=16)
        _write_result(out, {**meta, "greedy": {"first": first, "second": second}})
    else:
        raise ValueError(f"unknown task {task!r}")


def _write_result(out: Path, data: dict) -> None:
    (out / "result.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
