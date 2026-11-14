"""Saved runs: compressed JSONL that reads back the same, with stable bytes."""

import json

from icr.analysis import runs


def test_jsonl_is_compressed_and_reads_back(tmp_path):
    rows = [{"id": i, "ttft_s": 0.1 * i} for i in range(50)]
    text = "".join(json.dumps(r) + "\n" for r in rows)
    runs.write_file(tmp_path / "run-a", "requests.jsonl", text)
    runs.write_file(tmp_path / "run-a", "meta.json", json.dumps({"policy": "direct"}))

    assert not (tmp_path / "run-a" / "requests.jsonl").exists()
    run = runs.load("run-a", tmp_path)
    assert run.requests == rows
    assert run.replicas == []  # absent file
    assert run.meta == {"policy": "direct"}


def test_same_data_gives_the_same_bytes(tmp_path):
    text = '{"id": 1}\n'
    runs.write_file(tmp_path / "a", "requests.jsonl", text)
    runs.write_file(tmp_path / "b", "requests.jsonl", text)
    read = lambda d: (tmp_path / d / "requests.jsonl.gz").read_bytes()  # noqa: E731
    assert read("a") == read("b")


def test_plain_jsonl_is_still_readable(tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "requests.jsonl").write_text('{"id": 7}\n', encoding="utf-8")
    assert runs.read_jsonl(tmp_path / "old", "requests.jsonl") == [{"id": 7}]


def test_all_runs_filters_by_prefix(tmp_path):
    for name in ("sweep-l4-awq-ramp-chat", "fleet-fixed-chat-round-robin-s0"):
        runs.write_file(tmp_path / name, "meta.json", "{}")
    runs.write_file(tmp_path / "sweep-l4-awq-gsm8k", "result.json", '{"gsm8k": {}}')
    (tmp_path / "empty").mkdir()
    assert [r.run_id for r in runs.all_runs("sweep-", tmp_path)] == [
        "sweep-l4-awq-gsm8k",
        "sweep-l4-awq-ramp-chat",
    ]
    assert len(runs.all_runs(root=tmp_path)) == 3
