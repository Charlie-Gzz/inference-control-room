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
| M5 Optimizer and results pipeline | `icr results`, `icr calibrate`, `icr replay-data`, `icr charts` work on real sweep data |
| M6 Control room site | split view, control room, tour, what-if, autoscaling and method views written; only seen with mock data; record mode written; seen with mock and rehearsal data, what-if with real sweep data |
| M7 Assets and portfolio kit | charts, interactive page, diagram, screenshots, video capture and storyboards written (`icr assets`); tested on mock data only |
| M8 README and handoff | not started |

GPU spend so far: **$1.72 of $35** (actual, reconciled). See `docs/GPU_LEDGER.md`.

## Measured so far (real, one L4, chat workload unless noted)

Stage 1 after 3 sessions (capacity = highest ramp level within the SLO; levels are 2.6,
3.64, 4.42, 5.2, 5.98, 6.76 req/s):

| Config | Max req/s at SLO | $ per M output tokens | GSM8K |
|---|---|---|---|
| awq (baseline) | 5.98 | 0.525 | 92.4% |
| fp8 | 5.98 (tie) | 0.525 | 89.6% |
| awq-seqs32, awq-seqs64 | 5.20 | 0.675 | |
| awq-ngram (speculative) | 3.64 | 0.915 | acceptance 12.9% |
| bf16 | 2.60 | 1.349 | 90.8% |
| awq-nocache | fails every level | | |

- The binding limit is inter-token latency, not time to first token.
- Prefix caching off: misses the SLO even at 2.6 req/s. Speculative decoding (n-gram)
  lowers capacity under load. Unquantized weights cost more than half the capacity.
- Calibration: R_sat(chat) = 5.2 req/s (fine ramp). Coarse rag: 2 passes, 3 fails.
- Greedy outputs: baseline vs itself 92% identical, n-gram vs baseline 93%.
- Startup with warm JIT caches: 83 to 246 s. One replica plus the load generator uses
  about 0.5 to 0.8 CPU cores and 11 GiB while serving.
- L4 queue on Modal: anywhere from 0 to 25 minutes (unbilled).

## Exact next step

1. Session 4 (launched 16:21 EST, log `.scratch/sweep-6.log`): awq-draft and awq-suffix
   (ramp + greedy), then the fine rag ramp on awq. If it was cut short, repeat:
   `uv run modal run -m icr.modal_app.app::sweep --jobs "awq-draft=ramp:chat,greedy|awq-suffix=ramp:chat,greedy|awq=calib:rag@2;2.2;2.4;2.6;2.8;3"`
   After **each** session: commit results and ledger, then
   `uv run python -c "from icr import ledger; ledger.reconcile()"`.
   A config that fails to start three times is dropped (PLAN 1.7) and logged.
2. `uv run icr results`, read `results/RESULTS.md`. Pick 2 or 3 stage-2 combos, add them
   to `STAGE_2` in `src/icr/modal_app/configs.py`, log in DECISIONS, run them (ramp:chat).
3. Finalists on rag: `uv run icr calibrate`, then `ramp:rag` for the finalists.
4. Fleet config = cheapest config meeting the SLO on chat (ties: GSM8K, then baseline).
   `uv run icr calibrate --fleet-config <name>`. It needs fine ramps of that config on
   chat, rag and no-sharing. One task does coarse then fine:
   `--jobs "<name>=calib:no-sharing@0.5;1;1.5;2;3;4"` (and `calib:agentic@1;1.5;2;3;4;6`
   only if agentic will run).
5. M4, in priority order, one item per session (finished runs are skipped on rerun):
   `uv run modal run -m icr.modal_app.app::fleet --items proxycheck,chat` then `ramp`
   (needs two sessions), `rag`, `no-sharing`, `autoscale` (two sessions).
   About $4.09 per hour: estimated $17 of the $18 reserve. `agentic` only if at least
   $3 of the reserve is left afterwards.
   If `L4:4` is refused, set `GPU_L4_FLEET` to the `L4:2` fallback and say so on every chart.
6. M3b (H100) only after M4 and only if it fits: `--gpu h100`, calibrate first with
   `--jobs "awq=calib:chat@8;12;16;24;32;48" --gpu h100`, then `icr calibrate`.
7. `uv run icr assets --video` (results, charts, site data, storyboards, screenshots,
   videos). Look at every picture. Then README, DESIGN_FAQ, DEMO_SCRIPT, SLIDES_OUTLINE,
   PORTFOLIO_CARD, secret scan (gitleaks in Docker), HANDOFF.

## Rehearsed locally (free)

The whole M4 plan ran against mock replicas (32 runs, no errors), and the summary,
fleet charts, autoscaling view, method tables and all three storyboards were built from
it and looked at. Mock numbers are never published. The fleet code path is therefore
exercised, but **`L4:4` itself has not been requested yet**.

## Notes for restarts

- Run everything through `uv run`. Set `PYTHONIOENCODING=utf-8` for `modal run` on Windows.
- `modal run` sessions are started in the background and write to `.scratch/sweep-N.log`.
- Windows timers are coarse on Python 3.12. Use `icr.clock` for all timing.
- Site development: `uv run icr replay-data --mock` then `uv run icr site --mock`
  (mock data lives in `.scratch/`, is never committed, and the site shows a banner).
- Go: the pinned toolchain in `.tools/go` (1.27.4) is used. A system Go of the same
  version is also installed; the project does not depend on it.
- Docker Desktop is not needed until M7 (ffmpeg) and M8 (gitleaks).
