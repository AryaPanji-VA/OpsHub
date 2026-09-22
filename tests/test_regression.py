"""Regression tests to verify runtime data files are unchanged after test suite."""
import sys
from pathlib import Path
import json
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import runtime paths
from opshub.agent import TICKETS_FILE


def test_budgets_unchanged():
    """Verify runtime budgets.json is unchanged after tests."""
    budget_file = Path(__file__).parent.parent / "data" / "budgets.json"

    assert budget_file.exists(), "Runtime budget file should exist"

    content = json.loads(budget_file.read_text())

    assert "available" in content
    assert "allocated" in content

    # Should be the user-controlled runtime value (15000000)
    assert content["available"] == 15000000, f"Runtime budget modified: {content}"


def test_schedules_unchanged():
    """Verify runtime schedules.json is unchanged after tests."""
    schedule_file = Path(__file__).parent.parent / "data" / "schedules.json"

    assert schedule_file.exists(), "Runtime schedule file should exist"

    content = json.loads(schedule_file.read_text())

    assert content == [], f"Runtime schedule modified: {content}"


def test_tickets_unchanged():
    """Verify runtime tickets.json is unchanged after tests."""
    assert TICKETS_FILE.exists(), "Runtime tickets file should exist"

    content = json.loads(TICKETS_FILE.read_text())

    assert content == [], f"Runtime tickets modified: {content}"
