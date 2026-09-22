import sys
from pathlib import Path
from unittest.mock import Mock, patch
import tempfile
import json
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.models import OperationalPlan, Task, RiskFlag, NextAction, Approval, ApprovalStatus
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
            checks_required=["budget"],
            risk_flags=[],
            next_action=NextAction.RUN_TOOLS,
        )


def test_ticket_requires_approval():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.run_checks()

    task = agent.current_plan.tasks[0]

    ticket_id = agent.create_ticket(task)

    assert ticket_id is None


def test_ticket_created_after_approval():
    tmp_path = Path(tempfile.mktemp(suffix=".json"))
    tmp_path.write_text("[]")

    agent = OpsHubAgent(llm_provider=MockProvider(), tickets_file=tmp_path)
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.run_checks()

    task = agent.current_plan.tasks[0]
    agent.request_approval(task.id, "create_ticket")
    agent.grant_approval(task.id)

    ticket_id = agent.create_ticket(task)

    assert ticket_id is not None
    assert ticket_id.startswith("OPS-")

    tickets = json.loads(tmp_path.read_text())
    assert len(tickets) == 1

    tmp_path.unlink()


def test_rejected_approval_blocks_ticket():
    tmp_path = Path(tempfile.mktemp(suffix=".json"))
    tmp_path.write_text("[]")

    agent = OpsHubAgent(llm_provider=MockProvider(), tickets_file=tmp_path)
    agent.ingest_notes("Test notes")
    agent.generate_plan()

    task = agent.current_plan.tasks[0]
    agent.request_approval(task.id, "create_ticket")
    agent.reject_approval(task.id)

    ticket_id = agent.create_ticket(task)

    assert ticket_id is None

    tmp_path.unlink()


def test_audit_logs_approval_events():
    tmp_path = Path(tempfile.mktemp(suffix=".json"))
    tmp_path.write_text("[]")

    agent = OpsHubAgent(llm_provider=MockProvider(), tickets_file=tmp_path)
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.run_checks()

    task = agent.current_plan.tasks[0]
    agent.request_approval(task.id, "create_ticket")
    agent.grant_approval(task.id)

    events = [e["event"] for e in agent.audit_log.get_all()]

    assert "approval_requested" in events
    assert "approval_granted" in events

    tmp_path.unlink()


def test_exception_approval_keeps_risk_flag():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.ingest_notes("Test notes")
    agent.generate_plan()

    mock_results = {
        "budget": [Mock(success=False, task_id="task-001")],
        "schedule": [],
    }
    agent.update_plan_with_results(mock_results, True, ["Budget insufficient"])

    agent.grant_approval("task-001", exception=True)

    assert len(agent.current_plan.risk_flags) > 0


def test_has_pending_approval():
    agent = OpsHubAgent()
    agent.request_approval("task-001", "create_ticket")

    assert agent.has_pending_approval("task-001") is True
    assert agent.has_pending_approval("task-002") is False


def test_has_approved_approval():
    agent = OpsHubAgent()
    agent.request_approval("task-001", "create_ticket")
    agent.grant_approval("task-001")

    assert agent.has_approved_approval("task-001") is True
    assert agent.has_approved_approval("task-002") is False


def test_rejection_marks_as_rejected():
    agent = OpsHubAgent()
    agent.request_approval("task-001", "create_ticket")
    agent.reject_approval("task-001")

    approval = agent.approvals[0]
    assert approval.status == ApprovalStatus.REJECTED


def test_multi_task_per_task_approval():
    agent = OpsHubAgent(llm_provider=MockProvider())
    agent.current_plan = OperationalPlan(
        program="Test",
        summary="Test",
        tasks=[
            Task(id="task-001", title="Task 1", division=None, pic=None, deadline=None, budget_required=None, priority=None, status=None),
            Task(id="task-002", title="Task 2", division=None, pic=None, deadline=None, budget_required=None, priority=None, status=None),
        ],
        checks_required=[],
        risk_flags=[],
        next_action=NextAction.READY_TO_CREATE_TICKET,
    )

    agent.request_approval("task-001", "create_ticket")
    agent.request_approval("task-002", "create_ticket")
    agent.grant_approval("task-001")

    assert agent.has_approved_approval("task-001") is True
    assert agent.has_approved_approval("task-002") is False


def test_audit_logs_ticket_created():
    tmp_path = Path(tempfile.mktemp(suffix=".json"))
    tmp_path.write_text("[]")

    agent = OpsHubAgent(llm_provider=MockProvider(), tickets_file=tmp_path)
    agent.ingest_notes("Test notes")
    agent.generate_plan()
    agent.run_checks()

    task = agent.current_plan.tasks[0]
    agent.request_approval(task.id, "create_ticket")
    agent.grant_approval(task.id)
    agent.create_ticket(task)

    events = [e["event"] for e in agent.audit_log.get_all()]

    assert "ticket_created" in events

    tmp_path.unlink()
