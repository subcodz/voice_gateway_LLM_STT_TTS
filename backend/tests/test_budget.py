"""Tests for budget tracker and credit enforcement."""

import os
import pytest
from app.budget import BudgetTracker, BudgetExceededError, KillSwitchActiveError


@pytest.fixture
def budget_tracker(tmp_path):
    db_file = str(tmp_path / "test_budget.db")
    return BudgetTracker(db_path=db_file)


def test_budget_reservation_and_spend(budget_tracker):
    # Probe bucket default cap is 900 chars
    budget_tracker.reserve("probe", 500)
    status = budget_tracker.get_status()
    assert status["probe"]["chars_spent"] == 500

    # Reserving additional 300 (total 800 <= 900) succeeds
    budget_tracker.reserve("probe", 300)
    status = budget_tracker.get_status()
    assert status["probe"]["chars_spent"] == 800


def test_budget_refusal_when_exceeded(budget_tracker):
    # Probe bucket cap is 900. Requesting 1000 should raise BudgetExceededError
    with pytest.raises(BudgetExceededError) as exc_info:
        budget_tracker.reserve("probe", 1000)
    assert "Budget exceeded" in str(exc_info.value)

    # Verify spent chars remained 0
    status = budget_tracker.get_status()
    assert status["probe"]["chars_spent"] == 0


def test_budget_kill_switch_refusal(budget_tracker):
    with pytest.raises(KillSwitchActiveError):
        budget_tracker.reserve("probe", 100, kill_switch=True)


def test_budget_refund(budget_tracker):
    budget_tracker.reserve("probe", 400)
    assert budget_tracker.get_status()["probe"]["chars_spent"] == 400

    budget_tracker.refund("probe", 150)
    assert budget_tracker.get_status()["probe"]["chars_spent"] == 250
