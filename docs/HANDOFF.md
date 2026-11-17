# Handoff

Final state, 2026-11-16, 21:20 EST. The build is closed. Some fleet runs were never made
because no 2-GPU container could be had (see "Not finished" and "Adding the missing
fleet runs later"). Nothing is running on Modal, and no project containers are left in
Docker. Docker Desktop was started by Claude and is still running: quit it if you do not
need it. The images `jrottenberg/ffmpeg:7.1-alpine` (153 MB) and
`ghcr.io/gitleaks/gitleaks:v8.30.1` (77 MB) are kept for rebuilding the videos and
repeating the secret scan.

## What was built

Switchyard: a small LLM serving fleet on vLLM, measured on real traffic patterns and
replayed in an interactive control room.

- **Go router** (`router/`): an OpenAI-style streaming proxy with round-robin,
  least-loaded and prefix-aware routing, its own metrics and a decision log.
- **Workloads and load** (`src/icr/workloads/`, `src/icr/loadgen/`): seeded chat, rag,
  agentic and no-sharing mixes, BurstGPT arrival times, an open-loop load generator and
  a recorder.
- **Autoscaler** (`src/icr/autoscale/`) and a **mock fleet** (`src/icr/mock/`) for free
  local development and tests.
- **Modal runs** (`src/icr/modal_app/`): smoke test, single-GPU config sweeps, quality
  checks, fleet sessions. `modal run` only, one container at a time.
- **Results pipeline** (`src/icr/analysis/`): every metric, the Pareto frontier and the
  cheapest config for a latency target, recomputed from saved runs with no GPU.
- **Control room** (`site/`): split view, single-router view, what-if explorer,
  autoscaling view, method page, request inspector, guided tour, record mode.
- **Assets** (`assets/`): 8 charts (PNG and SVG) and an interactive page, 7 screenshots,
  the architecture diagram, three videos and the README GIF.
- **Docs**: README, `DESIGN_FAQ.md` (15 questions), `DECISIONS.md`, `DEMO_SCRIPT.md`,
  `SLIDES_OUTLINE.md`, `PORTFOLIO_CARD.md`, `GPU_LEDGER.md`.

## How to run it

```bash
uv sync
uv run icr site      # control room on http://127.0.0.1:8765
uv run icr results   # recompute every number from results/runs/
```

- Checked on 2026-11-16 from a fresh clone: `uv sync`, `uv run icr results` (it
  reproduces the committed result files byte for byte) and the site server.
- `uv run icr test` and `uv run icr lint`: Python and Go tests, ruff and `go vet`.
- `uv run icr assets`: summaries, charts, site data, storyboards, screenshots, diagram.
  Add `--video` for the videos (about 25 minutes, needs Docker Desktop running).
- GPU runs: `uv run modal run -m icr.modal_app.app::fleet --items <item> --replicas 2`
  and `...::sweep --jobs "<config>=<tasks>"`. Finished runs are skipped on a rerun.

## Headline results

**On the same 2 GPUs and the same traffic, prefix-aware routing cut p95 time to first
token by 41% versus round-robin, and served 20% more traffic within the SLO, which is
14% lower cost per million tokens.**

| | round-robin | least-loaded | prefix-aware |
|---|---|---|---|
| p95 time to first token | 0.51 s | 0.59 s | 0.30 s |
| p95 inter-token latency | 69 ms | 67 ms | 43 ms |
| Prompt tokens from cache | 74% | 74% | 84% |
| Max traffic within the SLO | 7.8 req/s | 7.8 req/s | 9.36 req/s |
| $ per million output tokens at the SLO | 0.770 | 0.784 | 0.659 |

- Fleet: 2 NVIDIA L4, Qwen2.5-7B-Instruct AWQ, vLLM 0.33.0, chat workload. Medians of 3
  repeats (2 for capacity, 1 so far for least-loaded capacity).
- The capacity gap is one ramp level, which is the ramp's resolution. Both repeats agree.
- One L4: the baseline (4-bit AWQ, prefix caching on) was the cheapest config that
  meets the SLO: 5.98 req/s, $0.525 per million output tokens. FP8 tied. Prefix caching
  off missed the SLO at every level. Speculative decoding lowered capacity. bf16 reached
  2.6 req/s.
- One H100: AWQ, FP8, bf16 and AWQ with n-gram speculation all reached 54.4 req/s,
  $0.242 per million output tokens. Nine times the traffic of one L4 for 4.1 times the
  hourly price. Quantization made no difference there. What set the limit (the GPU or
  vLLM's CPU-side work) is not shown by the runs.
- Full tables: `results/RESULTS.md`.

## Where the assets are

| What | Where |
|---|---|
| Charts (PNG 1600 px and SVG) | `assets/charts/` |
| Interactive chart page | `assets/charts/interactive.html` |
| Screenshots of every view | `assets/screenshots/` |
| Architecture diagram | `assets/diagrams/architecture.svg` and `.png` |
| Main video (85 s), loop (20 s), vertical cut | `assets/video/switchyard.mp4`, `switchyard-loop.mp4`, `switchyard-vertical.mp4` |
| README GIF | `assets/video/hero.gif` |
| Full-quality video masters (not committed) | `assets/video/masters/`, rebuilt by `uv run icr assets --video` |
| Link preview image (1200x630) | `site/assets/og.png` |
| Logo and favicon | `site/assets/logo.svg` |

## Questions for you

Details are in `docs/QUESTIONS_FOR_CHARLIE.md`. One line each is enough.

Answered on 2026-11-16:

1. **Try 4 GPUs again on another day?** Charlie: "Yeah, lets publish with 2-GPU." The
   2-GPU results are the published headline.
2. **GitHub description.** Charlie: "Yes change it pls." Set to "A small LLM serving
   fleet on vLLM with prefix-cache-aware routing, autoscaling, quantization and
   speculative decoding, measured on real traffic patterns and replayed in an
   interactive control room.", with the plan's 15 topics.
3. **H100 session (up to $7).** Charlie: "Go for it." Done on 2026-11-16 for $4.06.

4. **Wait for the missing fleet runs before going public?** Charlie deferred to Claude.
   Decided: do not wait. The headline does not depend on the missing runs, and the
   README and the site say what was not run. One 2-GPU request was still in the queue
   when this was decided. Whatever it returned is in the repo, and the build made no
   request after it.

Nothing is open. One thing to think about: if you want the no-sharing control and the
autoscaling view filled in before you announce the project, see the next section.

## Adding the missing fleet runs later

No Claude needed. Each command is safe to repeat: finished runs are skipped, the budget
guard refuses anything that could pass $35, and queue time is not billed.

```powershell
$env:PYTHONIOENCODING = "utf-8"
uv run modal app list     # nothing should be running
uv run modal run -m icr.modal_app.app::fleet --items ramp,rag,no-sharing,autoscale --replicas 2
```

- Repeat it until the last lines say `skipped: []`. A session is at most 60 minutes and
  costs about $2. The whole remaining list is about $5.
- If it sits in the queue for more than two hours, stop it with Ctrl+C and try at
  another hour. Then set the ledger row to $0:
  `uv run python -c "from icr import ledger; ledger.settle('<app id from the log>', 0.0, 'never ran')"`
- After each session: `git add -A`, commit, then
  `uv run python -c "from icr import ledger; ledger.reconcile()"`.
- When all runs are in: `uv run icr assets`, look at `assets/charts/latency_by_policy.png`,
  `cache_hit_by_policy.png` and `autoscaling.png`, and open the site's Autoscaling and
  Method views. Then remove the "Fleet runs still missing" bullet from the README and
  add the new tables from `results/RESULTS.md`.

## Not finished, skipped or changed, and why

- **4 GPUs.** Never available (five requests, three days, unbilled). The fleet ran on 2
  GPUs, the plan's fallback. Every chart, the site, the videos and the README say 2 GPUs.
- **Fleet runs never made:** rag, the no-sharing control, autoscaling, the agentic
  workload, and one of six capacity ramp runs (least-loaded, second repeat). On
  2026-11-16 four requests for a 2-GPU container waited up to two hours each without
  starting, the last one from 17:20 to 19:20 EST. All unbilled. The autoscaling view
  says "Not run yet" and its chart does not exist. See "Adding the missing fleet runs
  later".
- **Videos** were built from the 2-GPU chat runs and are final for this data
  (`assets/video/`). They do not need a rebuild if the missing runs are added, unless
  the headline numbers change.
- **Budget raise taken back.** You raised the budget by $17 for a 4-GPU rerun on
  2026-11-15. None of it was spent. The caps in `src/icr/config.py` are at the plan's
  values again.
- **H100 session (M3b).** Done on 2026-11-16: three calibration ramps and four configs,
  $4.06 of its $7. It ran before the remaining fleet runs, not after them as the plan
  orders, because no 2-GPU container could be had (`docs/DECISIONS.md`). GSM8K and the
  greedy-output check were not rerun on the H100.
- **GitHub description.** Changed from the plan's "A 4-GPU LLM serving fleet ..." to
  "A small LLM serving fleet ...". `PLAN.md` keeps the original text.
- **Draft-model speculative decoding.** Impossible with official Qwen2.5 models
  (vocabulary size mismatch). N-gram and suffix decoding were measured.
- **Stretch items** (a router that reads real cache state, Bulwark in front). Not started.
- **Nothing is faked.** Mock-fleet numbers are never published. The site shows a banner
  when it serves mock data, and no mock data is committed.

## Spend

- Total: **$10.11** of the plan's $35 (development $2.84 of $10, fleet $3.21 of $18,
  H100 $4.06 of $7). No cap was hit.
- Every run, including the requests that never started ($0), is in `docs/GPU_LEDGER.md`.
  Actual costs come from `modal billing report`.

## Security

- Secret scan (gitleaks v8.30.1 in Docker, full history): **no leaks found** on
  2026-11-16, 92 commits. Repeat it right before going public:
  `docker run --rm -v "${PWD}:/repo" ghcr.io/gitleaks/gitleaks:v8.30.1 git /repo --redact`
- No API keys are used. No `.env` exists. The Modal token was never printed or committed.
- The repo is private. GitHub Pages is prepared (`.github/workflows/pages.yml`) and not
  enabled.
- Nothing from an employer: public models, data and traces only (`THIRD_PARTY.md`).

## Pre-public checklist

1. Read README and this file. Answer the questions above.
2. Check `docs/GPU_LEDGER.md` against Modal's Usage page.
3. Skim the screenshots and videos for anything personal.
4. Confirm the secret scan was clean and nothing from your employer appears.
5. Read `docs/DESIGN_FAQ.md` end to end, so every design choice can be explained in an
   interview.
6. Make the repo public, then enable GitHub Pages.
7. Upload `site/assets/og.png` as the repo's social preview (repo Settings, General,
   Social preview). This cannot be done from the command line.
8. Pin the repo on your profile and add it to the portfolio site.
