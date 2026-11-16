# Slides outline (7 slides)

One idea per slide, one asset per slide. Numbers are from `results/RESULTS.md`.

## 1. Title

- **Switchyard: an LLM serving fleet you can watch**
- Serving LLMs is mostly a cost problem. This project measures what actually lowers it.
- Asset: `assets/screenshots/hero.png` (or the loop video, `assets/video/switchyard-loop.mp4`)

## 2. The problem

- A chat request resends the whole conversation every turn. Prompts average 1,260
  tokens. Answers have a median of 36.
- A GPU that has the conversation cached skips most of that work. One that does not
  reads it all again.
- A plain load balancer does not know which GPU has what.
- Asset: `assets/diagrams/architecture.png`

## 3. What I built

- A Go router with three policies, in front of one vLLM replica per GPU.
- An open-loop load generator driven by real arrival times (BurstGPT).
- A recorder that keeps every request and every routing decision.
- Asset: `assets/screenshots/control-room.png`

## 4. Result: same traffic, different router

- Prefix-aware routing cut p95 time to first token by 41% against round-robin
  (0.30 s against 0.51 s).
- Share of prompt tokens served from cache: 84% against 74%.
- Least-loaded routing was no better than round-robin.
- Asset: `assets/charts/latency_by_policy.png`

## 5. Result: cost

- On the same traffic every router costs the same. Savings come from capacity.
- Prefix-aware routing carried 20% more traffic within the latency target on the same
  2 GPUs: 14% lower cost per million tokens.
- Asset: `assets/charts/capacity_by_policy.png`

## 6. What did not work

- Speculative decoding lowered capacity (n-gram: 5.98 to 3.64 req/s). Short answers,
  long prompts, full batches.
- Full-precision weights were less than half as fast on a 24 GB GPU: no room for the cache.
- The 4-GPU machine never started. The fleet ran on 2.
- Asset: `assets/charts/cost_by_config.png`

## 7. How I know

- Open-loop load, identical traffic for every policy, 3 repeats, a no-sharing control.
- Method fixed before the results, every decision logged.
- Total GPU spend in the ledger. Every run replayable in the control room.
- Asset: `assets/screenshots/method.png`

## Backup slides

- Pareto frontier: `assets/charts/pareto.png`
- Quantization against accuracy: `assets/charts/quantization.png`
- Router overhead: `assets/charts/router_overhead.png`
- What-if explorer: `assets/screenshots/what-if.png`
