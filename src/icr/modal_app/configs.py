"""The server configs of the staged sweep (PLAN.md section 3, item 7).

Baseline: 4-bit AWQ, prefix caching on, no speculative decoding, vLLM's default batch
limit (128 sequences). Stage 1 changes one thing at a time. Stage 2 combines winners.
"""

from __future__ import annotations

from dataclasses import replace

from icr import config
from icr.modal_app.vllm_proc import ServerConfig


def _draft_path() -> str:
    """Local snapshot path of the draft model (the server runs with HF_HUB_OFFLINE=1)."""
    m = config.MODELS["draft"]
    repo_dir = "models--" + m["repo"].replace("/", "--")
    return f"{config.VOL_HF}/hub/{repo_dir}/snapshots/{m['revision']}"


DRAFT = {"method": "draft_model", "model": _draft_path(), "num_speculative_tokens": 5}
NGRAM = {
    "method": "ngram",
    "num_speculative_tokens": 4,
    "prompt_lookup_min": 2,
    "prompt_lookup_max": 4,
}
SUFFIX = {"method": "suffix", "num_speculative_tokens": 8}

BASELINE = ServerConfig(name="awq")

STAGE_1 = [
    BASELINE,
    # quantization (bf16 fits on an L4 with a smaller KV cache)
    replace(BASELINE, name="bf16", weights="bf16"),
    replace(BASELINE, name="fp8", weights="bf16", quantization="fp8_per_tensor"),
    # speculative decoding
    replace(BASELINE, name="awq-draft", speculative=DRAFT),
    replace(BASELINE, name="awq-ngram", speculative=NGRAM),
    replace(BASELINE, name="awq-suffix", speculative=SUFFIX),
    # prefix caching off
    replace(BASELINE, name="awq-nocache", prefix_caching=False),
    # two other batch limits
    replace(BASELINE, name="awq-seqs32", max_num_seqs=32),
    replace(BASELINE, name="awq-seqs64", max_num_seqs=64),
]

# Stage 2 (combinations of winners) is added here after stage 1, and logged in DECISIONS.md.
STAGE_2: list[ServerConfig] = []

CONFIGS: dict[str, ServerConfig] = {c.name: c for c in [*STAGE_1, *STAGE_2]}

# Named job lists for `modal run ...::sweep --jobs <name>`. Every config gets the chat
# ramp at the frozen sweep levels. GSM8K runs once per quantization, the greedy-output
# check on the baseline and on every speculative config.
JOBS = {
    "stage1": (
        "awq=ramp:chat,gsm8k,greedy|awq-nocache=ramp:chat|awq-seqs32=ramp:chat"
        "|awq-seqs64=ramp:chat|fp8=ramp:chat,gsm8k|bf16=ramp:chat,gsm8k"
        "|awq-ngram=ramp:chat,greedy|awq-draft=ramp:chat,greedy|awq-suffix=ramp:chat,greedy"
    ),
}
