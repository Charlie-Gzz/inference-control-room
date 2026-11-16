# Portfolio card

## Title

Switchyard: Inference Control Room

## Pitch

Serving LLMs is mostly a cost problem. Switchyard runs a small vLLM fleet on real traffic
patterns, measures which serving techniques lower cost and latency, and replays every
recorded request in an interactive control room.

## Headline metric

**41% lower p95 time to first token, 20% more traffic within the latency target, 14%
lower cost per million tokens.** Prefix-aware routing against round-robin, same 2 GPUs,
same traffic.

## Three bullets

- Wrote a prefix-cache-aware router in Go and compared it with round-robin and
  least-loaded routing on identical traffic, with repeats.
- Swept 10 server configs on an L4 and 4 on an H100 (quantization, speculative
  decoding, batch limits) and built an optimizer that picks the cheapest one for a
  latency target. One H100 carried 9 times the traffic of one L4 at 54% lower cost per
  token.
- Built a control room that replays the recorded runs request by request, so every
  number can be traced to the requests behind it.

## Tags

LLM serving, vLLM, KV cache, prefix caching, Go, load balancing, autoscaling,
quantization, speculative decoding, benchmarking, cost engineering, observability, Modal

## CV bullet

Built and benchmarked an LLM serving fleet (vLLM, Qwen2.5-7B, NVIDIA L4) with a
prefix-cache-aware router in Go. On identical open-loop traffic it cut p95 time to first
token by 41% and raised capacity within the latency SLO by 20% against round-robin, for
14% lower cost per million tokens.

## Image

`assets/screenshots/hero.png`. Link preview: `site/assets/og.png` (1200x630).
