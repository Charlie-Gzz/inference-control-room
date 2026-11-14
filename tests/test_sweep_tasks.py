"""Sweep task names: parsing, run ids, the time guard, and the chained calibration task."""

import json

from icr import config
from icr.modal_app import sweep


def test_plain_tasks():
    assert sweep.parse_task("gsm8k") == {"kind": "gsm8k", "mix": "", "rates": None, "tag": ""}
    assert sweep.parse_task("ramp:chat")["mix"] == "chat"
    assert sweep.run_id("l4", "awq", "ramp:chat") == "sweep-l4-awq-ramp-chat"
    assert sweep.run_id("l4", "awq-draft", "greedy") == "sweep-l4-awq-draft-greedy"


def test_ramp_with_its_own_rates_and_tag():
    task = "ramp:no-sharing@0.5;1;1.5=cal"
    parsed = sweep.parse_task(task)
    assert parsed == {"kind": "ramp", "mix": "no-sharing", "rates": [0.5, 1.0, 1.5], "tag": "cal"}
    assert sweep.run_id("l4", "awq", task) == "sweep-l4-awq-ramp-no-sharing-cal"


def test_rates_do_not_change_the_run_id():
    assert sweep.run_id("l4", "fp8", "ramp:chat@2;3;4") == sweep.run_id("l4", "fp8", "ramp:chat")


def test_time_estimates_cover_the_ramp():
    ramp = {"rates_rps": [1, 2, 3, 4, 5, 6], "level_s": 40.0, "warmup_s": 30.0}
    assert sweep.task_seconds("ramp:chat", ramp) == 30 + 240 + 90
    assert sweep.task_seconds("ramp:chat@1;2=cal", ramp) == 30 + 80 + 90
    assert sweep.task_seconds("gsm8k", ramp) > sweep.task_seconds("greedy", ramp)
    # A calibration is two ramps; its second half alone is one.
    assert sweep.task_seconds("calib:rag@1;2;3", ramp) == 2 * (30 + 120 + 90)
    assert sweep.task_seconds("fine-of:calib:rag@1;2;3", ramp) == 30 + 120 + 90


def test_calibration_task_is_a_coarse_ramp_then_a_fine_one(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VOL_RUNS", str(tmp_path))
    task = "calib:no-sharing@1;2;3"
    assert sweep.coarse_task(task) == "ramp:no-sharing@1;2;3=cal"
    assert sweep._result_ids("l4", "awq", task) == [
        "sweep-l4-awq-ramp-no-sharing-cal",
        "sweep-l4-awq-ramp-no-sharing-fine",
    ]
    assert not sweep._done("l4", "awq", task)

    # A finished coarse ramp: 1 and 2 req/s meet the SLO, 3 req/s does not.
    coarse = tmp_path / "sweep-l4-awq-ramp-no-sharing-cal"
    coarse.mkdir()
    rows = [
        {"phase": "measured", "level": level, "scheduled_s": level * 40 + i, "sent_s": 0.0,
         "end_s": level * 40 + i + 1, "ttft_s": 5.0 if level == 2 else 0.3, "itl_s": 0.03,
         "e2e_s": 1.0, "prompt_tokens": 900, "cached_tokens": 0, "completion_tokens": 60,
         "error": ""}
        for level in range(3)
        for i in range(10)
    ]  # fmt: skip
    (coarse / "requests.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    meta = {"ramp": {"rates_rps": [1.0, 2.0, 3.0], "level_s": 40.0, "warmup_s": 30.0}}
    (coarse / "meta.json").write_text(json.dumps(meta))
    fine = sweep.fine_task("l4", "awq", task)
    assert fine == "ramp:no-sharing@2.0;2.2;2.4;2.6;2.8;3.0=fine"
    assert sweep.run_id("l4", "awq", fine) == "sweep-l4-awq-ramp-no-sharing-fine"

    (tmp_path / "sweep-l4-awq-ramp-no-sharing-fine").mkdir()
    (tmp_path / "sweep-l4-awq-ramp-no-sharing-fine" / "meta.json").write_text("{}")
    assert sweep._done("l4", "awq", task)


def test_no_fine_ramp_when_the_coarse_ramp_never_missed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VOL_RUNS", str(tmp_path))
    coarse = tmp_path / "sweep-l4-awq-ramp-rag-cal"
    coarse.mkdir()
    row = {"phase": "measured", "level": 0, "scheduled_s": 1.0, "sent_s": 1.0, "end_s": 2.0,
           "ttft_s": 0.3, "itl_s": 0.03, "e2e_s": 1.0, "prompt_tokens": 900, "cached_tokens": 0,
           "completion_tokens": 60, "error": ""}  # fmt: skip
    (coarse / "requests.jsonl").write_text(json.dumps(row) + "\n")
    meta = {"ramp": {"rates_rps": [1.0], "level_s": 40.0, "warmup_s": 30.0}}
    (coarse / "meta.json").write_text(json.dumps(meta))
    assert sweep.fine_task("l4", "awq", "calib:rag@1") is None
