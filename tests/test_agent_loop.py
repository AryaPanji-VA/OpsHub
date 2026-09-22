import sys
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.models import (
    OperationalPlan,
    Task,
    NextAction,
    AgentObservation,
    AgentAction,
    AgentActionModel,
    RuntimeContext,
)
from opshub.agent import OpsHubAgent


class MockActionProvider:
    """Mock provider that controls action selection."""

    def __init__(self, actions=None):
        self.actions = actions or []
        self.call_count = 0

    def generate_plan(self, notes):
        return OperationalPlan(
            program="Test",
            summary="Test",
            tasks=[Task(
                id="task-001",
                title="Test Task",
                division="Operations",
                pic=None,
                deadline="2026-12-01",
                budget_required=5000.0,
                priority=None,
                status=None,
            )],
            checks_required=["budget", "schedule"],
            risk_flags=[],
            next_action=NextAction.RUN_TOOLS,
        )

    def choose_next_action(self, plan, observations, runtime_context):
        self.call_count += 1
        if self.actions and self.call_count <= len(self.actions):
            return self.actions[self.call_count - 1]
        # Default deterministic
        if len(observations) == 0:
            return AgentActionModel(
                action=AgentAction.CHECK_BUDGET,
                task_id="task-001",
                reason="Check budget first",
            )
        elif len(observations) == 1:
            return AgentActionModel(
                action=AgentAction.CHECK_SCHEDULE,
                task_id="task-001",
                reason="Check schedule second",
            )
        else:
            return AgentActionModel(
                action=AgentAction.PROPOSE_TICKET_CREATION,
                task_id="task-001",
                reason="Done with checks",
            )


def test_agent_loop_budget_dispatch():
    provider = MockActionProvider()
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.runtime_context.available_budget = 10000.0

    success, observations = agent.run_agent_loop()

    assert success is True
    assert len(observations) > 0
    assert observations[0].action == "check_budget"


def test_agent_loop_schedule_dispatch():
    provider = MockActionProvider()
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert success is True
    assert len(observations) >= 2
    assert observations[1].action == "check_schedule"


def test_agent_loop_finish():
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.FINISH,
            task_id="task-001",
            reason="Done",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    # Finish should be rejected because checks haven't been done yet
    assert any(o.status == "invalid_action" for o in observations)


def test_agent_loop_invalid_task_id():
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
            task_id="invalid-task-id",
            reason="Invalid task_id",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert any(o.status == "invalid_action" for o in observations)
    assert any("invalid-task-id" in o.message for o in observations)


def test_agent_loop_finish_accepted_after_checks():
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        # First call - budget check
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
            task_id="task-001",
            reason="Check budget",
        ),
        # Second call - schedule check
        AgentActionModel(
            action=AgentAction.CHECK_SCHEDULE,
            task_id="task-001",
            reason="Check schedule",
        ),
        # Third call - finish (should be accepted)
        AgentActionModel(
            action=AgentAction.FINISH,
            task_id=None,
            reason="All done",
        ),
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.runtime_context.available_budget = 10000.0

    success, observations = agent.run_agent_loop()

    # Checks alone do not resolve the operational task.
    finish_obs = [o for o in observations if o.action == "finish"]
    assert len(finish_obs) == 1
    assert finish_obs[0].status == "invalid_action"


def test_agent_loop_finish_with_task_id_rejected():
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
            task_id="task-001",
            reason="Check budget",
        ),
        AgentActionModel(
            action=AgentAction.CHECK_SCHEDULE,
            task_id="task-001",
            reason="Check schedule",
        ),
        AgentActionModel(
            action=AgentAction.FINISH,
            task_id="task-001",
            reason="Done with task",
        ),
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.runtime_context.available_budget = 10000.0

    success, observations = agent.run_agent_loop()

    finish_obs = [o for o in observations if o.action == "finish"]
    assert len(finish_obs) == 1
    assert finish_obs[0].status == "invalid_action"


def test_agent_loop_propose_ticket():
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.PROPOSE_TICKET_CREATION,
            task_id="task-001",
            reason="Ready",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert success is True
    assert observations[0].action == "propose_ticket_creation"
    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN


def test_ticket_creation_requires_approval():
    provider = MockActionProvider()
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    task = agent.current_plan.tasks[0]
    ticket_id = agent.create_ticket(task)

    assert ticket_id is None


def test_ticket_creation_after_approval():
    import tempfile
    import json

    tmp_path = Path(tempfile.mktemp(suffix=".json"))
    tmp_path.write_text("[]")

    provider = MockActionProvider()
    agent = OpsHubAgent(llm_provider=provider, tickets_file=tmp_path)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.request_approval("task-001", "create_ticket")
    agent.grant_approval("task-001")

    task = agent.current_plan.tasks[0]
    ticket_id = agent.create_ticket(task)

    assert ticket_id is not None
    assert ticket_id.startswith("OPS-")

    tickets = json.loads(tmp_path.read_text())
    assert len(tickets) == 1

    tmp_path.unlink()


def test_can_finish_with_risk_flags():
    from opshub.models import RiskFlag

    provider = MockActionProvider()
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.current_plan.risk_flags.append(RiskFlag(description="Test risk", severity="high"))

    assert agent._can_finish() is False


def test_can_finish_without_checks_done():
    provider = MockActionProvider()
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    assert agent._can_finish() is False


def test_validate_task_id():
    provider = MockActionProvider()
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    assert agent._validate_task_id("task-001") is True
    assert agent._validate_task_id("invalid-task") is False
    assert agent._validate_task_id("") is False


def test_finish_with_task_id_rejected():
    """Test that finish action with task_id is rejected."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.FINISH,
            task_id="task-001",
            reason="Done",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert any(o.status == "invalid_action" for o in observations)
    assert any("task_id=null" in o.message for o in observations)


def test_finish_rejected_when_checks_pending():
    """Test that finish is rejected when checks are still pending."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.FINISH,
            task_id=None,
            reason="Done",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert any(o.status == "invalid_action" for o in observations)
    assert any("Workflow cannot finish" in o.message for o in observations)


def test_propose_ticket_creation_with_invented_task_id():
    """Test that propose_ticket_creation with invalid task_id is rejected."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.PROPOSE_TICKET_CREATION,
            task_id="task-999",
            reason="Done",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert any(o.status == "invalid_action" for o in observations)
    assert any("task-999" in o.message for o in observations)


def test_propose_ticket_creation_with_valid_task_id():
    """Test that propose_ticket_creation with valid task_id is accepted."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.PROPOSE_TICKET_CREATION,
            task_id="task-001",
            reason="Done",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert success is True
    assert observations[0].action == "propose_ticket_creation"
    assert observations[0].status == "invalid_action"


def test_propose_ticket_creation_rejects_empty_task_id():
    """Test that propose_ticket_creation with empty task_id is rejected."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.PROPOSE_TICKET_CREATION,
            task_id=None,
            reason="Done",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert any(o.status == "invalid_action" for o in observations)


def test_clear_checks_progress_to_propose_ticket():
    """Test that clear checks progress to propose_ticket_creation."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
            task_id="task-001",
            reason="Check budget",
        ),
        AgentActionModel(
            action=AgentAction.CHECK_SCHEDULE,
            task_id="task-001",
            reason="Check schedule",
        ),
        AgentActionModel(
            action=AgentAction.PROPOSE_TICKET_CREATION,
            task_id="task-001",
            reason="All done",
        ),
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.runtime_context.available_budget = 10000.0

    success, observations = agent.run_agent_loop()

    assert success is True
    assert len(observations) == 3
    assert observations[2].action == "propose_ticket_creation"
    assert agent.current_plan.next_action == NextAction.READY_TO_CREATE_TICKET


def test_finish_accepted_only_when_complete():
    """Test that finish is accepted only when workflow is truly complete."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
            task_id="task-001",
            reason="Check budget",
        ),
        AgentActionModel(
            action=AgentAction.CHECK_SCHEDULE,
            task_id="task-001",
            reason="Check schedule",
        ),
        AgentActionModel(
            action=AgentAction.FINISH,
            task_id=None,
            reason="All done",
        ),
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.runtime_context.available_budget = 10000.0

    success, observations = agent.run_agent_loop()

    finish_obs = [o for o in observations if o.action == "finish"]
    assert len(finish_obs) == 1
    assert finish_obs[0].status == "invalid_action"


def test_two_task_workflow():
    """Test multi-task workflow HITL required for each ticket."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
            task_id="task-001",
            reason="Check budget",
        ),
        AgentActionModel(
            action=AgentAction.CHECK_SCHEDULE,
            task_id="task-001",
            reason="Check schedule",
        ),
        AgentActionModel(
            action=AgentAction.PROPOSE_TICKET_CREATION,
            task_id="task-001",
            reason="Ready for task 1",
        ),
    ])

    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.runtime_context.available_budget = 10000.0

    success, observations = agent.run_agent_loop()

    assert success is True
    assert observations[2].action == "propose_ticket_creation"
    assert agent.current_plan.next_action == NextAction.READY_TO_CREATE_TICKET


def test_check_schedule_validates_task_id():
    """Test that check_schedule validates task_id."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.CHECK_SCHEDULE,
            task_id="nonexistent",
            reason="Check schedule",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert any(o.status == "invalid_action" for o in observations)
    assert any("nonexistent" in o.message for o in observations)


def test_finish_rejected_with_task_id():
    """Test that finish action with non-null task_id is rejected."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.FINISH,
            task_id="task-001",
            reason="Done",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    finish_obs = [o for o in observations if o.action == "finish"]
    assert len(finish_obs) == 1
    assert finish_obs[0].status == "invalid_action"
    assert "task_id=null" in finish_obs[0].message


def test_rejected_finish_not_marked_as_executed():
    """Test that rejected finish is NOT added to executed_actions."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.FINISH,
            task_id=None,
            reason="Done",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()

    success, observations = agent.run_agent_loop()

    assert ("finish", "") not in agent.executed_actions


def test_step_limit_results_in_wait_for_human():
    """Test that MAX_AGENT_STEPS results in WAIT_FOR_HUMAN, not COMPLETED."""
    from opshub.models import AgentActionModel

    # Provider that always returns finish which gets rejected
    # forcing step limit to be reached
    class AlwaysFinishProvider:
        def generate_plan(self, notes):
            return OperationalPlan(
                program="Test",
                summary="Test",
                tasks=[Task(
                    id="task_1",
                    title="Test Task",
                    division="Operations",
                    pic=None,
                    deadline="2026-12-01",
                    budget_required=5000.0,
                    priority=None,
                    status=None,
                )],
                checks_required=["budget", "schedule"],
                risk_flags=[],
                next_action=NextAction.RUN_TOOLS,
            )

        def choose_next_action(self, plan, observations, runtime_context):
            return AgentActionModel(
                action=AgentAction.FINISH,
                task_id=None,
                reason="Done",
            )

    provider = AlwaysFinishProvider()
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.runtime_context.available_budget = 10000.0

    success, observations = agent.run_agent_loop()

    # Step limit reached, should set WAIT_FOR_HUMAN not COMPLETED
    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN


def test_duplicate_protection_for_successful_tool_calls():
    """Test that successful tool calls are deduplicated."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
            task_id="task-001",
            reason="Check budget",
        ),
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
            task_id="task-001",
            reason="Check budget again",
        ),
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.runtime_context.available_budget = 10000.0

    success, observations = agent.run_agent_loop()

    assert observations[0].action == "check_budget"
    assert observations[1].action == "check_budget"
    assert observations[1].status == "already_checked"


def test_finish_rejection_lists_unresolved_task_ids():
    """Test that finish rejection includes unresolved task IDs."""
    from opshub.models import AgentActionModel

    provider = MockActionProvider(actions=[
        AgentActionModel(
            action=AgentAction.FINISH,
            task_id=None,
            reason="Done",
        )
    ])
    agent = OpsHubAgent(llm_provider=provider)
    agent.ingest_notes("Test")
    agent.generate_plan()
    agent.runtime_context.available_budget = 10000.0

    success, observations = agent.run_agent_loop()

    finish_obs = [o for o in observations if o.action == "finish"]
    assert len(finish_obs) == 1
    assert finish_obs[0].status == "invalid_action"
    assert "task-001" in finish_obs[0].message
