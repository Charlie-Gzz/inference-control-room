# Progress

Updated before every commit. On restart: read this, run `git status`, commit half-finished
work, run `uv run modal app list` and stop anything running.

## Status

**In progress (2026-11-14, evening): M4 fleet experiments.** M3a is done.

| Milestone | State |
|---|---|
| M0 Setup and smoke test | **done** |
| M1 Workloads, load generator, recorder, mock fleet | **done** |
| M2 Go router and autoscaler | **done** |
| M3a L4 single-replica sweeps and quality | **done** except one leftover ramp (`fp8` on rag, see next steps) |
| M4 Fleet experiments | **blocked on GPU capacity**: no 4-GPU machine yet; a 2-GPU pilot is queued (see below) |
| M3b H100 session (after M4, if budget allows) | not started; code ready (`--gpu h100`) |
| M5 Optimizer and results pipeline | works on real sweep data (`icr results`, `icr calibrate`, `icr charts`, `icr replay-data`) |
| M6 Control room site | every view written; seen with mock, rehearsal and real sweep data; needs real fleet runs |
| M7 Assets and portfolio kit | `icr assets [--video]` written and rehearsed on mock data; real assets not generated yet |
| M8 README and handoff | not started |

GPU spend so far: **$2.68 of $35** (all in the dev budget of $10; fleet $0 of $18; H100 $0 of $7).

## Measured so far (real, one L4)

Config sweep on chat (capacity = highest ramp level within the SLO; one level is about
15% and is the noise floor; levels are 2.6, 3.64, 4.42, 5.2, 5.98, 6.76 req/s):

| Config | Max req/s at SLO | $ per M output tokens | Notes |
|---|---|---|---|
| awq (baseline, **fleet config**) | 5.98 | 0.525 | GSM8K 92.4% |
| fp8 | 5.98 (tie) | 0.525 | GSM8K 89.6% |
| fp8-seqs256 (stage 2) | 5.98 (tie) | 0.525 | |
| awq-seqs256 (stage 2), awq-seqs32, awq-seqs64 | 5.20 | 0.675 | small batch limits fail on TTFT, not ITL |
| awq-suffix | 5.20 | 0.675 | engine crashed at the overload level |
| awq-ngram | 3.64 | 0.915 | 12.9% of draft tokens accepted |
| bf16 | 2.60 | 1.349 | GSM8K 90.8% |
| awq-nocache | fails every level | | |
| awq-draft | does not start | | vocabulary size mismatch with the 0.5B draft |

- Calibration of awq: R_sat chat 5.2, rag 2.0 (conservative), no-sharing 1.1 req/s.
- awq on rag (sweep levels 1.0 to 2.6 req/s): meets the SLO at every level.
- The binding limit is inter-token latency, not time to first token.

## State at the pause (2026-11-15, 12:00 EST): read this first

Paused for the usage limit. A wakeup at 15:15 EST runs `/autonomous-build` again.

- **`L4:4` has not been available.** Two requests waited in Modal's queue (over an hour
  on the evening of 2026-11-14, 80 minutes on the morning of 2026-11-15). No container
  ever started and nothing was billed. Both are in the ledger at $0 with notes.
- **A 2-GPU pilot is queued right now**: `fleet --items proxycheck,chat --max-runs 4
  --replicas 2`, launched 11:38 EST, log `.scratch/fleet-3.log`, app
  `ap-gB1sVwX5U6bYOhwBpWk5DD`. At 12:00 it was still waiting for GPUs. If it ran while
  nobody was watching, its runs are in `results/runs/fleetx2-*` and the ledger has a new
  row: **commit them first**, then `ledger.reconcile()`. If its log ends with an error
  (for example an expired login token) and there are no `fleetx2-*` runs, nothing ran:
  settle the ledger row to $0 with `ledger.settle(app_id, 0.0, note)` and launch again.
- Pilot runs are named `fleetx2-...` on purpose. `icr results` ignores them. To look at
  them: `icr.analysis.runs.all_runs("fleetx2-")` and `metrics.summarize`.

On restart, in this order:
1. `git status`, commit anything uncommitted (results and ledger first).
2. `uv run modal app list`. If the pilot app is still queued or running, let it finish.
   Stop anything else that is not expected (`modal app stop --yes <id>`).
3. Read the pilot: errors, CPU use (`container_resources` in meta.json, the fleet asked
   for 5 cores for 2 replicas), cache hit rate and latency per policy. Fix any bug it
   shows before spending on 4 GPUs.
4. Request `L4:4` again: `uv run modal run -m icr.modal_app.app::fleet --items proxycheck,chat`.
   Watch with `modal app list --json` (tasks goes from 0 to 1 when the container starts).
   Waiting is free. If 4 GPUs still cannot be had after a long wait, use the plan's
   fallback for the whole fleet plan: add `--replicas 2` to every fleet command, set the
   analysis to read `fleetx2-` runs (`_fleet_runs` in `src/icr/analysis/fleet_results.py`
   and `all_runs("fleet-")` in `site_data.py`, `results.py`, `story.py`), and change the
   fixed texts that say 4 GPUs (`site/index.html` meta tags, `assets/diagram.py`, README).

## Exact next step

1. M4 sessions, one item per `modal run` (finished runs are skipped on rerun, so a cut
   session is simply repeated). After **each** session: commit results and ledger, then
   `uv run python -c "from icr import ledger; ledger.reconcile()"`.
   - `uv run modal run -m icr.modal_app.app::fleet --items proxycheck,chat`  (running)
   - `--items ramp` (needs two sessions), `--items rag`, `--items no-sharing`,
     `--items autoscale` (two sessions)
   - `--items agentic` only if at least $3 of the $18 fleet reserve is left, and it needs
     `--jobs "awq=calib:agentic@1;1.5;2;3;4;6"` on one L4 and `icr calibrate` first.
   If `L4:4` never gets capacity, set `GPU_L4_FLEET` to the `L4:2` fallback
   (`config.GPU_L4_FLEET_FALLBACK`, `FLEET_REPLICAS = 2`) and say so on every chart.
2. Leftover dev run (any time, one L4): `uv run modal run -m icr.modal_app.app::sweep --jobs "fp8=ramp:rag"`.
3. M3b (H100) only after M4 and only if it fits: calibrate first with
   `--jobs "awq=calib:chat@8;12;16;24;32;48" --gpu h100`, `icr calibrate`, then
   `--jobs "awq=ramp:chat|fp8=ramp:chat|awq-ngram=ramp:chat|bf16=ramp:chat" --gpu h100`.
4. `uv run icr assets --video` (results, charts, site data, storyboards, screenshots,
   videos). Look at every picture. Then README, DESIGN_FAQ, DEMO_SCRIPT, SLIDES_OUTLINE,
   PORTFOLIO_CARD, secret scan (gitleaks in Docker, clean as of 16:32), HANDOFF.

## Rehearsed locally (free)

The whole M4 plan ran against mock replicas (32 runs, no errors), and the summary,
fleet charts, autoscaling view, method tables and all three storyboards were built from
it and looked at. Mock numbers are never published.

## Notes for restarts

- Run everything through `uv run`. Set `PYTHONIOENCODING=utf-8` for `modal run` on Windows.
- `modal run` sessions are started in the background and write to `.scratch/sweep-N.log`.
- Windows timers are coarse on Python 3.12. Use `icr.clock` for all timing.
- Site development: `uv run icr replay-data --mock` then `uv run icr site --mock`
  (mock data lives in `.scratch/`, is never committed, and the site shows a banner).
- Go: the pinned toolchain in `.tools/go` (1.27.4) is used. A system Go of the same
  version is also installed; the project does not depend on it.
- Docker Desktop is not needed until M7 (ffmpeg) and M8 (gitleaks).
