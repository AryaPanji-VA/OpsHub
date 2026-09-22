"""Regression tests for the two-task CLI workflow."""

from opshub.agent import OpsHubAgent
from opshub import cli
from opshub.models import AgentAction, AgentActionModel, NextAction, OperationalPlan, Task
from opshub.llm.qwen import OPERATIONAL_PLAN_SCHEMA as QWEN_PLAN_SCHEMA
from opshub.llm.nex import OPERATIONAL_PLAN_SCHEMA as NEX_PLAN_SCHEMA


class ScriptedProvider:
    def __init__(self, actions):
        self.actions = iter(actions)

    def generate_plan(self, notes):
        return OperationalPlan(
            program="Internship", summary="Two operational tasks",
            tasks=[
                Task(id="task_1", title="Fund event", division="Ops", pic=None,
                     deadline=None, budget_required=12_000_000, priority=None, status=None),
                Task(id="task_2", title="Book event", division="Ops", pic=None,
                     deadline="2026-12-01", budget_required=None, priority=None, status=None),
            ],
            checks_required=["budget", "schedule"], risk_flags=[],
            next_action=NextAction.RUN_TOOLS,
        )

    def choose_next_action(self, plan, observations, runtime_context):
        return next(self.actions)


def action(name, task_id=None):
    return AgentActionModel(action=AgentAction(name), task_id=task_id, reason="test")


def run_cli(monkeypatch, tmp_path, capsys, actions, answers):
    provider = ScriptedProvider(actions)
    agent = OpsHubAgent(llm_provider=provider, tickets_file=tmp_path / "tickets.json")
    monkeypatch.setattr(cli, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(cli, "OpsHubAgent", lambda llm_provider: agent)
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")
    prompts = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(prompts))
    cli.main()
    return agent, capsys.readouterr().out


def test_repeated_invalid_finish_never_prints_completed(monkeypatch, tmp_path, capsys):
    actions = [action("check_budget", "task_1"), action("check_schedule", "task_2")]
    actions += [action("finish") for _ in range(4)]
    agent, output = run_cli(monkeypatch, tmp_path, capsys, actions,
                            ["meeting notes", "/run", "2", "15000000", "/exit"])
    assert output.count("[INVALID_ACTION]") == 2
    assert len([e for e in agent.audit_log.events
                if e["event"] == "agent_action_selected"]) == 4
    assert "Next Action: wait_for_human" in output
    assert "Next Action: completed" not in output
    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
    assert not (tmp_path / "tickets.json").exists()


def test_two_proposals_require_two_approvals_and_tickets(monkeypatch, tmp_path, capsys):
    actions = [action("check_budget", "task_1"), action("check_schedule", "task_2"),
               action("propose_ticket_creation", "task_1"),
               action("propose_ticket_creation", "task_2"), action("finish")]
    agent, output = run_cli(monkeypatch, tmp_path, capsys, actions,
                            ["meeting notes", "/run", "2", "15000000", "y", "y", "/exit"])
    assert "Create ticket for task_1?" in output
    assert "Create ticket for task_2?" in output
    assert output.count("Ticket OPS-") == 2
    assert "Next Action: completed" in output
    assert agent.created_ticket_tasks == {"task_1", "task_2"}


def test_approval_alone_does_not_resolve_task(tmp_path):
    provider = ScriptedProvider([])
    agent = OpsHubAgent(llm_provider=provider, tickets_file=tmp_path / "tickets.json")
    agent.ingest_notes("meeting notes")
    agent.generate_plan()
    agent.request_approval("task_1", "create_ticket")
    agent.grant_approval("task_1")
    assert agent._get_unresolved_task_ids() == ["task_1", "task_2"]
    assert not agent._can_finish()


def test_schedule_check_uses_session_entries(monkeypatch, tmp_path):
    provider = ScriptedProvider([action("check_schedule", "task_2")])
    agent = OpsHubAgent(llm_provider=provider, tickets_file=tmp_path / "tickets.json")
    agent.ingest_notes("meeting notes")
    agent.generate_plan()
    agent.set_schedule_entries([{"name": "Other", "date": "2026-12-01"}])
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")
    # The next action is human review, so only inspect the first dispatched result.
    class ReviewAfterCheck:
        def __init__(self):
            self.calls = 0

        def choose_next_action(self, plan, observations, runtime_context):
            self.calls += 1
            return action("check_schedule", "task_2") if self.calls == 1 else action("request_human_review")

    agent.llm_provider = ReviewAfterCheck()
    _, observations = agent.run_agent_loop()
    assert observations[0].status == "failed"
    assert observations[0].details["source"] == "human"


def test_provider_plan_schema_is_shared_and_allows_unknown_status():
    assert NEX_PLAN_SCHEMA is QWEN_PLAN_SCHEMA
    assert None in QWEN_PLAN_SCHEMA["properties"]["tasks"]["items"]["properties"]["status"]["enum"]
