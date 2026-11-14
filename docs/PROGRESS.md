# Progress

Updated before every commit. On restart: read this, run `git status`, commit half-finished
work, run `uv run modal app list` and stop anything running.

## Status

**Current milestone: M0 (setup and smoke test).**

| Milestone | State |
|---|---|
| M0 Setup and smoke test | in progress |
| M1 Workloads, load generator, recorder, mock fleet | not started |
| M2 Go router and autoscaler | not started |
| M3a L4 single-replica sweeps and quality | not started |
| M4 Fleet experiments | not started |
| M3b H100 session (after M4, if budget allows) | not started |
| M5 Optimizer and results pipeline | not started |
| M6 Control room site | not started |
| M7 Assets and portfolio kit | not started |
| M8 README and handoff | not started |

## Done

- Environment checked: git, gh (workflow scope), uv + Python 3.12, Modal profile, no stray apps,
  no `ANTHROPIC_API_KEY`. Docker Desktop was not running, so it was started.
- Go 1.27.4 in `.tools/go` (checksum verified).
- Skeleton: `pyproject.toml`, `icr` CLI (`test`, `lint`, `version`), config, ledger with budget guard.
- Modal app: CPU download function, L4 smoke test function.

## Exact next step

1. `uv run modal run -m icr.modal_app.app::download` (CPU only), check the Volume.
2. `uv run modal run -m icr.modal_app.app::smoke` (one L4), commit results and ledger.
3. Create the private GitHub repo and push. Then M1.

## Notes for restarts

- Run everything through `uv run`. Set `PYTHONIOENCODING=utf-8` for `modal run` on Windows.
- GPU spend so far: see `docs/GPU_LEDGER.md`.
