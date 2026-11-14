"""The frozen fleet run list: load levels, interleaved order, identical traffic per policy."""

import pytest

from icr.fleet import plan
from icr.modal_app import fleet
from icr.routing.policy import POLICIES

CALIB = {"r_sat": {"chat": 3.0, "rag": 1.5, "no-sharing": 2.0, "agentic": 1.0}}


def test_fixed_runs_use_70_percent_of_fleet_capacity():
    runs = plan.runs_for("rag", CALIB)
    assert len(runs) == 9
    assert {r["rate_rps"] for r in runs} == {round(0.7 * 4 * 1.5, 2)}
    assert all(r["warmup_s"] == 60 and r["measured_s"] == 180 for r in runs)


def test_every_repeat_runs_all_policies_in_a_rotated_order():
    runs = plan.runs_for("chat", CALIB)
    by_seed = [[r["policy"] for r in runs if r["seed"] == s] for s in plan.SEEDS]
    assert all(sorted(order) == sorted(POLICIES) for order in by_seed)
    assert len({order[0] for order in by_seed}) == 3  # each policy goes first once


def test_ramp_levels_are_multiples_of_four_replicas():
    runs = plan.runs_for("ramp", CALIB)
    assert len(runs) == 6 and {r["seed"] for r in runs} == {0, 1}
    assert runs[0]["rates_rps"] == [7.2, 9.0, 10.8, 12.6, 14.4, 16.2]


def test_autoscale_compares_static_and_autoscaled_on_the_bursty_segment():
    runs = plan.runs_for("autoscale", CALIB)
    assert [r["policy"] for r in runs[:2]] == ["static", "autoscaled"]
    assert sorted(r["policy"] for r in runs) == ["autoscaled"] * 3 + ["static"] * 3
    assert all(r["segment"] == "bursty" and r["rate_rps"] == 3.0 for r in runs)
    assert len({r["router_policy"] for r in runs}) == 1


def test_unknown_item_is_rejected():
    with pytest.raises(ValueError):
        plan.runs_for("nope", CALIB)


def test_run_ids_are_unique_across_the_whole_plan():
    runs = [r for item in plan.ITEMS for r in plan.runs_for(item, CALIB)]
    ids = [fleet.run_id(r) for r in runs]
    assert len(ids) == len(set(ids))


def test_policies_of_one_repeat_get_identical_traffic():
    a, b, _ = (r for r in plan.runs_for("chat", CALIB) if r["seed"] == 1)
    assert a["policy"] != b["policy"]
    short = {"warmup_s": 2.0, "measured_s": 6.0}
    specs_a, specs_b = fleet.build_specs({**a, **short}), fleet.build_specs({**b, **short})
    assert [s.to_dict() for s in specs_a] == [s.to_dict() for s in specs_b]
    assert {s.phase for s in specs_a} == {"warmup", "measured"}


def test_planned_seconds_cover_warmup_and_every_level():
    ramp = plan.runs_for("ramp", CALIB)[0]
    assert fleet.planned_seconds(ramp) == 60 + 6 * 60
    assert fleet.planned_seconds(plan.runs_for("chat", CALIB)[0]) == 240
    specs = fleet.build_specs({**ramp, "warmup_s": 2.0, "level_s": 2.0})
    assert sorted({s.level for s in specs if s.phase == "measured"}) == [0, 1, 2, 3, 4, 5]
