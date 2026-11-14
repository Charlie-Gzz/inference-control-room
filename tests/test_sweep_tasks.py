"""Sweep task names: parsing, run ids and the time guard's estimates."""

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
