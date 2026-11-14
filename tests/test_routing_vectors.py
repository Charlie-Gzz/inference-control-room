"""The Python reference policies must agree with the shared vectors the Go router uses."""

import json
from pathlib import Path

import pytest

from icr.routing.policy import Router, RouterConfig
from icr.routing.prefix import canonical_text, prefix_hashes

VECTORS = json.loads(
    (Path(__file__).parents[1] / "router" / "testdata" / "vectors.json").read_text("utf-8")
)


def test_fnv1a_known_value():
    assert prefix_hashes(b"a", 1, 9) == [0xAF63DC4C8601EC8C]


@pytest.mark.parametrize("vector", VECTORS["hashes"])
def test_hash_vectors(vector):
    text = canonical_text(vector["messages"])
    got = [f"{h:016x}" for h in prefix_hashes(text, vector["chunk_size"], vector["max_chunks"])]
    assert got == vector["expect"]


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_routing_vectors(case):
    router = Router(case["replicas"], case["policy"], RouterConfig(**case["config"]))
    for i, step in enumerate(case["steps"]):
        if step["op"] == "finish":
            router.finish(step["replica"])
        elif step["op"] == "set_live":
            router.set_live(step["live"])
        elif step["op"] == "reset":
            router.reset()
        else:
            d = router.route([{"role": "u", "content": step["content"]}])
            want = step["expect"]
            got = {"replica": d.replica, "reason": d.reason, "matched": d.matched_chunks}
            assert got == {k: want[k] for k in got}, f"step {i}"
            if "loads" in want:
                assert d.loads == want["loads"], f"step {i}"
