import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.models import Task, OperationalPlan, RiskFlag, NextAction, TaskStatus


def test_task_creation():
    task = Task(
        id="t1",
        title="Test",
        division=None,
        pic=None,
        deadline=None,
        budget_required=None,
        priority=None,
        status=None,
    )
    assert task.title == "Test"
    assert task.division is None


def test_plan_creation():
    plan = OperationalPlan(
        program="Test",
        summary="Test",
        tasks=[],
        checks_required=[],
        risk_flags=[],
        next_action=NextAction.WAIT_FOR_HUMAN,
    )
    assert plan.program == "Test"
    assert len(plan.tasks) == 0


def test_task_with_none_fields():
    task = Task(
        id="t2",
        title="Task with nulls",
        division=None,
        pic=None,
        deadline=None,
        budget_required=None,
        priority=None,
        status=None,
    )
    assert task.budget_required is None


def test_next_action_values():
    assert NextAction.RUN_TOOLS.value == "run_tools"
    assert NextAction.WAIT_FOR_HUMAN.value == "wait_for_human"
