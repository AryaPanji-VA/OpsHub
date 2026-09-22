import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.policy import check_ticket_policy
from opshub.policy import check_budget_policy, check_schedule_policy


def test_ticket_policy_requires_approval():
    result = check_ticket_policy()
    assert result.requires_approval is True


def test_read_only_policies_accept_tool_result_shape(monkeypatch, tmp_path):
    budget_file = tmp_path / "budgets.json"
    budget_file.write_text('{"available": 100, "allocated": 0}')
    schedule_file = tmp_path / "schedules.json"
    schedule_file.write_text('[]')
    monkeypatch.setattr("opshub.tools.budget.DATA_FILE", budget_file)
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", schedule_file)
    assert check_budget_policy(50).requires_approval is False
    assert check_schedule_policy("Event", "2026-12-01").requires_approval is False
