# Third-party models, data and software

Nothing below is redistributed in this repo, except the small derived samples noted.
Licenses were checked on 2026-11-13 from each source's own page.

## Models (official `Qwen/` uploads only)

| Model | Use | License | URL | Pinned revision |
|---|---|---|---|---|
| Qwen2.5-7B-Instruct | bf16 and FP8 (quantized at load time) serving | Apache-2.0 | https://huggingface.co/Qwen/Qwen2.5-7B-Instruct | `a09a3545` |
| Qwen2.5-7B-Instruct-AWQ | 4-bit AWQ serving (baseline) | Apache-2.0 | https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-AWQ | `b2503754` |
| Qwen2.5-0.5B-Instruct | draft model for speculative decoding | Apache-2.0 | https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct | `7ae55760` |

Model weights are never committed. They live in a Modal Volume.

## Data

| Data | Use | License | URL |
|---|---|---|---|
| BurstGPT v2.0 (`BurstGPT_without_fails_1.csv`) | request arrival times | CC BY 4.0 | https://github.com/HPMLL/BurstGPT |
| GSM8K (test split, 250-question seeded subset) | quality check for quantized configs | MIT | https://huggingface.co/datasets/openai/gsm8k |

**BurstGPT attribution.** Yuxin Wang, Yuhan Chen, Zeyu Li, Xueze Kang, Yuchu Fang, Yeju Zhou,
Yang Zheng, Zhenheng Tang, Xin He, Rui Guo, Xin Wang, Qiang Wang, Amelie Chi Zhou, Xiaowen Chu.
"BurstGPT: A Real-World Workload Dataset to Optimize LLM Serving Systems." KDD 2025.
https://doi.org/10.1145/3711896.3737413

Derived sample committed here: `src/icr/workloads/data/burstgpt_segments.json` holds the
arrival times (seconds, relative to segment start) of two 8,000-request segments of the trace.
No prompts, tokens or session data are included. Changes made: only timestamps kept, made
relative to the segment start.

The GSM8K subset is not committed. It lives in the Modal Volume.

## Software

| Software | Use | License |
|---|---|---|
| vLLM 0.33.0 | serving engine (Modal image only) | Apache-2.0 |
| Modal client | GPU cloud | Apache-2.0 |
| Go 1.27.4 toolchain | builds the router (downloaded to `.tools/`, not committed) | BSD-3-Clause |
| Tailwind CSS (CDN), Inter, JetBrains Mono | site styling and fonts | MIT, OFL-1.1, OFL-1.1 |
| matplotlib, Plotly, aiohttp, Typer, numpy, pytest, ruff, Playwright | charts, client, CLI, tests | see each project |
