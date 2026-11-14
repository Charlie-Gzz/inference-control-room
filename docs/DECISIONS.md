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
| Ledger cost = Modal's billing report per app, with a time-based estimate until it arrives | wall-clock of the remote call; in-container timer; billing report | The first smoke run waited 7 minutes for an L4. Wall-clock counted that as spend ($0.23) while Modal billed $0.09. `icr.ledger.reconcile` now reads `modal billing report` per app, and the budget guard uses the actual figure. | yes |
| JIT caches (FlashInfer, Triton, torch.compile) live in the Volume | rebuild per container; cache in Volume | The first vLLM start took 270 s, of which about 120 s was FlashInfer building its sampling kernel. Cached, later starts skip it. | yes |

## Benchmark method (frozen 2026-11-14, before any ramp or fleet result)

Seen before freezing: only the M0 smoke test (20 requests: 19 ms per token single-stream,
0.74 s to prefill 2,164 uncached tokens, 0.05 s when cached, KV cache of 240,768 tokens).

| Decision | Options considered | Why | Easy to change? |
|---|---|---|---|
| **Default SLO: p95 time to first token <= 2.0 s and p95 inter-token latency <= 100 ms, with no failed requests** | TTFT 1 s / 2 s / 5 s; ITL 50 / 100 / 200 ms | Chat targets. 2 s is where a chat UI starts to feel stuck. 100 ms per token is 10 tokens/s, above reading speed. Both are loose enough that an L4 can meet them and tight enough to bind under load. | no (frozen) |
| TTFT and end-to-end latency count from the **scheduled** arrival time | from send time | Open-loop rule: a queue in the sender must not hide a slow system. Send lag is recorded separately. | no (frozen) |
| ITL of a request = (last token time - first token time) / (output tokens - 1); the SLO uses the p95 across requests | per-gap p95; per-request mean | Standard definition, robust to chunks that carry several tokens (speculative decoding). The longest gap per request is also recorded. | no (frozen) |
| Goodput = share of measured requests that finished without error, with TTFT <= 2.0 s and ITL <= 100 ms | throughput only | "What users actually get." | no (frozen) |
| Requests use greedy decoding, `ignore_eos` and `max_tokens` drawn from BurstGPT's real response lengths (clipped to 16..400; 150 for agent steps) | let the model stop naturally; fixed length | Every policy and config then produces exactly the same number of output tokens on the same traffic, so comparisons are clean. Quality checks (GSM8K, greedy match) use natural stopping. | no (frozen) |
| Chat history contains scripted assistant replies, not the model's real output | feed real outputs back | Real outputs would make turn k depend on the policy and break "same traffic for every policy". The cached prefix is then the whole previous prompt. | no (frozen) |
| Workload sizes: as in `src/icr/workloads/mixes.py` (chat: 24 tenants, mean 5 turns; rag: 8 tenants x 20 documents of 1.5k to 2.5k tokens; agentic: 6 agent types with a 2.5k-token preamble; no-sharing control with chat's length profile) | tune pools until prefix-aware wins | Sizes come from the workload descriptions. Whether they exceed one replica's cache is measured and reported, not tuned. | no (frozen) |
| Arrivals: BurstGPT `steady` segment for fixed-traffic runs and ramps, `bursty` segment for the autoscaling window, linearly rescaled | Poisson | Real arrival pattern. | no (frozen) |
| **Saturation rate R_sat(workload)** = highest level of a single-replica ramp on the fleet config that meets the SLO | throughput knee | Same definition as capacity everywhere else. | no (frozen) |
| Single-replica ramps: 30 s warmup, then 6 levels x 40 s. Levels for config sweeps: 0.5, 0.7, 0.85, 1.0, 1.15, 1.3 x the baseline's R_sat | longer levels; finer steps | Fits about 12 configs in the $10 development budget. Capacity resolution is about 15%. | no (frozen) |
| **Fixed-traffic fleet runs: 0.7 x 4 x R_sat(workload)**, 60 s warmup + 180 s measured | pick the load after seeing results | The plan's rule. Never chosen to flatter a policy. | no (frozen) |
| **Fleet capacity ramp: 60 s warmup, then 6 levels x 60 s at 0.6, 0.75, 0.9, 1.05, 1.2, 1.35 x 4 x R_sat(chat)** | 4 levels | Six levels give 15% resolution around the single-replica estimate. | no (frozen) |
| Capacity = the highest level that meets the SLO with every lower level also meeting it | best level anywhere | Once a ramp overloads, later levels inherit the queue. | no (frozen) |
| **Cost per million tokens at the SLO** = container cost per hour (GPUs + requested CPU + requested memory, Modal list prices) / generated tokens per hour at capacity. Total (prompt + generated) tokens are reported next to it. | raw cost of a fixed-traffic run | On identical traffic every policy burns the same GPU-seconds. Cost differences come only from capacity. | no (frozen) |
| Repeats: 3 per fleet comparison (2 for the capacity ramp), seeds 0, 1, 2. Within a repeat every policy gets the identical request sequence. Report median with min and max; flag spread above 10%. | one run | The plan's rule. Different seeds per repeat also sample different traffic. | no (frozen) |
| Policy order inside a fleet session is interleaved (RR, LL, PA / PA, RR, LL / LL, PA, RR) and every run starts from empty prefix caches and an empty router table | fixed order | Slow drift must not favor one policy; one run's cache must not help the next. | no (frozen) |
| Router knobs: 256-byte text chunks, up to 128 chunks hashed, load bound = max(4, ceil(1.5 x fair share)), per-replica prefix table sized to 80% of the replica's KV cache (in chunks) | tune on GPU results | Chosen from first principles and the mock, before any GPU fleet run. 256 bytes is about 42 tokens of this text: fine enough to see a 200-token system prompt, coarse enough to keep the table small. | no (frozen) |
| Fleet config = cheapest stage-1 or stage-2 config that meets the default SLO on `chat` (lowest cost per million tokens at the SLO) | fastest; highest quality | The plan's definition. | no (frozen) |
