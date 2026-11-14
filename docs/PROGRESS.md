# Progress

Updated before every commit. On restart: read this, run `git status`, commit half-finished
work, run `uv run modal app list` and stop anything running.

## Status

**Resumed 2026-11-14.** M2 closed. M3a in progress: the calibration ramp was launched
(`.scratch/sweep-calib.log`) and waited several minutes for an L4.

| Milestone | State |
|---|---|
| M0 Setup and smoke test | **done** |
| M1 Workloads, load generator, recorder, mock fleet | **done** (tests pass) |
| M2 Go router and autoscaler | **done** (mock check at 8 rps: prefix-aware 78% cache hits vs 64% on chat, 0% and no gain on no-sharing; mock only) |
| M3a L4 single-replica sweeps and quality | **in progress**: calibration ramp running |
| M4 Fleet experiments | code written (`modal_app/fleet.py`, `fleet/plan.py`, `fleet` entry point), **never run** |
| M3b H100 session (after M4, if budget allows) | not started |
| M5 Optimizer and results pipeline | `analysis/runs.py`, `optimizer.py`, `sweeps.py`, `replay.py` written with tests; `icr results` and `icr replay-data` commands not wired yet |
| M6 Control room site | not started |
| M7 Assets and portfolio kit | not started |
| M8 README and handoff | not started |

GPU spend so far: **$0.14 of $35** (actual, from Modal's billing report). See `docs/GPU_LEDGER.md`.

## Done

- **M0.** Environment checked. Go 1.27.4 in `.tools/go` (checksum verified). Private repo
  created and pushed. Models (bf16, AWQ, 0.5B draft), BurstGPT and a 250-question GSM8K
  subset are in the Modal Volume `inference-control-room`. Smoke test passed on one L4.
- **Smoke test findings** (`results/runs/smoke-20261114-012022/`):
  - AWQ loads in vLLM 0.33.0 with no `--quantization` flag.
  - `usage.prompt_tokens_details.cached_tokens` works with `--enable-prompt-tokens-details`.
  - `/reset_prefix_cache` works with `VLLM_SERVER_DEV_MODE=1`.
  - KV cache: 240,768 tokens. Prefill: 2,164 uncached tokens in 0.74 s, 0.05 s when cached.
    Single-stream decode: about 19 ms per token.
  - First startup took 270 s (120 s of it FlashInfer JIT). Caches now go to the Volume.
  - vLLM defaults: `max_num_seqs` 128, `max_num_batched_tokens` 2048.
- **M1.** Workload generator (chat, rag, agentic, no-sharing), BurstGPT segments and
  rescaling, open-loop load generator, recorder, mock fleet. Tests cover determinism,
  open-loop timing, recorder fields and the mock prefix cache.
- **M2.** Go router (round-robin, least-loaded, prefix-aware), admin endpoints, metrics,
  decision log, shared JSON vectors used by Go and Python tests. Autoscaler with tests.
- Benchmark method frozen in `docs/DECISIONS.md` before any ramp or fleet result.
- Ledger reconciles against `modal billing report` (`icr.ledger.reconcile`).
- `uv run icr test` (73 Python tests + Go) and `uv run icr lint` pass.

## Not verified yet (be careful)

- The container CPU/RAM sampler returned no samples in the smoke test (no cgroup files in
  Modal's sandbox). A psutil fallback is written but **has not run on Modal yet**. Fleet
  container sizing depends on it.
- The JIT cache env vars (`FLASHINFER_WORKSPACE_BASE`, `TRITON_CACHE_DIR`) are set but the
  faster second startup **has not been measured yet**.
- `src/icr/modal_app/sweep.py`, `configs.py` and the `sweep` entry point are written but
  **have never run**. Expect a first-run bug or two.
- The mock comparison (`icr mock-run`) at 30 rps overloaded the mock (p95 TTFT about 20 s
  for every policy), so it says little. Rerun at a lower rate.
- `icr mock-run` took more than 6 minutes for two workloads on this machine. Check why
  (probably the overload plus the 120 s request timeout) before relying on it.

## Exact next step

1. `git status`, then `uv run modal app list` (expect nothing running).
2. `uv run icr mock-run --workload chat --rate 8 --duration 30` and the same for
   `no-sharing`. Expect prefix-aware to have the higher cache hit rate on chat and no gain
   on no-sharing. This closes M2. Mock numbers are never published.
3. `uv run icr build-router --linux` (the image picks up `router/bin/switchyard-router`).
4. M3a calibration, one L4 session:
   `uv run modal run -m icr.modal_app.app::sweep --configs awq --tasks ramp:chat --rates 1,2,3,4,6,8 --purpose "M3a calibration ramp"`
   Check startup time (JIT cache), the resource sampler output, and R_sat.
5. Then the stage-1 sweep in sessions of 3 configs (30-minute timeout each), levels
   0.5, 0.7, 0.85, 1.0, 1.15, 1.3 x R_sat, plus `gsm8k` for awq / fp8 / bf16 and `greedy`
   for awq and the speculative configs.
6. After every GPU run: commit results and ledger first, then `ledger.reconcile()`.

## Notes for restarts

- Run everything through `uv run`. Set `PYTHONIOENCODING=utf-8` for `modal run` on Windows.
- L4 capacity can take minutes to arrive (7 minutes for the smoke test). Waiting is not billed.
- Windows timers are coarse on Python 3.12. Use `icr.clock` for all timing.
- Docker Desktop was started at the beginning of the session. It is not needed until M7/M8.
