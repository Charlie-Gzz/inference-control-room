"""The budget guard refuses runs that could break a cap."""

import pytest

from icr import config, ledger


@pytest.fixture
def empty_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_JSONL", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(ledger, "LEDGER_MD", tmp_path / "GPU_LEDGER.md")


def spend(category: str, dollars: float) -> None:
    seconds = dollars / config.hourly_cost("L4", 1, 0, 0) * 3600 - ledger.STARTUP_ALLOWANCE_S
    ledger.record(
        purpose="test", category=category, gpu="L4", gpu_count=1, cpu=0, memory_gib=0,
        container_seconds=seconds,
    )  # fmt: skip


def test_cost_formula_adds_gpu_cpu_and_memory():
    assert config.hourly_cost("L4", 4, 10, 48) == pytest.approx(3.2 + 0.473 + 0.384)
    assert config.hourly_cost("H100!", 1, 0, 0) == 3.95


def test_record_accumulates_and_renders(empty_ledger):
    spend("dev", 1.0)
    spend("fleet", 2.0)
    assert ledger.spent() == pytest.approx(3.0, abs=0.01)
    assert ledger.spent("dev") == pytest.approx(1.0, abs=0.01)
    text = ledger.LEDGER_MD.read_text("utf-8")
    assert "| 3.000 |" in text and "fleet: $2.00 of $18.00" in text


def test_actual_cost_replaces_the_estimate_once_known(empty_ledger, monkeypatch):
    spend("dev", 1.0)
    row = ledger.rows()[0] | {"app_id": "ap-1"}
    ledger._write([row])
    monkeypatch.setattr(ledger, "billing_by_app", lambda period: {"ap-1": 0.4, "ap-other": 9.0})
    ledger.reconcile()
    assert ledger.spent() == 0.4
    assert "| 1.000 | 0.400 | 0.400 |" in ledger.LEDGER_MD.read_text("utf-8")


def test_dev_cap_blocks_development_runs(empty_ledger):
    spend("dev", 9.9)
    with pytest.raises(ledger.BudgetError, match="dev cap"):
        ledger.check_budget("dev", "L4", 1, 4, 16, max_seconds=1800)


def test_fleet_reserve_is_separate_from_dev(empty_ledger):
    spend("dev", 9.9)
    assert ledger.check_budget("fleet", "L4", 4, 10, 48, max_seconds=3600) > 4.0


def test_total_cap_is_a_hard_stop(empty_ledger):
    spend("dev", 9.0)
    spend("fleet", 17.0)
    spend("h100", 6.5)
    with pytest.raises(ledger.BudgetError, match="total cap"):
        ledger.check_budget("fleet", "L4", 4, 10, 48, max_seconds=3600)


def test_soft_stop_ends_development_runs(empty_ledger):
    spend("fleet", 17.5)
    spend("h100", 6.9)
    spend("dev", 4.0)
    with pytest.raises(ledger.BudgetError, match="soft stop"):
        ledger.check_budget("dev", "L4", 1, 4, 16, max_seconds=60)
