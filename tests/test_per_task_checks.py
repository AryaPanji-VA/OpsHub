"""Per-task ReAct check state and provider context."""

import json
from unittest.mock import Mock, patch

import pytest

from opshub.agent import OpsHubAgent
from opshub.checks import format_task_check_context, get_required_checks_for_task
from opshub.models import (AgentAction, AgentActionModel, AgentObservation, NextAction,
                           OperationalPlan, RuntimeContext, Task)


def task(task_id, budget=None, deadline=None):
    return Task(id=task_id, title=task_id, division=None, pic=None, deadline=deadline,
                budget_required=budget, priority=None, status=None)


def plan(*tasks):
    return OperationalPlan(program="Test", summary="Test", tasks=list(tasks),
                           checks_required=["budget", "schedule"], risk_flags=[],
                           next_action=NextAction.RUN_TOOLS)


def obs(check, task_id, status="clear"):
    return AgentObservation(action=f"check_{check}", task_id=task_id,
                            status=status, message="test")


def act(name, task_id=None):
    return AgentActionModel(action=AgentAction(name), task_id=task_id, reason="test")


class SequenceProvider:
    def __init__(self, current_plan, actions):
        self.current_plan = current_plan
        self.actions = iter(actions)

    def generate_plan(self, notes):
        return self.current_plan

    def choose_next_action(self, plan, observations, runtime_context):
        return next(self.actions, act("request_human_review"))


def agent_for(current_plan, actions):
    agent = OpsHubAgent(llm_provider=SequenceProvider(current_plan, actions))
    agent.ingest_notes("test")
    agent.generate_plan()
    return agent


@pytest.mark.parametrize("budget,deadline,required", [
    (12_000_000, None, ["budget"]),
    (None, "2026-10-15", ["schedule"]),
    (12_000_000, "2026-10-15", ["budget", "schedule"]),
])
def test_requirements_derive_from_each_task_not_global_list(budget, deadline, required):
    assert get_required_checks_for_task(task("task_1", budget, deadline)) == required


def test_another_tasks_schedule_does_not_satisfy_task_one():
    current_plan = plan(task("task_1", 12_000_000, "2026-10-15"),
                        task("task_2", None, "2026-10-15"))
    agent = agent_for(current_plan, [])
    agent.observations = [obs("budget", "task_1"), obs("schedule", "task_2")]
    assert agent.get_missing_checks_for_task("task_1") == ["schedule"]
    assert agent.get_missing_checks_for_task("task_2") == []


def test_proposal_allowed_after_only_own_required_check():
    agent = agent_for(plan(task("task_1", 12_000_000),
                           task("task_2", None, "2026-10-15")),
                      [act("propose_ticket_creation", "task_1")])
    agent.observations = [obs("budget", "task_1")]
    _, observations = agent.run_agent_loop()
    assert observations[-1].status == "ready"
    assert agent.current_plan.next_action == NextAction.READY_TO_CREATE_TICKET


def test_proposal_rejection_lists_exact_missing_check():
    agent = agent_for(plan(task("task_1", 12_000_000, "2026-10-15")),
                      [act("propose_ticket_creation", "task_1"),
                       act("request_human_review")])
    agent.observations = [obs("budget", "task_1")]
    _, observations = agent.run_agent_loop()
    assert observations[1].status == "invalid_action"
    assert observations[1].message == (
        "task_1 is not ready for ticket creation. Missing checks: schedule.")
    assert observations[1].details["missing_checks"] == ["schedule"]


def test_reported_two_task_sequence_recovers_with_task_one_schedule(monkeypatch, tmp_path):
    current_plan = plan(task("task_1", 12_000_000, "2026-10-15"),
                        task("task_2", None, "2026-10-15"))
    agent = agent_for(current_plan, [act("check_budget", "task_1"),
                                     act("check_schedule", "task_2"),
                                     act("propose_ticket_creation", "task_1"),
                                     act("check_schedule", "task_1"),
                                     act("propose_ticket_creation", "task_1")])
    agent.set_budget(15_000_000)
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedule.json")
    _, observations = agent.run_agent_loop()
    assert [o.status for o in observations] == [
        "clear", "clear", "invalid_action", "clear", "ready"]
    assert observations[2].message.endswith("Missing checks: schedule.")
    assert agent.current_plan.next_action == NextAction.READY_TO_CREATE_TICKET


def test_context_shows_per_task_clear_and_missing_checks():
    context = format_task_check_context(
        [task("task_1", 12_000_000, "2026-10-15"),
         task("task_2", None, "2026-10-15")],
        [obs("budget", "task_1"), obs("schedule", "task_2")],
    )
    assert "task_1: budget: clear, schedule: missing" in context
    assert "remaining read-only checks: check_schedule task_1" in context
    assert "task_2: schedule: clear; remaining read-only checks: none" in context


def test_repeat_check_and_review_do_not_preempt_remaining_read_only_check(monkeypatch, tmp_path):
    current_plan = plan(task("task_1", 12_000_000, "2026-10-15"))
    agent = agent_for(current_plan, [act("check_budget", "task_1"),
                                     act("request_human_review"),
                                     act("check_schedule", "task_1"),
                                     act("propose_ticket_creation", "task_1")])
    agent.observations = [obs("budget", "task_1")]
    agent.executed_actions[("check_budget", "task_1")] = 1
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedule.json")
    _, observations = agent.run_agent_loop()
    assert observations[1].status == "already_checked"
    assert "check_schedule task_1" in observations[1].message
    assert observations[2].status == "invalid_action"
    assert "check_schedule task_1" in observations[2].message
    assert observations[3].action == "check_schedule" and observations[3].status == "clear"
    assert observations[4].action == "propose_ticket_creation" and observations[4].status == "ready"


def test_qwen_prompt_contains_per_task_state(monkeypatch):
    from opshub.llm.qwen import QwenProvider
    monkeypatch.setenv("GROQ_API_KEY", "test")
    response = Mock()
    response.choices = [Mock(message=Mock(content=json.dumps(
        {"action": "check_schedule", "task_id": "task_1", "reason": "missing"})))]
    with patch("groq.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = response
        QwenProvider().choose_next_action(
            plan(task("task_1", 12_000_000, "2026-10-15")),
            [obs("budget", "task_1")], RuntimeContext())
        prompt = groq.return_value.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "budget: clear, schedule: missing" in prompt
    assert "check_schedule task_1" in prompt


def test_nex_prompt_contains_per_task_state(monkeypatch):
    from opshub.llm.nex import NexProvider
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": json.dumps(
        {"action": "check_schedule", "task_id": "task_1", "reason": "missing"})}}]}
    with patch("httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value = response
        NexProvider().choose_next_action(
            plan(task("task_1", 12_000_000, "2026-10-15")),
            [obs("budget", "task_1")], RuntimeContext())
        payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
    assert "budget: clear, schedule: missing" in payload["messages"][1]["content"]
    assert "check_schedule task_1" in payload["messages"][1]["content"]
