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
# vLLM 0.33.0 asks for exactly this package and version when suffix decoding is requested.
SUFFIX_PACKAGES = ("arctic-inference==0.1.1",)

BASELINE = ServerConfig(name="awq")

STAGE_1 = [
    BASELINE,
    # quantization (bf16 fits on an L4 with a smaller KV cache)
    replace(BASELINE, name="bf16", weights="bf16"),
    replace(BASELINE, name="fp8", weights="bf16", quantization="fp8_per_tensor"),
    # speculative decoding
    # awq-draft does not start: vLLM refuses a draft model whose vocabulary size differs
    # from the target's (Qwen2.5-0.5B has 151,936 entries, Qwen2.5-7B has 152,064).
    # It stays here so the failure is reproducible. See docs/DECISIONS.md.
    replace(BASELINE, name="awq-draft", speculative=DRAFT),
    replace(BASELINE, name="awq-ngram", speculative=NGRAM),
    replace(BASELINE, name="awq-suffix", speculative=SUFFIX, pip=SUFFIX_PACKAGES),
    # prefix caching off
    replace(BASELINE, name="awq-nocache", prefix_caching=False),
    # two other batch limits
    replace(BASELINE, name="awq-seqs32", max_num_seqs=32),
    replace(BASELINE, name="awq-seqs64", max_num_seqs=64),
]

# Stage 2: combinations of the stage-1 winners (docs/DECISIONS.md, "Stage 2").
# Stage 1's winner in every dimension was the baseline's own setting, with AWQ and FP8
# tied. Smaller batch limits lost, so stage 2 pushes the batch limit the other way on
# both tied quantizations.
STAGE_2 = [
    replace(BASELINE, name="awq-seqs256", max_num_seqs=256),
    replace(
        BASELINE,
        name="fp8-seqs256",
        weights="bf16",
        quantization="fp8_per_tensor",
        max_num_seqs=256,
    ),  # fmt: skip
]

CONFIGS: dict[str, ServerConfig] = {c.name: c for c in [*STAGE_1, *STAGE_2]}

# Named job lists for `modal run ...::sweep --jobs <name>`. Every config gets the chat
# ramp at the frozen sweep levels. GSM8K runs once per quantization, the greedy-output
# check on the baseline and on every speculative config.
JOBS = {
    "stage1": (
        "awq=ramp:chat,gsm8k,greedy|awq-nocache=ramp:chat|awq-seqs32=ramp:chat"
        "|awq-seqs64=ramp:chat|fp8=ramp:chat,gsm8k|bf16=ramp:chat,gsm8k"
        "|awq-ngram=ramp:chat,greedy|awq-draft=ramp:chat,greedy"
    ),
    # awq-suffix installs a package first, so it runs last in the session.
    "stage2": "awq-seqs256=ramp:chat|fp8-seqs256=ramp:chat|awq-suffix=ramp:chat,greedy",
    # Finalists on the rag workload, and the no-sharing calibration of the fleet config.
    "finalists": "awq=ramp:rag,calib:no-sharing@0.5;1;1.5;2;3;4|fp8=ramp:rag",
}
