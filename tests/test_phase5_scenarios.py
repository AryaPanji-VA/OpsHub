"""Deterministic Phase 5 demos; all writes stay in pytest temporary directories."""

import json

import pytest

from opshub import cli
from opshub.agent import MAX_AGENT_STEPS, OpsHubAgent
from opshub.llm.exceptions import RecoverableLLMError
from opshub.models import AgentAction, AgentActionModel, NextAction
from tests.test_runtime_flow import ScriptedProvider, action, run_cli


def events(agent):
    return [entry["event"] for entry in agent.audit_log.get_all()]


def test_safe_demo_audit_and_finish(monkeypatch, tmp_path, capsys):
    agent, output = run_cli(
        monkeypatch, tmp_path, capsys,
        [action("check_budget", "task_1"), action("check_schedule", "task_2"),
         action("propose_ticket_creation", "task_1"),
         action("propose_ticket_creation", "task_2"), action("finish")],
        ["meeting notes", "/run", "2", "15000000", "y", "y", "/exit"],
    )
    assert "Workflow completed." in output
    assert [ticket["task_id"] for ticket in json.loads(
        (tmp_path / "tickets.json").read_text())] == ["task_1", "task_2"]
    assert events(agent).count("ticket_created") == 2
    assert events(agent).count("approval_granted") == 2
    assert events(agent).count("tool_observation") == 2
    assert agent.audit_log.get_all()[-1]["details"]["reason"] == "finish"


@pytest.mark.parametrize("scenario,actions,answers", [
    ("budget", [action("check_budget", "task_1"), action("request_human_review")],
     ["meeting notes", "/run", "2", "10000000", "/exit"]),
    ("schedule", [action("check_schedule", "task_2"), action("request_human_review")],
     ["meeting notes", "/run", "2", "15000000", "/exit"]),
])
def test_blocked_demos(monkeypatch, tmp_path, capsys, scenario, actions, answers):
    if scenario == "schedule":
        (tmp_path / "schedules.json").write_text(
            json.dumps([{"name": "Other event", "date": "2026-12-01"}]))
    agent, output = run_cli(monkeypatch, tmp_path, capsys, actions, answers)
    assert "Next Action: wait_for_human" in output
    assert "Workflow completed." not in output
    assert not (tmp_path / "tickets.json").exists()
    result = next(e for e in agent.audit_log.get_all() if e["event"] == "tool_observation")
    assert result["details"]["status"] == "failed"
    assert result["details"]["message"]
    assert "policy_interrupted_loop" in events(agent)


def test_missing_critical_budget_context_escalates(monkeypatch, tmp_path):
    monkeypatch.setattr("opshub.tools.budget.DATA_FILE", tmp_path / "missing-budget.json")
    agent = OpsHubAgent(
        llm_provider=ScriptedProvider(
            [action("check_budget", "task_1"), action("request_human_review")]),
        tickets_file=tmp_path / "tickets.json",
    )
    agent.ingest_notes("meeting notes")
    agent.generate_plan()
    success, observations = agent.run_agent_loop()
    assert success
    assert observations[0].status == "missing_context"
    assert observations[-1].action == "request_human_review"
    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
    assert not (tmp_path / "tickets.json").exists()


def test_invented_id_cannot_dispatch_or_create_ticket(tmp_path):
    agent = OpsHubAgent(
        llm_provider=ScriptedProvider(
            [action("propose_ticket_creation", "invented")] * MAX_AGENT_STEPS),
        tickets_file=tmp_path / "tickets.json",
    )
    agent.ingest_notes("meeting notes")
    agent.generate_plan()
    agent.run_agent_loop()
    assert agent.observations[0].status == "invalid_action"
    assert "task_id_validation_failed" in events(agent)
    agent.request_approval("invented", "create_ticket")
    agent.grant_approval("invented")
    from opshub.models import Task
    forged = Task(id="invented", title="Invented", division=None, pic=None,
                  deadline=None, budget_required=None, priority=None, status=None)
    assert agent.create_ticket(forged) is None
    assert not (tmp_path / "tickets.json").exists()


def test_provider_action_failure_is_safe_in_cli(monkeypatch, tmp_path, capsys):
    class FailingProvider(ScriptedProvider):
        def choose_next_action(self, plan, observations, runtime_context):
            raise RecoverableLLMError("both unavailable", provider="fallback",
                                      category="all_failed")

    provider = FailingProvider([])
    agent = OpsHubAgent(llm_provider=provider, tickets_file=tmp_path / "tickets.json")
    monkeypatch.setattr(cli, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(cli, "OpsHubAgent", lambda llm_provider: agent)
    answers = iter(["meeting notes", "/run", "2", "15000000", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main()
    output = capsys.readouterr().out
    assert "Agent loop failed." in output
    assert "Traceback" not in output
    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
    assert "agent_action_failed" in events(agent)
    assert not (tmp_path / "tickets.json").exists()


def test_step_limit_audit_escalates(tmp_path):
    class InvalidActionProvider(ScriptedProvider):
        def choose_next_action(self, plan, observations, runtime_context):
            return AgentActionModel(action=AgentAction.CHECK_BUDGET,
                                    task_id="invented", reason="bad id")

    agent = OpsHubAgent(llm_provider=InvalidActionProvider([]),
                        tickets_file=tmp_path / "tickets.json")
    agent.ingest_notes("meeting notes")
    agent.generate_plan()
    agent.run_agent_loop()
    assert MAX_AGENT_STEPS == 6
    assert events(agent).count("task_id_validation_failed") == MAX_AGENT_STEPS
    assert {
        "event": "agent_step_limit_reached",
        "details": {"step": MAX_AGENT_STEPS, "next_action": "wait_for_human"},
    } in agent.audit_log.get_all()
    # Phase 7.5: the step limit now records a resumable pause.
    assert agent.audit_log.get_all()[-1] == {
        "event": "workflow_paused",
        "details": {"reason": "step_limit", "preserved_observations": 6,
                    "executed_checks": 0},
    }
    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
