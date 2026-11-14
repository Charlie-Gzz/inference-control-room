"""Fleet experiments (M4). Everything runs inside one container with several GPUs.

One vLLM process per GPU on its own localhost port, the Go router in front, and the load
generator and recorder next to them. Nothing leaves the container.

A session is a list of runs. Each finished run is written to the Volume and committed
right away, and a rerun of the session skips what is already there. Before every run the
prefix cache of every replica and the router's prefix table are reset.

Run kinds:
- `fixed`      steady traffic at one rate (warmup, then a measured window)
- `ramp`       stepped capacity ramp
- `autoscale`  bursty window, with the autoscaler (starts at 1 replica) or static
- `proxycheck` the same light traffic sent direct to replica 0 and through the router
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from icr import config
from icr.autoscale.autoscaler import Autoscaler, AutoscalerConfig
from icr.fleet import experiment
from icr.fleet.router_proc import RouterProcess
from icr.modal_app.sweep import _annotate, read_run
from icr.modal_app.sysinfo import ResourceSampler, nvidia_smi, vllm_version
from icr.modal_app.vllm_proc import ServerConfig, VllmServer
from icr.workloads import generator

BASE_PORT = 8001
ROUTER_PORT = 8080
DRAIN_ALLOWANCE_S = 45.0  # time after the last arrival for requests to finish


def run_id(run: dict) -> str:
    """Stable id of one run: kind, workload, policy (or variant) and seed."""
    return f"fleet-{run['kind']}-{run['workload']}-{run['policy']}-s{run['seed']}"


def planned_seconds(run: dict) -> float:
    """Traffic time of one run, without the drain allowance."""
    if run["kind"] == "ramp":
        return run["warmup_s"] + run["level_s"] * len(run["rates_rps"])
    return run["warmup_s"] + run["measured_s"]


def build_specs(run: dict) -> list:
    if run["kind"] == "ramp":
        return generator.ramp_workload(
            run["workload"], run["seed"], run["rates_rps"], run["level_s"], run["warmup_s"]
        )
    return generator.steady_workload(
        run["workload"], run["seed"], run["rate_rps"], planned_seconds(run), run["warmup_s"],
        segment=run.get("segment", "steady"),
    )  # fmt: skip


class VllmManager:
    """ReplicaManager for the autoscaler: starts and stops real vLLM processes."""

    def __init__(self, servers: dict[int, VllmServer], startup_timeout_s: float = 420):
        self.servers, self.timeout = servers, startup_timeout_s

    def url(self, index: int) -> str:
        return self.servers[index].url

    async def start(self, index: int) -> None:
        server = self.servers[index]
        server.start()
        await asyncio.to_thread(server.wait_ready, self.timeout)

    async def stop(self, index: int) -> None:
        await asyncio.to_thread(self.servers[index].stop)


class Fleet:
    """The replicas and the router of one session."""

    def __init__(self, cfg: ServerConfig, session: dict, make_server=VllmServer):
        base = session.get("base_port", BASE_PORT)
        self.servers = {
            i: make_server(cfg, base + i, gpu_index=i) for i in range(session["replicas"])
        }
        self.urls = {i: s.url for i, s in self.servers.items()}
        self.router = RouterProcess(
            self.urls, "round-robin", session.get("router_port", ROUTER_PORT),
            flags={"table-chunks": session["table_chunks"]},
        )  # fmt: skip
        self.startups: dict[int, float] = {}

    def ensure_all_up(self, timeout: float = 420) -> None:
        """Start every replica that is not running (in parallel) and wait for all of them."""
        down = [
            i for i, s in self.servers.items() if s.process is None or s.process.poll() is not None
        ]
        for i in down:
            self.servers[i].start()
        for i in down:
            self.startups[i] = round(self.servers[i].wait_ready(timeout), 1)

    def clean_state(self, live: dict[int, str]) -> None:
        """Empty prefix caches and an empty router table, so no run helps the next."""
        for i in live:
            self.servers[i].reset_prefix_cache()
        self.router.set_replicas(live)
        self.router.reset()

    def stop(self) -> None:
        self.router.stop()
        for server in self.servers.values():
            server.stop()


def run_session(session: dict, commit, make_server=VllmServer, runs_root: Path | None = None):
    """Run every unfinished run of the session. `commit` persists the Volume.

    `make_server` and `runs_root` exist for the local dry run against the mock fleet.
    """
    runs_root = runs_root or Path(config.VOL_RUNS)
    deadline = time.monotonic() + session["budget_s"]
    cfg_dict = session["config"]
    cfg = ServerConfig(**{**cfg_dict, "extra_args": tuple(cfg_dict.get("extra_args", ()))})
    sampler = ResourceSampler().start()
    environment = {"gpu": nvidia_smi(), "vllm_version": vllm_version()}
    fleet = Fleet(cfg, session, make_server)
    runs: dict[str, dict] = {}
    skipped: list[str] = []
    out: dict = {"runs": runs, "skipped": skipped, **environment}
    try:
        fleet.ensure_all_up()
        fleet.router.start()
        out["startup_s"] = dict(fleet.startups)
        for run in session["runs"]:
            rid = run_id(run)
            directory = runs_root / rid
            if (directory / "meta.json").exists():
                runs[rid] = read_run(directory)
                continue
            needed = planned_seconds(run) + DRAIN_ALLOWANCE_S + 60
            if run["kind"] == "proxycheck":
                needed *= 2
            if time.monotonic() + needed > deadline:
                skipped.append(rid)  # not enough time left in this session: rerun later
                continue
            meta = {
                "run_id": rid, "kind": "fleet", "run": run, "label": session["label"],
                "config": cfg.to_dict(), "replicas": session["replicas"],
                "workload": run["workload"], "policy": run["policy"], "seed": run["seed"],
                "session_id": session["session_id"], "table_chunks": session["table_chunks"],
                "startup_s": dict(fleet.startups), **environment,
            }  # fmt: skip
            mark = sampler.mark()
            asyncio.run(_run_one(fleet, run, session, directory, meta))
            for d in _directories(directory, run):
                _annotate(d, {"container_resources": sampler.summary(mark)})
                runs[d.name] = read_run(d)
            commit()
    except Exception as e:  # keep finished runs; report the failure with server logs
        out["error"] = repr(e)[:500]
        out["logs"] = {i: s.log_tail(40) for i, s in fleet.servers.items()}
    finally:
        fleet.stop()
        sampler.stop()
    out["resources"] = sampler.summary()
    return out


def _directories(directory: Path, run: dict) -> list[Path]:
    if run["kind"] != "proxycheck":
        return [directory]
    return [directory, directory.with_name(directory.name + "-direct")]


async def _run_one(fleet: Fleet, run: dict, session: dict, out: Path, meta: dict) -> None:
    specs = build_specs(run)
    if run["kind"] == "proxycheck":
        # Same traffic twice on replica 0: through the router, then straight to vLLM.
        one = {0: fleet.urls[0]}
        fleet.clean_state(one)
        fleet.router.set_policy("round-robin")
        await experiment.run(
            specs, targets=[fleet.router.url], replica_urls=one, out_dir=out, meta=meta
        )
        fleet.clean_state(one)
        direct = {**meta, "run_id": out.name + "-direct", "policy": "direct"}
        await experiment.run(
            specs, targets=[fleet.urls[0]], replica_urls=one,
            out_dir=out.with_name(out.name + "-direct"), meta=direct,
        )  # fmt: skip
        fleet.router.set_replicas(fleet.urls)
        return

    if run["kind"] == "autoscale" and run["policy"] == "autoscaled":
        for i in list(fleet.servers)[1:]:  # start from one replica
            fleet.servers[i].stop()
        live = {0: fleet.urls[0]}
        fleet.clean_state(live)
        fleet.router.set_policy(run["router_policy"])
        scaler_config = AutoscalerConfig(**session["autoscaler"])
        scaler = Autoscaler(VllmManager(fleet.servers), fleet.router, scaler_config, [0])
        meta = {**meta, "autoscaler": scaler_config.to_dict()}
        try:
            await experiment.run(
                specs, targets=[fleet.router.url], replica_urls=live, out_dir=out, meta=meta,
                autoscaler=scaler,
            )  # fmt: skip
        finally:
            await asyncio.to_thread(fleet.ensure_all_up)  # the next run needs every replica
            fleet.router.set_replicas(fleet.urls)
        return

    fleet.clean_state(fleet.urls)
    fleet.router.set_policy(run.get("router_policy", run["policy"]))
    await experiment.run(
        specs, targets=[fleet.router.url], replica_urls=fleet.urls, out_dir=out, meta=meta
    )
