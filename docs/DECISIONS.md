# Decisions

Choices a reviewer might question. Newest at the bottom of each section.

## Setup (M0)

| Decision | Options considered | Why | Easy to change? |
|---|---|---|---|
| Pin vLLM **0.33.0** | latest release (0.33.0, 2026-11-02); the 0.21.0 in Modal's example | Newest release has the flags we need (`--enable-prompt-tokens-details`, online FP8, per-request spec-decode metrics). Pinned in `src/icr/config.py`. | yes |
| Pin Go **1.27.4** in `.tools/` | 1.27.4 (current stable); 1.26.11 | Current stable. Zip verified against the SHA-256 published by go.dev. | yes |
| Request the H100 as **`H100!`** | `H100`; `H100!` | Modal may silently upgrade `H100` to an H200. `H100!` forbids that, which the plan requires for benchmarks. | yes |
| "Billed seconds" = wall-clock seconds of the remote call | container-internal timer; Modal billing API per run | The wall clock includes queue time and container startup, so it is an upper bound and the ledger never undercounts. Checked against `modal billing report` after each milestone. | yes |
| Budget guard uses the **worst case** (full timeout) before each run | check after the run only | A run is refused if its timeout could break a cap, so a hung container cannot overspend. | yes |
| FP8 = vLLM **online quantization** (`--quantization fp8_per_tensor`) of the bf16 weights | pre-quantized community FP8 checkpoint; online quantization | There is no official `Qwen/` FP8 upload. The plan allows only official uploads, so we quantize the official bf16 weights at load time. L4 (Ada) supports FP8 W8A8. | yes |
| AWQ model loaded with no `--quantization` flag | pass `awq`; auto-detect | vLLM reads the format from the checkpoint config. AutoAWQ is deprecated upstream, so the smoke test checks this first. | yes |
| CUDA devel base image (`nvidia/cuda:12.9.0-devel-ubuntu22.04`) | `debian_slim`; CUDA devel | Same base as Modal's own vLLM example. vLLM's JIT paths can need a compiler. | yes |
| Modal Volume **v2**, one Volume for weights, data, compile caches and runs | separate Volumes | One mount, simpler commits. v2 is Modal's recommendation for new Volumes. | yes |
| BurstGPT file: `BurstGPT_without_fails_1.csv` (v2.0, 1.4M requests) | file 1, 2 or 3; with or without failures | Smallest file, still two months of real traffic. Failed requests are not real load on a healthy fleet. | yes |
| Arrival segments chosen by a fixed rule (see `src/icr/workloads/burstgpt.py`) | hand-pick a nice-looking burst; fixed rule | A rule fixed before any benchmark cannot be tuned toward a result. `steady` = median burstiness, `bursty` = 95th percentile, both among the busier half of 8,000-arrival segments. | no (frozen) |
| Arrival rescaling: linear time compression to the target mean rate, with seeded sub-second jitter | thinning; Poisson re-draw; linear compression | BurstGPT's own README recommends scaling the average RPS. Linear compression keeps the burst shape. The trace has one-second resolution, so arrivals get a seeded jitter inside their second. | yes |
