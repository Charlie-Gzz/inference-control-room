"""Prefix hashing shared by the Go router, the Python reference policies and the mock.

The router has no tokenizer, so it hashes prompt *text*:
1. Canonical text: for every message, `role + "\\n" + content + "\\n"`, encoded as UTF-8.
2. Cut into fixed-size byte chunks. Only full chunks count.
3. One running FNV-1a 64-bit hash over the bytes; its value after each chunk is that
   prefix's hash. Two prompts share their first k hashes exactly when their first
   k chunks are byte-identical.

The Go implementation is `router/policies/prefix.go`. Both are checked against
`router/testdata/vectors.json`.
"""

from __future__ import annotations

FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK = 0xFFFFFFFFFFFFFFFF


def canonical_text(messages: list[dict]) -> bytes:
    parts = []
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, list):  # OpenAI content parts: keep the text ones
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        parts.append(f"{m.get('role', '')}\n{content}\n")
    return "".join(parts).encode("utf-8")


def prefix_hashes(text: bytes, chunk_size: int, max_chunks: int) -> list[int]:
    """Hash of every full-chunk prefix of `text`, shortest first."""
    hashes: list[int] = []
    h = FNV_OFFSET
    full = min(len(text) // chunk_size, max_chunks)
    for i in range(full):
        for b in text[i * chunk_size : (i + 1) * chunk_size]:
            h = ((h ^ b) * FNV_PRIME) & MASK
        hashes.append(h)
    return hashes
