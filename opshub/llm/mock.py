from typing import List

from opshub.models import (
    OperationalPlan,
    Task,
    AgentActionModel,
    AgentAction,
    AgentObservation,
    RuntimeContext,
    NextAction,
)
from opshub.llm.base import LLMProvider
from opshub.checks import get_check_states_for_task


class MockLLMProvider(LLMProvider):
    """Mock provider for testing and development."""

    def __init__(self):
        self.step = 0

    def generate_plan(self, meeting_notes: str) -> OperationalPlan:
        return OperationalPlan(
            program="Grand Summit 2026",
            summary="Annual tech conference planning",
            tasks=[
                Task(
                    id="task-001",
                    title="Book venue",
                    division="Operations",
                    pic="Alice Chen",
                    deadline="2026-10-15",
                    budget_required=5000.0,
                    priority="high",
                    status=None,
                )
            ],
            checks_required=["budget", "schedule"],
            risk_flags=[],
            next_action=NextAction.RUN_TOOLS,
        )

    def choose_next_action(
        self,
        plan: OperationalPlan,
        observations: List[AgentObservation],
        runtime_context: RuntimeContext,
    ) -> AgentActionModel:
        """Deterministic mock action selection."""
        self.step += 1

        has_conflict = any(o.status in {"failed", "missing_context"} for o in observations)
        if has_conflict:
            return AgentActionModel(
                action=AgentAction.REQUEST_HUMAN_REVIEW,
                task_id=None,
                reason="Conflict detected that requires human review.",
            )

        for task in plan.tasks:
            if any(o.action == "ticket_created" and o.task_id == task.id for o in observations):
                continue
            for check, status in get_check_states_for_task(task, observations).items():
                if status == "missing":
                    return AgentActionModel(
                        action=AgentAction(f"check_{check}"), task_id=task.id,
                        reason=f"{check} check has not been performed yet.",
                    )
            return AgentActionModel(
                action=AgentAction.PROPOSE_TICKET_CREATION, task_id=task.id,
                reason="All required read-only checks completed.",
            )

        return AgentActionModel(
            action=AgentAction.FINISH,
            task_id=None,
            reason="Workflow complete.",
        )
