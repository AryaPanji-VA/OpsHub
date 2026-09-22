import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.tools.budget import check_budget
from opshub.tools.schedule import check_schedule


def test_budget_check_safe():
    """Test with safe budget fixture."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    budget_path = fixtures_dir / "budgets_safe.json"

    ok, msg, source = check_budget(5000000, data_path=budget_path)
    assert ok is True


def test_budget_check_insufficient():
    """Test with insufficient budget fixture."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    budget_path = fixtures_dir / "budgets_insufficient.json"

    ok, msg, source = check_budget(3000000, data_path=budget_path)
    assert ok is False


def test_budget_explicit_value():
    """Test with explicit available value."""
    ok, msg, source = check_budget(5000000, available=15000000)
    assert ok is True
    assert source.value == "human"


def test_schedule_check_clear():
    """Test with clear schedule fixture."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    schedule_path = fixtures_dir / "schedules_clear.json"

    ok, msg, count, source = check_schedule("New Event", "2026-12-01", data_path=schedule_path)
    assert ok is True
    assert count == 0


def test_schedule_check_conflict():
    """Test with conflict schedule fixture."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    schedule_path = fixtures_dir / "schedules_conflict.json"

    ok, msg, count, source = check_schedule("New Event", "2026-12-01", data_path=schedule_path)
    assert ok is False
