# Progress

Updated before every commit. On restart: read this, run `git status`, commit half-finished
work, run `uv run modal app list` and stop anything running.

## Status

**Resumed 2026-11-16, 10:40 EST, in the middle of M4 (fleet experiments).** M3a is done.
Read "Resumed 2026-11-16" below before anything else.

| Milestone | State |
|---|---|
| M0 Setup and smoke test | **done** |
| M1 Workloads, load generator, recorder, mock fleet | **done** |
| M2 Go router and autoscaler | **done** |
| M3a L4 single-replica sweeps and quality | **done** (the leftover `fp8` on rag ramp ran on 2026-11-16) |
| M4 Fleet experiments | **in progress on 2 GPUs** (fallback): chat done, capacity ramp 5 of 6 runs. A 4-GPU rerun is approved (see below) |
| M3b H100 session (after M4, if budget allows) | not started; code ready (`--gpu h100`) |
| M5 Optimizer and results pipeline | works on real sweep data (`icr results`, `icr calibrate`, `icr charts`, `icr replay-data`) |
| M6 Control room site | every view works on the real 2-GPU runs, screenshots looked at. The autoscaling view is empty until those runs exist |
| M7 Assets and portfolio kit | charts, screenshots, diagram, three videos and the GIF built from the real 2-GPU data and looked at; demo script, slides outline and portfolio card drafted. All to be refreshed when the fleet data is final |
| M8 README and handoff | README drafted; DESIGN_FAQ written; secret scan rehearsed (clean); HANDOFF not written yet |

GPU spend so far: **$6.04** (dev $2.83 of $10; fleet $3.21; H100 $0 of $7). Caps: $35 total and $18 fleet in the plan, raised by Charlie on 2026-11-15 to $52 and $35 (see below).

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

## Resumed 2026-11-16: read this first

- Budget constants are raised in `src/icr/config.py` (total 52, soft stop 45, fleet 35)
  and the ledger tests follow the constants. Committed.
- **Fourth `L4:4` try: no container after 60 minutes (11:00 to 12:00 EST), cancelled by
  the watchdog, nothing billed, ledger row settled to $0.** Next `L4:4` try: later on
  2026-11-16, between two 2-GPU sessions (afternoon or evening, a different hour from
  the four tries so far: 20:51, 10:17, 15:16 and 11:00 EST). Same command as below with
  a new log number.
- **The 2-GPU request below never started either:** 120 minutes in the queue (12:01 to
  14:01 EST), cancelled by the watchdog, nothing billed, ledger row settled to $0. So on
  2026-11-16 neither `L4:4` (60 min) nor `L4:2` (120 min) could be had by 14:00 EST.
- **14:31 EST: the single-L4 run got a container (about 20 minutes in the queue) and
  finished.** `fp8` on rag meets the SLO at every level, like `awq`. M3a is complete.
  Reconciled: $0.145. Total spend $6.04 (dev $2.83, fleet $3.21).
- **15:32 EST: the fifth `L4:4` request was cancelled after 60 minutes, unbilled. The
  4-GPU rerun is closed for this build:** the 2-GPU results are the headline, the budget
  constants are back at the plan's values (35 / 28 / 18), `docs/DECISIONS.md` and
  `docs/QUESTIONS_FOR_CHARLIE.md` (Q1 outcome, Q2 open) record it. Do not request
  `L4:4` again unless Charlie asks.
- **15:35 EST: 2-GPU request queued** (`--items ramp --replicas 2`, log
  `.scratch/fleet-11.log`, watchdog 120 minutes). If it runs: commit results and ledger,
  reconcile, `icr results`, then `--items rag --replicas 2`, `no-sharing`, `autoscale`,
  each with the watchdog. If it is cancelled: settle the row to $0 and run the H100
  session instead (M3b, its own $7 budget, one GPU): first
  `sweep --jobs "awq=calib:chat@8;12;16;24;32;48" --gpu h100`, then `icr calibrate`,
  then `--jobs "awq=ramp:chat|fp8=ramp:chat|awq-ngram=ramp:chat|bf16=ramp:chat" --gpu
  h100` (repeat until `skipped: []`), each with a 45-minute watchdog. Checked on
  2026-11-16: `icr calibrate` reproduces the frozen L4 values byte for byte and only
  adds `baseline_r_sat_h100`, so it is safe to rerun. Then finish the project on
  the data that exists (refresh the docs, final secret scan with the pinned image,
  Docker cleanup).
- `docs/HANDOFF.md` is drafted (state of 15:45 EST). Refresh its numbers, the "Not
  finished" list and the date at the end.
- Earlier, 14:36 EST: fifth `L4:4` request queued (`--items proxycheck,chat --replicas 4`,
  log `.scratch/fleet-10.log`, watchdog 60 minutes). If it is cancelled: settle the
  ledger row to $0, then `--items ramp --replicas 2` with a 120-minute watchdog, then
  `rag`, `no-sharing`, `autoscale` on 2 GPUs. If the 2-GPU request also times out again,
  stop GPU work for the day, finish the handoff on what exists, and tell Charlie.
- Earlier (14:03 EST): a capacity probe that is also useful work. The leftover dev run
  on one L4: `uv run modal run -m icr.modal_app.app::sweep --jobs "fp8=ramp:rag"`, log
  `.scratch/sweep-9.log`, watchdog at 45 minutes. If it runs: commit results and ledger,
  `ledger.reconcile()`, `icr results`. Then try `L4:4` once more (60 min), then the
  2-GPU list (`--items ramp --replicas 2`, then `rag`, `no-sharing`, `autoscale`).
  If even one L4 cannot be had, GPU work stops for the day: write the handoff on what
  exists and tell Charlie.
- Earlier (cancelled): the 2-GPU list. Launched 12:02 EST: `--items ramp --replicas 2` (the
  one skipped run), log `.scratch/fleet-9.log`, watchdog at 120 minutes. After it:
  commit results and ledger, `ledger.reconcile()`, `icr results`, then `--items rag
  --replicas 2`, `no-sharing`, `autoscale`, one session at a time.
- Earlier today, the 4-GPU request went into the queue at 11:00 EST (fourth try):
  `uv run modal run -m icr.modal_app.app::fleet --items proxycheck,chat --replicas 4`,
  log `.scratch/fleet-8.log`, with the queue watchdog below at 60 minutes. Claude Code's
  permission check had refused the first launch (spend above the plan's written cap).
  Charlie confirmed in the session ("go 4 GPUs", 2026-11-16, about 10:58 EST).
  `FLEET_REPLICAS` stays 2 in config until 4-GPU runs exist (the analysis reads it);
  the launch passes `--replicas 4`. When the first 4-GPU runs land: set
  `FLEET_REPLICAS = 4`, check how the analysis keeps the `fleetx2-` runs as a second
  data set, then continue the 4-GPU list (`ramp`, `rag`, `no-sharing`, `autoscale`).
- If the watchdog cancels it (log ends with an error, no new runs): settle the ledger row
  to $0, then run the 2-GPU list (`--items ramp --replicas 2` for the one skipped run,
  then `rag`, `no-sharing`, `autoscale`) and try `L4:4` again at another hour.
- A 2-GPU request for the skipped ramp run (10:44 EST) was cancelled after 16 minutes in
  the queue to free the slot for the 4-GPU request. Ledger row settled to $0.
- `.scratch/queue_watchdog.ps1 -Log <log> -Minutes <n>` stops a request that is still
  in the queue after n minutes (unbilled). Start it in the background next to each launch.
- **Drafted on the 2-GPU numbers as of 2026-11-16 (free work while the queue waits):**
  `README.md`, `docs/DEMO_SCRIPT.md`, `docs/SLIDES_OUTLINE.md`, `docs/PORTFOLIO_CARD.md`.
  They quote the headline (41%, 20%, 14%), the per-policy table, "2 GPUs", the spend
  ($5.88, 17 runs) and "rag, no-sharing, autoscaling not run yet" by omission. **Refresh
  all four when the fleet data changes** (new runs, or 4 GPUs becoming the headline),
  and add the rag, no-sharing and autoscaling results and charts to the README then.
  The README hero is `assets/screenshots/hero.png` until the GIF exists.
- `icr assets` (no video) was rerun on the current data: capacity chart is new, charts
  and the interactive page are now byte-stable between runs, storyboards carry all
  three headline numbers. Every screenshot was looked at.
- **Two fleet sizes in the results:** `icr results` now writes a `second_fleet` block
  (the size that is not `FLEET_REPLICAS`) into the summary and a "Second data set"
  section into `results/RESULTS.md`, when such runs exist. Still to do once 4-GPU runs
  exist: show the second data set on the site's Method page and in the README, and
  decide on a chart of the routing effect by fleet size. The site's replay views and
  `icr replay-data` cover the headline fleet only.
- Docker Desktop was started by Claude at 12:00 EST on 2026-11-16 (it was not running).
  Leave it running until the final video build and secret scan, then stop the
  project's containers (label `project=inference-control-room`).
- Secret scan rehearsal, 2026-11-16 12:01 EST: gitleaks over the full history, 65
  commits, no leaks. Repeat it with the pinned image
  (`ghcr.io/gitleaks/gitleaks:v8.30.1`) right before the handoff.
- **Videos on real data (2026-11-16):** the first full build worked (main 8.3 MB, loop
  2.5 MB, vertical 7.5 MB, `hero.gif` 5.1 MB). Frames were looked at and three layout
  defects fixed in `site/css/site.css` (record mode only): the footer was cut off in the
  single-router scenes, the vertical single-router scenes left half the frame empty, and
  the rewind badge sat on the panel border. A second build with the fixes started at
  12:40 EST (`video.make_all()` only, log `.scratch/video2.log`). When it ends: look at
  frames 1900, 2178 and 3100 of `story-main` and `story-vertical` in
  `assets/video/frames/`, play nothing else, then commit `assets/video/*.mp4` and
  `hero.gif`. `.scratch/frames.py <story> <frame...>` captures single frames in seconds.
  The videos must be rebuilt once more when the fleet data is final.
- The second build stopped after the main story: the capture server never closed its
  socket, so the next story's server on the same port timed out (Windows). Fixed with
  `siteserver.stop` and `tests/test_siteserver.py`.
- **Videos committed at 13:10 EST on the 2-GPU data:** `switchyard.mp4` 8.3 MB,
  `switchyard-loop.mp4` 2.5 MB, `switchyard-vertical.mp4` 7.9 MB, `hero.gif` 5.1 MB.
  Frames of every scene were looked at in both formats after the fixes (a fourth fix:
  the vertical what-if scene now stacks the chart above the panels). Rebuild all of
  them with `uv run icr assets --video` (about 25 minutes) when the fleet data is final.
- The README hero is now `assets/video/hero.gif`.

## Paused for the night (2026-11-15, 22:15 EST)

Charlie is turning the PC off for the night. Work resumes on 2026-11-16.

**State at the pause: nothing is running on Modal and everything is committed.** The
2-GPU capacity ramp session (app `ap-TqLsegvuuS7Fkl305hIZGs`) ended at 22:40 EST after
44 minutes on the GPUs ($1.53). It finished 5 of 6 runs with no errors. The time guard
skipped `fleetx2-ramp-chat-least-loaded-s1`; rerun `--items ramp` to get it (about 12
minutes, $0.45).

Capacity at the SLO on 2 GPUs (levels 6.24, 7.8, 9.36, 10.92, 12.48, 14.04 req/s):
round-robin 7.80 and 7.80 req/s, least-loaded 7.80 (one repeat so far), prefix-aware
9.36 and 9.36. That is one level (20%) more traffic within the SLO and 14% lower cost
per million output tokens ($0.659 against $0.770). One level is the stated noise floor
for a single ramp, so say that the gap is one level and that both repeats agree.

**On resume, first:** `uv run modal app list` (expect nothing running), `git status`.

**Decision from Charlie (2026-11-15, 22:05 EST): retry the fleet on 4 GPUs.** In Charlie's words:
"I say we go for it, I still have credits available if not, I can put $17 more for sure."
See `docs/QUESTIONS_FOR_CHARLIE.md` Q1 and `docs/DECISIONS.md`. My reading of it:

- The full fleet plan is rerun on `L4:4` (about $17), on top of the 2-GPU results.
- The budget rises by up to $17 for this: **total hard stop $52, fleet reserve $35**
  (dev $10 and H100 $7 unchanged). `BUDGET_TOTAL`, `BUDGET_SOFT_STOP` and
  `BUDGET_BY_CATEGORY` in `src/icr/config.py` still hold the old values. Change them
  first thing (total 52, soft stop 45, fleet 35) and fix any test that pins them.
- Charlie handles the Modal side (credits, workspace spend limit). Never change billing
  or account settings from here. On any quota or spend-limit error: stop and ask.

**Order for 2026-11-16:**

1. Change the budget constants (see above).
2. Ask for `L4:4` in the morning, when queues may be shorter: set `FLEET_REPLICAS = 4`,
   run `--items proxycheck,chat`. Give it at most 60 minutes in the queue per try
   (unbilled). If it starts, run the whole 4-GPU list (`proxycheck,chat`, `ramp`, `rag`,
   `no-sharing`, `autoscale`). The 4-GPU runs become the headline; the 2-GPU runs stay
   as a second data set (`fleetx2-...`).
3. While `L4:4` cannot be had, set `FLEET_REPLICAS = 2` and keep going with the 2-GPU
   list (`ramp` for the one skipped run, `rag`, `no-sharing`, `autoscale`), then try `L4:4` again at another hour.
   One container at a time, so the two never queue together.
4. Do not poll the queue in a loop (it burns Claude usage). Launch in the background,
   update this file, end the turn. The finished task wakes the session.

## State of the fleet work (2026-11-15)

- **The fleet runs on 2 L4s (`L4:2`), the plan's fallback.** Three requests for `L4:4`
  waited 50 to 80 minutes each and never got a container (all in the ledger at $0).
  `FLEET_REPLICAS = 2` in `src/icr/config.py` is the single switch. Run ids are
  `fleetx2-...`. The fleet commands need no extra flag.
- **Done on 2 GPUs:** the router check and chat (3 policies x 3 repeats). Median p95 time
  to first token: round-robin 0.51 s, least-loaded 0.59 s, prefix-aware 0.30 s. p95
  inter-token latency 69, 67, 43 ms. Cache hit rate 74%, 74%, 84%. No errors.
- **Capacity ramp:** see the pause notes above. `L4:2` queues were long on 2026-11-15
  (25 minutes to 2 hours, unbilled).
  A session that ends shows `App completed` in its log and its runs appear in
  `results/runs/fleetx2-*`. **Commit results and ledger first, then reconcile.**
- If a log ends with an error and no new runs exist, nothing ran: settle the ledger row
  to $0 with `ledger.settle(app_id, 0.0, note)` and launch again.
- `icr assets` (no video) already runs end to end on the real data: results, charts,
  site data, storyboards, screenshots, diagram.

Remaining fleet sessions, in order (each is one command, finished runs are skipped):
`--items ramp` (repeat until `skipped: []`), `--items rag`, `--items no-sharing`,
`--items autoscale` (repeat until `skipped: []`), then `agentic` if the reserve allows
(it needs `sweep --jobs "awq=calib:agentic@1;1.5;2;3;4;6"` and `icr calibrate` first).

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
