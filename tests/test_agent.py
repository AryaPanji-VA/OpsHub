import sys
from pathlib import Path
from unittest.mock import Mock
import tempfile
import json
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.models import OperationalPlan, Task, RiskFlag, NextAction
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
                    division="Operations",
                    pic="Alice",
                    deadline="2026-12-01",
                    budget_required=5000000.0,
                    priority="medium",
                    status=None,
                ),
            ],
            checks_required=["budget", "schedule"],
            risk_flags=[],
            next_action=NextAction.RUN_TOOLS,
        )


def test_agent_generates_plan():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    plan = agent.generate_plan()

    assert plan.program == "Test Program"
    assert agent.current_plan is not None


def test_agent_runs_budget_check():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()

    results = agent.run_checks()

    assert "budget" in results
    assert len(results["budget"]) == 1
    assert results["budget"][0].task_id == "task-001"


def test_agent_runs_schedule_check():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()

    results = agent.run_checks()

    assert "schedule" in results
    assert len(results["schedule"]) == 1
    assert results["schedule"][0].task_id == "task-001"


def test_agent_policy_no_conflict():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    # Set sufficient budget context
    agent.set_budget(15000000)
    results = agent.run_checks()

    requires_approval, reasons = agent.evaluate_policy(results)

    assert requires_approval is False
    assert len(reasons) == 0


def test_agent_policy_budget_insufficient():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()

    mock_results = {
        "budget": [
            Mock(success=False, status="insufficient", task_id="task-001", message="Insufficient")
        ],
        "schedule": [],
    }
    requires_approval, reasons = agent.evaluate_policy(mock_results)

    assert requires_approval is True
    assert len(reasons) == 1


def test_agent_policy_schedule_conflict():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()

    mock_results = {
        "budget": [],
        "schedule": [
            Mock(success=False, status="conflict", task_id="task-001", message="Conflict")
        ],
    }
    requires_approval, reasons = agent.evaluate_policy(mock_results)

    assert requires_approval is True
    assert "schedule" in reasons[0].lower()


def test_agent_updates_plan_on_conflict():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()

    mock_results = {
        "budget": [Mock(success=False, task_id="task-001")],
        "schedule": [],
    }
    agent.update_plan_with_results(mock_results, True, ["Budget insufficient"])

    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
    assert len(agent.current_plan.risk_flags) > 0


def test_agent_updates_plan_no_conflict():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()

    mock_results = {
        "budget": [Mock(success=True, task_id="task-001")],
        "schedule": [],
    }
    agent.update_plan_with_results(mock_results, False, [])

    assert agent.current_plan.next_action == NextAction.READY_TO_CREATE_TICKET


def test_agent_audit_log_records_tool_results():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.run_checks()

    tool_results = [e for e in agent.audit_log.get_all() if e["event"] == "tool_result"]

    assert len(tool_results) > 0


def test_agent_audit_log_records_conflicts():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()

    mock_results = {"budget": [Mock(success=False, task_id="task-001")], "schedule": []}
    agent.update_plan_with_results(mock_results, True, ["Budget insufficient"])

    conflicts = [e for e in agent.audit_log.get_all() if e["event"] == "conflict_detected"]

    assert len(conflicts) > 0
