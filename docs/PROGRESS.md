# Progress

Updated before every commit. On restart: read this, run `git status`, commit half-finished
work, run `uv run modal app list` and stop anything running.

## Status

**In progress (2026-11-14): M3a stage-1 sweep.** Site (M6) and results pipeline (M5) are
being built in parallel against mock data while GPU sessions run.

| Milestone | State |
|---|---|
| M0 Setup and smoke test | **done** |
| M1 Workloads, load generator, recorder, mock fleet | **done** |
| M2 Go router and autoscaler | **done** (mock check: prefix-aware 78% cache hits vs 64% on chat, no gain on no-sharing; mock only) |
| M3a L4 single-replica sweeps and quality | **in progress**: calibration done, stage 1 running |
| M4 Fleet experiments | code written and dry-run against mock replicas (`tests/test_fleet_session.py`); **not yet run on GPUs** |
| M3b H100 session (after M4, if budget allows) | not started (needs an `h100` sweep function and label) |
| M5 Optimizer and results pipeline | `icr results`, `icr calibrate`, `icr replay-data` work; charts not written |
| M6 Control room site | split view, control room, tour, what-if, autoscaling and method views written; only seen with mock data; record mode not written |
| M7 Assets and portfolio kit | chart theme only |
| M8 README and handoff | not started |

GPU spend so far: **$0.55 of $35** (actual, reconciled). See `docs/GPU_LEDGER.md`.

## Measured so far (real, one L4, baseline AWQ)

- Coarse chat ramp: meets the SLO up to 4 req/s, misses at 6 (ITL p95 108 ms).
- Fine chat ramp: **R_sat(chat) = 5.2 req/s** (5.6 misses with ITL p95 100.2 ms).
- The binding limit is inter-token latency, not time to first token.
- Coarse rag ramp: meets the SLO at 2 req/s, misses at 3. Fine ramp still to run.
- GSM8K (250 questions): 92.4%. Greedy outputs, same server twice: 92% identical.
- Startup with warm JIT caches: 154 to 177 s. One replica plus the load generator uses
  about 0.5 CPU cores and 11 GiB while serving.
- L4 capacity on Modal is slow to arrive: 15 to 20 minutes of (unbilled) queue per session.

## Exact next step

1. Stage 1 is driven by one repeatable command. Finished tasks are skipped and tasks
   that do not fit a session's time are left for the next call:
   `uv run modal run -m icr.modal_app.app::sweep --jobs stage1 --purpose "M3a stage 1 sweep, session N"`
   Repeat until the output says `skipped: []`. After **each** session: commit results and
   ledger, then `uv run python -c "from icr import ledger; ledger.reconcile()"`.
   A config that fails to start three times is dropped (PLAN 1.7) and logged.
2. `uv run icr results` and look at `results/RESULTS.md`. Pick 2 or 3 stage-2 combos of the
   winners, add them to `STAGE_2` in `src/icr/modal_app/configs.py`, log in DECISIONS, run.
3. Finalists on rag: first `ramp:rag@2.0;2.2;2.4;2.6;2.8;3.0=fine` on `awq`, then
   `icr calibrate`, then `ramp:rag` for the finalists.
4. Fleet config = cheapest config meeting the SLO on chat. `uv run icr calibrate --fleet-config <name>`.
   It needs fine ramps of that config on chat, rag and no-sharing (coarse first where
   missing; `icr calibrate` prints the fine levels).
5. M4, in priority order, one item per session (finished runs are skipped on rerun):
   `uv run modal run -m icr.modal_app.app::fleet --items proxycheck,chat` then `ramp`,
   `rag`, `no-sharing`, `autoscale`. Estimated $16.5 of the $18 reserve at $3.96/hour.
   `agentic` only if at least $3 of the reserve is left afterwards.
   If `L4:4` is refused, set `GPU_L4_FLEET` to the `L4:2` fallback and say so on every chart.
6. M3b (H100) only after M4 and only if it fits the budget.
7. Then: `icr results`, `icr replay-data`, look at every site view with real data,
   charts, record mode and video, README, DESIGN_FAQ, HANDOFF.

## Notes for restarts

- Run everything through `uv run`. Set `PYTHONIOENCODING=utf-8` for `modal run` on Windows.
- `modal run` sessions are started in the background and write to `.scratch/sweep-N.log`.
- Windows timers are coarse on Python 3.12. Use `icr.clock` for all timing.
- Site development: `uv run icr replay-data --mock` then `uv run icr site --mock`
  (mock data lives in `.scratch/`, is never committed, and the site shows a banner).
- Go: the pinned toolchain in `.tools/go` (1.27.4) is used. A system Go of the same
  version is also installed; the project does not depend on it.
- Docker Desktop is not needed until M7 (ffmpeg) and M8 (gitleaks).
