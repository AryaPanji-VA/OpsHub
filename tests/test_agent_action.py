import sys
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.models import (
    OperationalPlan,
    Task,
    AgentActionModel,
    AgentAction,
    AgentObservation,
    RuntimeContext,
    NextAction,
)
from opshub.llm.mock import MockLLMProvider
from opshub.llm.exceptions import RecoverableLLMError


def test_agent_action_model_valid():
    action = AgentActionModel(
        action=AgentAction.CHECK_BUDGET,
        task_id="task-001",
        reason="Need to check budget",
    )
    assert action.action == AgentAction.CHECK_BUDGET
    assert action.task_id == "task-001"


def test_agent_action_model_unknown_action():
    from pydantic import ValidationError

    try:
        AgentActionModel(
            action="unknown_action",  # type: ignore
            task_id="task-001",
            reason="Test",
        )
        assert False, "Should raise ValidationError"
    except ValidationError:
        pass


def test_agent_action_model_task_id_required():
    from pydantic import ValidationError

    try:
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
            reason="Test",
        )
        assert False, "Should raise ValidationError"
    except ValidationError:
        pass


def test_agent_action_model_task_id_accepts_none():
    action = AgentActionModel(
        action=AgentAction.CHECK_BUDGET,
        task_id=None,
        reason="Test",
    )
    assert action.task_id is None


def test_agent_action_schema_has_all_required():
    schema = AgentActionModel.model_json_schema()
    required = set(schema.get("required", []))
    properties = set(schema.get("properties", {}).keys())

    assert required == properties
    assert "action" in required
    assert "task_id" in required
    assert "reason" in required


def test_agent_action_model_missing_fields():
    from pydantic import ValidationError

    try:
        AgentActionModel(
            action=AgentAction.CHECK_BUDGET,
        )
        assert False, "Should raise ValidationError"
    except ValidationError:
        pass


def test_observation_model():
    obs = AgentObservation(
        action="check_budget",
        task_id="task-001",
        status="clear",
        message="Budget sufficient",
        details={"required": 5000, "available": 10000},
    )
    assert obs.status == "clear"


def test_mock_action_selection_budget():
    provider = MockLLMProvider()
    plan = OperationalPlan(
        program="Test",
        summary="Test",
        tasks=[Task(
            id="task-001",
            title="Test",
            division=None,
            pic=None,
            deadline=None,
            budget_required=5000.0,
            priority=None,
            status=None,
        )],
        checks_required=["budget"],
        risk_flags=[],
        next_action=NextAction.RUN_TOOLS,
    )
    action = provider.choose_next_action(plan, [], RuntimeContext())
    assert action.action == AgentAction.CHECK_BUDGET


def test_mock_action_selection_schedule():
    provider = MockLLMProvider()
    plan = OperationalPlan(
        program="Test",
        summary="Test",
        tasks=[Task(
            id="task-001",
            title="Test",
            division=None,
            pic=None,
            deadline="2026-12-01",
            budget_required=None,
            priority=None,
            status=None,
        )],
        checks_required=["schedule"],
        risk_flags=[],
        next_action=NextAction.RUN_TOOLS,
    )
    # After budget checked
    observations = [AgentObservation(
        action="check_budget",
        task_id="task-001",
        status="clear",
        message="OK",
    )]
    action = provider.choose_next_action(plan, observations, RuntimeContext())
    assert action.action == AgentAction.CHECK_SCHEDULE


def test_mock_action_selection_propose():
    provider = MockLLMProvider()
    # Simulate after checks done
    observations = [
        AgentObservation(action="check_budget", task_id="task-001", status="clear", message=""),
        AgentObservation(action="check_schedule", task_id="task-001", status="clear", message=""),
    ]
    plan = OperationalPlan(
        program="Test",
        summary="Test",
        tasks=[Task(
            id="task-001",
            title="Test",
            division=None,
            pic=None,
            deadline=None,
            budget_required=None,
            priority=None,
            status=None,
        )],
        checks_required=[],
        risk_flags=[],
        next_action=NextAction.RUN_TOOLS,
    )
    action = provider.choose_next_action(plan, observations, RuntimeContext())
    assert action.action == AgentAction.PROPOSE_TICKET_CREATION
