"""Saturation rates from calibration ramps, including a coarse ramp that had to be extended."""

import json

import pytest

from icr import config
from icr.analysis import calibrate


def _ramp(root, run_id: str, rates: list[float], first_miss: int | None) -> None:
    """A saved ramp whose levels meet the SLO up to (not including) level `first_miss`."""
    rows = [
        {"phase": "measured", "level": level, "scheduled_s": level * 40 + i, "sent_s": 0.0,
         "end_s": level * 40 + i + 1, "ttft_s": 0.3, "e2e_s": 1.0, "prompt_tokens": 900,
         "itl_s": 0.5 if first_miss is not None and level >= first_miss else 0.03,
         "cached_tokens": 0, "completion_tokens": 60, "error": ""}
        for level in range(len(rates))
        for i in range(10)
    ]  # fmt: skip
    directory = root / run_id
    directory.mkdir()
    (directory / "requests.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    meta = {"ramp": {"rates_rps": rates, "level_s": 40.0, "warmup_s": 30.0}}
    (directory / "meta.json").write_text(json.dumps(meta))


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    return tmp_path


def test_a_coarse_ramp_that_never_missed_gives_no_fine_levels(runs_dir):
    _ramp(runs_dir, "sweep-h100-awq-ramp-chat-cal", [8.0, 12.0, 16.0], None)
    found = calibrate.r_sat("awq", "chat", "h100")
    assert found["r_sat"] == 16.0 and found["first_miss"] is None
    with pytest.raises(ValueError, match="never missed"):
        calibrate.fine_levels(found)


def test_an_extension_ramp_continues_the_coarse_ramp_upwards(runs_dir):
    _ramp(runs_dir, "sweep-h100-awq-ramp-chat-cal", [8.0, 12.0, 16.0], None)
    _ramp(runs_dir, "sweep-h100-awq-ramp-chat-cal2", [24.0, 32.0, 48.0], 2)
    found = calibrate.r_sat("awq", "chat", "h100")
    assert (found["stage"], found["r_sat"], found["first_miss"]) == ("cal2", 32.0, 48.0)
    assert calibrate.fine_levels(found) == [32.0, 35.2, 38.4, 41.6, 44.8, 48.0]


def test_an_extension_whose_first_level_misses_brackets_the_limit_with_the_first_ramp(runs_dir):
    _ramp(runs_dir, "sweep-h100-awq-ramp-chat-cal", [8.0, 12.0, 16.0], None)
    _ramp(runs_dir, "sweep-h100-awq-ramp-chat-cal2", [24.0, 32.0, 48.0], 0)
    found = calibrate.r_sat("awq", "chat", "h100")
    assert (found["r_sat"], found["first_miss"]) == (16.0, 24.0)
    assert calibrate.fine_levels(found)[0] == 16.0 and calibrate.fine_levels(found)[-1] == 24.0


def test_the_fine_ramp_wins_once_it_exists(runs_dir):
    _ramp(runs_dir, "sweep-h100-awq-ramp-chat-cal", [8.0, 12.0, 16.0], None)
    _ramp(runs_dir, "sweep-h100-awq-ramp-chat-cal2", [24.0, 32.0, 48.0], 2)
    _ramp(runs_dir, "sweep-h100-awq-ramp-chat-fine", [32.0, 35.2, 38.4, 41.6, 44.8, 48.0], 4)
    found = calibrate.r_sat("awq", "chat", "h100")
    assert (found["stage"], found["r_sat"]) == ("fine", 41.6)
