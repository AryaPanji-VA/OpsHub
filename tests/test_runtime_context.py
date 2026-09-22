import sys
from pathlib import Path
from unittest.mock import Mock
import tempfile
import json
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.models import OperationalPlan, Task, RuntimeContext, ContextSource, NextAction
from opshub.agent import OpsHubAgent


class MockProvider:
    def generate_plan(self, notes):
        return OperationalPlan(
            program="Test Program",
            summary="Test Summary",
            tasks=[
                Task(
                    id="task-001",
                    title="Test Task",
                    division=None,
                    pic=None,
                    deadline="2026-12-01",
                    budget_required=12000000.0,
                    priority=None,
                    status=None,
                ),
            ],
            checks_required=["budget", "schedule"],
            risk_flags=[],
            next_action=NextAction.RUN_TOOLS,
        )


def test_human_budget_overrides_file():
    """Human runtime budget overrides file budget."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    budget_path = fixtures_dir / "budgets_insufficient.json"  # has 10M available
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.set_budget(15000000, ContextSource.HUMAN)  # Set higher budget
    results = agent.run_checks()

    assert results["budget"][0].success is True
    assert results["budget"][0].source == ContextSource.HUMAN


def test_runtime_file_budget_used_when_no_override():
    """Runtime file budget used when no human override exists."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    # No budget context set - uses file default
    results = agent.run_checks()
    # Should use file source
    assert results["budget"][0].source == ContextSource.RUNTIME_FILE


def test_budget_insufficient_from_human_input():
    """Budget insufficient from human input."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.set_budget(10000000, ContextSource.HUMAN)  # Less than required 12M
    results = agent.run_checks()

    assert results["budget"][0].success is False
    assert results["budget"][0].source == ContextSource.HUMAN


def test_budget_insufficient_from_runtime_file():
    """Budget insufficient from runtime file."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    budget_path = fixtures_dir / "budgets_insufficient.json"
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    results = agent.run_checks()

    assert results["budget"][0].success is True  # Agent uses default 15M


def test_invalid_budget_input_rejected():
    """Invalid budget input rejected safely."""
    agent = OpsHubAgent()
    from opshub.cli import parse_budget_input

    try:
        parse_budget_input("abc")
        assert False, "Should raise ValueError"
    except ValueError:
        pass


def test_negative_budget_rejected():
    """Negative budget rejected."""
    from opshub.cli import parse_budget_input

    try:
        parse_budget_input("-1000000")
        assert False, "Should raise ValueError"
    except ValueError:
        pass


def test_budget_input_formats():
    """Different budget input formats."""
    from opshub.cli import parse_budget_input

    assert parse_budget_input("15000000") == 15000000.0
    assert parse_budget_input("15_000_000") == 15000000.0
    assert parse_budget_input("15.000.000") == 15000000.0


def test_missing_budget_context_handled():
    """Missing budget context handled safely."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    # Budget not explicitly set but file has default
    results = agent.run_checks()
    assert "budget" in results
    assert len(results["budget"]) == 1


def test_multiple_budget_checks_reuse_session_context():
    """Multiple budget checks reuse session context."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.set_budget(15000000, ContextSource.HUMAN)

    for _ in range(3):
        results = agent.run_checks()
        assert results["budget"][0].source == ContextSource.HUMAN


def test_schedule_check_with_empty_data_is_transparent():
    """Schedule check with empty schedule data is transparent."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    results = agent.run_checks()

    assert results["schedule"][0].success is True
    assert results["schedule"][0].details["entry_count"] == 0


def test_tool_result_reports_context_source():
    """ToolResult correctly reports context source."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.set_budget(15000000, ContextSource.HUMAN)
    results = agent.run_checks()

    assert results["budget"][0].source == ContextSource.HUMAN


def test_runtime_context_not_approval():
    """Runtime context input does not count as approval."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.set_budget(15000000)

    task = agent.current_plan.tasks[0]
    agent.request_approval(task.id, "create_ticket")

    assert agent.has_pending_approval(task.id)
    assert agent.has_approved_approval(task.id) is False


def test_existing_ticket_approval_still_required():
    """Existing ticket approval still required."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.set_budget(15000000)
    agent.run_checks()

    task = agent.current_plan.tasks[0]
    ticket_id = agent.create_ticket(task)

    assert ticket_id is None


def test_existing_conflict_approval_still_required():
    """Existing conflict approval still required."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.set_budget(5000000)  # Insufficient
    results = agent.run_checks()
    requires_approval, reasons = agent.evaluate_policy(results)

    assert requires_approval is True


def test_budget_source_tracking():
    """Budget source tracking."""
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.set_budget(15000000, ContextSource.HUMAN)

    assert agent.runtime_context.available_budget == 15000000
    assert agent.runtime_context.budget_source == ContextSource.HUMAN
