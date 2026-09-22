"""Trusted per-task check requirements and model-visible check state."""

from typing import Iterable

from opshub.models import AgentObservation, Task


def get_required_checks_for_task(task: Task) -> list[str]:
    """Derive required read-only checks from trusted task fields, not plan labels."""
    checks = []
    if task.budget_required is not None:
        checks.append("budget")
    if task.deadline is not None:
        checks.append("schedule")
    return checks


def get_check_states_for_task(task: Task, observations: Iterable[AgentObservation]) -> dict[str, str]:
    states = {check: "missing" for check in get_required_checks_for_task(task)}
    for observation in observations:
        if observation.task_id != task.id or not observation.action.startswith("check_"):
            continue
        check = observation.action.removeprefix("check_")
        if check in states and observation.status in {"clear", "failed", "missing_context"}:
            states[check] = observation.status
    return states


def format_task_check_context(tasks: Iterable[Task], observations: Iterable[AgentObservation]) -> str:
    """Give either provider the same per-task state and valid next checks."""
    observations = list(observations)
    lines = []
    for task in tasks:
        states = get_check_states_for_task(task, observations)
        summary = ", ".join(f"{check}: {status}" for check, status in states.items()) or "none required"
        remaining = ", ".join(
            f"check_{check} {task.id}" for check, status in states.items() if status == "missing"
        ) or "none"
        lines.append(f"- {task.id}: {summary}; remaining read-only checks: {remaining}")
    return "\n".join(lines) or "No tasks"
