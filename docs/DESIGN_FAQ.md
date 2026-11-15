# Design FAQ

Questions an expert would ask about Switchyard, each answered in a few lines with a
pointer to the code or the result. Numbers come from `results/RESULTS.md` and
`results/summaries/summary.json`, which `icr results` rebuilds from the saved runs.

## Method

### 1. Why an open-loop load generator?

A closed-loop client sends the next request only when the previous one returns. When the
server slows down, the client slows down with it, and the queue that real users would be
standing in never shows up in the numbers (coordinated omission). Here every request is
sent at its scheduled arrival time, whether or not earlier ones have finished, and
latency counts from the scheduled time, not the send time.

- Code: `src/icr/loadgen/client.py` (`LoadGenerator.run`, `ttft_s` is first token minus
  scheduled time). Test: `tests/test_loadgen.py`.
- Send lag (send time minus scheduled time) is recorded per request. Its p99 was 2.7 ms
  in the single-GPU ramps, so the sender itself was never the bottleneck.

### 2. How do you know every routing policy saw the same traffic?

The workload is a pure function of (mix, seed, arrival times). Within a repeat, all
policies get byte-identical request bodies at identical scheduled times. Two things
would break this, and both are designed out:

- Output length. Requests use greedy decoding with `ignore_eos` and a `max_tokens` drawn
  from the trace's real response lengths, so every policy generates exactly the same
  number of tokens.
- Chat history. Turn k of a conversation contains scripted assistant replies, not the
  model's real output. Real outputs would make later prompts depend on the policy.

Code: `src/icr/workloads/generator.py`. Tests: `tests/test_workloads.py`,
`tests/test_fleet_plan.py::test_policies_of_one_repeat_get_identical_traffic`. Before
every run the prefix cache of every replica and the router's table are emptied
(`Fleet.clean_state` in `src/icr/modal_app/fleet.py`).

### 3. How were the traffic levels chosen? Could they have been picked to flatter a policy?

They are multiples of a measured number, fixed before any fleet run. One replica of the
fleet config is ramped until it misses the SLO. The highest rate that still meets it is
its saturation rate, R_sat. Fleet runs then use 0.7 x 4 x R_sat, and the capacity ramp
uses 0.6 to 1.35 x 4 x R_sat. Measured R_sat on one L4: 5.2 req/s for chat, 2.0 for rag,
1.1 for the no-sharing control.

- Rule and values: `docs/DECISIONS.md` ("Benchmark method" and "Fleet method, final numbers").
- Code: `src/icr/analysis/calibrate.py`, `src/icr/fleet/plan.py`.
- Known weakness: R_sat for rag is conservative (2.0, while a later ramp met the SLO at
  2.6). It was frozen before that ramp ran and was not changed afterwards.

### 4. Why is cost reported "at the SLO" and not per run?

On identical traffic in a fixed window, every routing policy burns the same GPU-seconds
and generates the same tokens, so the raw cost per token is identical by construction.
A router can only lower cost by letting the same GPUs carry more traffic before latency
breaks. So cost per million tokens = fleet cost per hour (GPUs + requested CPU + requested
memory at Modal's list prices) divided by tokens per hour at the highest traffic level
that still meets the SLO.

Code: `metrics.capacity` and `metrics.cost_per_million` in `src/icr/analysis/metrics.py`.

### 5. How sure are these numbers?

- Fleet comparisons run 3 times with different seeds (2 for the capacity ramp). Tables
  show the median with min and max and flag any spread above 10%.
- Single-GPU capacity is known to about one ramp level (15%). AWQ sat right on a level:
  of four AWQ ramps near 6 req/s, one met the 100 ms inter-token target (86.7 ms) and
  three missed it by 0.2 to 11 ms. So one-level differences between configs are reported
  as ties. Differences of two levels or more are treated as real.
- GSM8K accuracy uses 250 questions, so its 95% interval is about 3 points each way.
  The gaps between quantizations (89.6% to 92.4%) are inside it.

## Routing

### 6. Why does the router hash text chunks instead of tokens?

The router has no tokenizer, and it should not need one: tokenizing a 3,000-token prompt
costs more than the routing decision is worth. It hashes the prompt text in 256-byte
chunks with one running FNV-1a hash, so two prompts share their first k hashes exactly
when their first k chunks are byte-identical. Identical text gives identical tokens, so a
shared text prefix is a shared token prefix. 256 bytes is about 42 tokens of this text:
fine enough to see a 200-token system prompt, coarse enough to keep the table small.

- Code: `router/policies/prefix.go`, mirrored by `src/icr/routing/prefix.py`.
- Both implementations are checked against the same vectors: `router/testdata/vectors.json`.
- The router reads the body once and only parses it for the prefix-aware policy.

### 7. What happens when the replica that has the prefix cached is overloaded?

The request goes to the least loaded replica instead, and the decision is logged as
`prefix-overloaded`. A replica counts as overloaded when it has more requests in flight
than max(4, ceil(1.5 x fair share)), where fair share is the fleet's total in flight
divided by the number of replicas. Without the bound, one hot prefix would pile onto one
GPU.

- Code: `Router.bound` and `Router.prefixAware` in `router/policies/router.go`.
- Test: `tests/test_router.py::test_overloaded_replica_falls_back_to_least_loaded`.
- The router's table remembers, per replica, the prefixes it sent there (LRU, sized to
  80% of the replica's KV cache). It is a guess about the replica's cache, not a
  reading of it. Reading the real cache state is stretch item 1 in the plan.

## What the single-GPU sweep showed

### 8. Why did inter-token latency, not time to first token, set the capacity?

vLLM admits requests into the running batch as they arrive (up to 128 by default), so
nothing waits in a queue and the first token comes quickly even under heavy load: p95
time to first token was 0.39 s at the level where the SLO broke. What gets slower is
every step of the batch. Each step now also carries the prompt processing of newly
arrived requests, and all running requests wait for it. At 5.98 req/s the p95 gap
between tokens was 87 ms. At 6.76 req/s it was 237 ms.

This is why prefix caching matters so much here: outputs are short (median 36 tokens in
the trace) and prompts are long (1,260 tokens on average), so most of the GPU's work is
reading prompts.

Runs: `results/runs/sweep-l4-awq-ramp-chat*`.

### 9. What does the batch limit (`max_num_seqs`) change?

It moves the failure from one latency to the other. With the limit at 32, the token gap
stayed low at 5.98 req/s (73 ms) but requests queued for a slot: p95 time to first token
rose to 2.3 s and broke the 2 s target. With the limit at 64 the queue appeared one level
later (9.1 s to first token at 6.76 req/s). With the default 128 nothing queues and the
token gap is what breaks. Raising the limit to 256 changed nothing beyond noise, because
a replica at its limit holds well under 128 requests.

Runs: `sweep-l4-awq-seqs32-ramp-chat`, `-seqs64-`, `-seqs256-`.

### 10. Why did speculative decoding make things worse?

Speculation spends extra GPU work per step to guess several tokens at once. That pays off
when the GPU has idle capacity and outputs are long. Under a full batch on a prompt-heavy
workload it is the wrong trade.

- N-gram lookup: only 12.9% of proposed tokens were accepted, and capacity fell from 5.98
  to 3.64 req/s. Greedy outputs matched the baseline as often as the baseline matches
  itself (93% against 92%), so it changed speed, not text.
- Suffix decoding: one level under the baseline (5.20 req/s), and the vLLM engine crashed
  during the overload level.
- A draft model could not be tested: vLLM requires the draft and the target to have the
  same vocabulary size, and Qwen2.5-0.5B (151,936) does not match Qwen2.5-7B (152,064).

Chart: `assets/charts/spec_decode.png`. Decisions: `docs/DECISIONS.md`.

### 11. Why is the 4-bit model more than twice as fast as bf16 on an L4?

An L4 has 24 GB. The bf16 weights take about 15 GB of it, which makes every step read
more memory and leaves a KV cache of only 74,000 tokens (vLLM's own figure). AWQ (4-bit)
leaves 250,000 and FP8 185,000. With so little cache, bf16 also starts evicting prefixes:
its cache hit rate fell from 83% to about 60% as traffic rose, while AWQ's stayed at 83%.
bf16 met the SLO only up to 2.6 req/s, against 5.98 for AWQ and FP8, with GSM8K accuracy
within 3 points for all three.

Chart: `assets/charts/quantization.png`.

### 12. How much is prefix caching worth on a single GPU?

With prefix caching off, the same replica missed the SLO at every level tested, even the
lowest (2.6 req/s, against 5.98 with caching on). The no-sharing control workload gives
the same answer from the other side: with nothing to reuse, one replica saturates at 1.1
req/s instead of 5.2. A single replica that sees all the traffic served about 83% of
chat prompt tokens from cache.

Runs: `sweep-l4-awq-nocache-ramp-chat`, `sweep-l4-awq-ramp-no-sharing-fine`.
