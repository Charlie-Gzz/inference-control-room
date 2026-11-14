"""The `icr` command line: one entry point for tests, lint, GPU runs, results and assets."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer

from icr.fleet.router_proc import GO, ROUTER_DIR

ROOT = Path(__file__).resolve().parents[2]

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)


def _run(cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> int:
    """Run a command, echo it, and return its real exit code."""
    typer.echo(f"$ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})}).returncode


def _go_available() -> bool:
    return (GO.exists() or shutil.which(str(GO)) is not None) and (ROUTER_DIR / "go.mod").exists()


@app.command()
def test() -> None:
    """Run the Python tests and the Go tests."""
    codes = [_run([sys.executable, "-m", "pytest"])]
    if _go_available():
        codes.append(_run([str(GO), "test", "./..."], cwd=ROUTER_DIR))
    raise typer.Exit(max(codes))


@app.command()
def lint() -> None:
    """Run ruff (check and format check) and go vet."""
    codes = [
        _run([sys.executable, "-m", "ruff", "check", "src", "tests"]),
        _run([sys.executable, "-m", "ruff", "format", "--check", "src", "tests"]),
    ]
    if _go_available():
        codes.append(_run([str(GO), "vet", "./..."], cwd=ROUTER_DIR))
    raise typer.Exit(max(codes))


@app.command("build-router")
def build_router(linux: bool = typer.Option(False, help="Cross-compile for the Modal image.")):
    """Compile the Go router (native by default)."""
    from icr.fleet import router_proc

    typer.echo(router_proc.build(linux=linux))


@app.command()
def mock(replicas: int = 4, base_port: int = 8001) -> None:
    """Serve the MOCK fleet on localhost (development only)."""
    import asyncio

    from icr.mock.fleet import serve_forever
    from icr.mock.replica import MockParams

    asyncio.run(serve_forever(replicas, base_port, MockParams()))


@app.command("mock-run")
def mock_run(workload: str = "chat", rate: float = 30.0, duration: float = 40.0, seed: int = 0):
    """Same traffic through all three policies on the MOCK fleet. Never published."""
    import asyncio

    from icr.fleet.local import mock_comparison

    results = asyncio.run(mock_comparison(workload, seed=seed, rate_rps=rate, duration_s=duration))
    typer.echo(f"\nMOCK fleet, workload={workload}, {rate} rps. Not real numbers.")
    header = ("policy", "p50 TTFT", "p95 TTFT", "goodput", "cache hit", "imbalance")
    typer.echo("".join(f"{h:>14}" for h in header))
    for policy, s in results.items():
        row = (
            policy,
            f"{s['ttft_p50_s']:.3f}",
            f"{s['ttft_p95_s']:.3f}",
            f"{s['goodput']:.1%}",
            f"{s['cache_hit_rate']:.1%}",
            f"{s['imbalance']:.2f}",
        )
        typer.echo("".join(f"{v:>14}" for v in row))


@app.command()
def calibrate(fleet_config: str = typer.Option("", help="Server config the fleet will use.")):
    """Write results/summaries/calibration.json from the saved calibration ramps."""
    from icr.analysis import calibrate as calibration

    data = calibration.write(fleet_config or None)
    typer.echo(f"baseline {data['baseline']}: R_sat {data['baseline_r_sat']}")
    typer.echo(f"fleet config {data['fleet_config']}: R_sat {data['r_sat']}")
    typer.echo(f"KV cache: {data['kv_cache_tokens']} tokens per replica")
    for where, found in data["sources"].items():
        for workload, src in found.items():
            if src["stage"] == "cal" and src["first_miss"] is not None:
                levels = ";".join(str(x) for x in calibration.fine_levels(src))
                typer.echo(
                    f"  {where} {workload}: coarse only. Fine ramp: ramp:{workload}@{levels}=fine"
                )


@app.command()
def results() -> None:
    """Recompute every metric from results/runs/ (no GPU) and write the summaries."""
    from icr.analysis import results as report

    summary = report.write()
    typer.echo(f"wrote {report.SUMMARY_FILE} and {report.RESULTS_MD}")
    if summary.get("headline"):
        typer.echo(summary["headline"]["text"])


@app.command()
def charts() -> None:
    """Draw every chart (PNG + SVG) and the interactive page into assets/charts/."""
    from icr.assets import charts as drawing
    from icr.assets import interactive

    for name, status in drawing.write_all().items():
        typer.echo(f"{name:22} {status}")
    typer.echo(f"{'interactive page':22} {interactive.write()}")


@app.command()
def assets(
    video: bool = typer.Option(False, help="Also capture and encode the videos (slow, Docker)."),
) -> None:
    """Regenerate everything derived from results/: summaries, charts, site data,
    storyboards, screenshots, the diagram and (with --video) the videos."""
    from icr.analysis import results as report
    from icr.analysis import site_data
    from icr.assets import charts as drawing
    from icr.assets import interactive, shots, story
    from icr.assets import video as videos

    summary = report.write()
    for name, status in drawing.write_all().items():
        typer.echo(f"chart {name:22} {status}")
    interactive.write()
    typer.echo(f"site data: {site_data.build_all()}")
    stories = story.write_all(summary)
    window = stories["story-main"]["window"]
    request = next(s["request"] for s in stories["story-main"]["scenes"] if s["kind"] == "cold")
    for path in shots.capture(shots.shots(t=window["t0"] + 20.0, pick=request)):
        typer.echo(f"wrote {path}")
    if video:
        for name, path in videos.make_all().items():
            typer.echo(f"video {name}: {path} ({path.stat().st_size / 1e6:.1f} MB)")


@app.command("replay-data")
def replay_data(mock: bool = typer.Option(False, help="Use local MOCK runs (site development).")):
    """Build the control room's replay files in site/data/ from results/."""
    from icr.analysis import site_data

    typer.echo(site_data.build_all(mock=mock))


@app.command()
def site(port: int = 8765, mock: bool = typer.Option(False, help="Serve MOCK replay data.")):
    """Serve the control room on http://127.0.0.1:<port> (localhost only)."""
    from icr import siteserver

    siteserver.serve(port, mock=mock)


@app.command()
def version() -> None:
    """Print the package version."""
    from icr import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
