# Handoff

State on 2026-11-16, 17:45 EST. The build is finished except for the fleet runs that are
still waiting for a 2-GPU container (see "Not finished"). `docs/PROGRESS.md` has the
exact next step if the build is resumed.

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
3. **H100 session (up to $7).** Charlie: "Go for it." Done on 2026-11-16 for $3.97.

Still open:

4. **Wait for the missing fleet runs before going public?** Nothing is wrong with
   publishing first and updating later: the headline does not depend on the missing
   runs, and the README and the site say what has not been run. The only cost is first
   impressions. Recommendation: make the repo public whenever you like, and hold the
   announcement (LinkedIn post, portfolio pin) until the missing runs are in or you
   decide to go without them. Meanwhile: the build keeps requesting 2-GPU containers.

## Not finished, skipped or changed, and why

- **4 GPUs.** Never available (five requests, three days, unbilled). The fleet ran on 2
  GPUs, the plan's fallback. Every chart, the site, the videos and the README say 2 GPUs.
- **Fleet runs still missing:** rag, the no-sharing control, autoscaling, the agentic
  workload, and one of six capacity ramp runs (least-loaded, second repeat). On
  2026-11-16 a 2-GPU request waited two hours without a container. The autoscaling view
  and chart stay empty until those runs exist. Commands, in order:
  `--items ramp`, `rag`, `no-sharing`, `autoscale` (each with `--replicas 2`).
- **Budget raise taken back.** You raised the budget by $17 for a 4-GPU rerun on
  2026-11-15. None of it was spent. The caps in `src/icr/config.py` are at the plan's
  values again.
- **H100 session (M3b).** Done on 2026-11-16: three calibration ramps and four configs,
  $3.97 of its $7. It ran before the remaining fleet runs, not after them as the plan
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

- Total: **$10.02** of the plan's $35 (development $2.83 of $10, fleet $3.21 of $18,
  H100 $3.97 of $7). No cap was hit.
- Every run, including the requests that never started ($0), is in `docs/GPU_LEDGER.md`.
  Actual costs come from `modal billing report`.

## Security

- Secret scan (gitleaks in Docker, full history): clean on 2026-11-16, 65 commits.
  Repeat it right before going public:
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
