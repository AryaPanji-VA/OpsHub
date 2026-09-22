"""Bounded-autonomy resume/continue regression tests (Phase 7.5)."""

import hashlib
from pathlib import Path

from opshub.agent import MAX_AGENT_STEPS, OpsHubAgent
from opshub.models import (
    AgentAction,
    AgentActionModel,
    ContextSource,
    NextAction,
    OperationalPlan,
    Task,
)
from opshub.repl import parse_intent
from tests.test_runtime_flow import action


class LargePlanProvider:
    """Scripted provider serving a large plan and a fixed action queue."""

    def __init__(self, n_tasks: int, actions=()):
        self.plan = OperationalPlan(
            program="Expo",
            summary="Large operational plan",
            tasks=[
                Task(id=f"task_{i}", title=f"Do {i}", division="Ops", pic=None,
                     deadline="2026-12-01", budget_required=12_000_000,
                     priority=None, status=None)
                for i in range(1, n_tasks + 1)
            ],
            checks_required=["budget", "schedule"],
            risk_flags=[],
            next_action=NextAction.RUN_TOOLS,
        )
        self._actions = iter(actions)

    def extend(self, actions):
        self._actions = iter(actions)

    def generate_plan(self, notes):
        return self.plan

    def choose_next_action(self, plan, observations, runtime_context):
        return next(self._actions)


def check_queue(task_ids):
    """All required checks for the given tasks, in order."""
    actions = []
    for task_id in task_ids:
        actions.append(action("check_budget", task_id))
        actions.append(action("check_schedule", task_id))
    return actions


def make_agent(provider, tmp_path):
    agent = OpsHubAgent(llm_provider=provider, tickets_file=tmp_path / "tickets.json")
    agent.ingest_notes("notulensi rapat operational")
    agent.generate_plan()
    agent.set_budget(100_000_000, ContextSource.HUMAN)
    agent.set_schedule_entries([], ContextSource.HUMAN)
    return agent


def data_dir_hashes():
    data = Path(__file__).parent.parent / "data"
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(data.glob("*.json"))
    }


def test_max_agent_steps_unchanged():
    assert MAX_AGENT_STEPS == 6


def test_step_limit_pauses_instead_of_completing(tmp_path):
    provider = LargePlanProvider(4, check_queue(["task_1", "task_2", "task_3"]))
    agent = make_agent(provider, tmp_path)

    success, observations = agent.run_agent_loop()

    assert success is True
    assert len([o for o in observations if o.status == "clear"]) == 6
    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
    assert agent.current_plan.next_action != NextAction.COMPLETED
    assert agent.workflow_paused is True
    assert agent.paused_reason == "step_limit"
    assert not any(o.action == "finish" and o.status == "complete"
                   for o in observations)


def test_completed_observations_survive_pause(tmp_path):
    provider = LargePlanProvider(4, check_queue(["task_1", "task_2", "task_3"]))
    agent = make_agent(provider, tmp_path)
    agent.run_agent_loop()
    before = list(agent.observations)
    executed_before = dict(agent.executed_actions)

    # Any later mutation must not erase preserved work.
    assert len(before) == 6
    assert all(o.status == "clear" for o in before)
    assert len(executed_before) == 6
    assert agent.executed_actions == executed_before


def test_continue_resumes_without_repeating_checks(tmp_path):
    provider = LargePlanProvider(4, check_queue(["task_1", "task_2", "task_3"]))
    agent = make_agent(provider, tmp_path)
    agent.run_agent_loop()
    executed_after_run1 = dict(agent.executed_actions)
    obs_count_after_run1 = len(agent.observations)

    provider.extend([action("check_budget", "task_4"),
                     action("check_schedule", "task_4"),
                     action("propose_ticket_creation", "task_1")])
    success, _ = agent.resume_workflow()

    assert success is True
    assert agent.current_plan.next_action == NextAction.READY_TO_CREATE_TICKET
    # Same plan object reused, not regenerated.
    assert agent.current_plan.program == "Expo"
    # Completed checks preserved and not re-executed.
    assert executed_after_run1.items() <= agent.executed_actions.items()
    assert not any(o.status == "already_checked" for o in agent.observations)
    tool_events = [e for e in agent.audit_log.get_all() if e["event"] == "tool_observation"]
    pairs = [(e["details"]["action"], e["details"]["task_id"]) for e in tool_events]
    assert len(pairs) == len(set(pairs)) == 8
    assert len(agent.observations) > obs_count_after_run1


def test_continue_grants_another_bounded_six_step_run(tmp_path):
    provider = LargePlanProvider(6, check_queue(["task_1", "task_2", "task_3"]))
    agent = make_agent(provider, tmp_path)
    agent.run_agent_loop()
    assert agent.workflow_paused is True

    # Resume 1: the next six legitimate actions, then the limit again.
    provider.extend(check_queue(["task_4", "task_5", "task_6"]))
    success, _ = agent.resume_workflow()
    assert success is True
    assert agent.workflow_paused is True  # paused again by the same bound
    assert len([o for o in agent.observations if o.status == "clear"]) == 12

    # Resume 2: another bounded run proposes the first ticket.
    provider.extend([action("propose_ticket_creation", "task_1")])
    success, _ = agent.resume_workflow()
    assert success is True
    assert agent.current_plan.next_action == NextAction.READY_TO_CREATE_TICKET
    assert agent.workflow_paused is False


def test_multiple_resumes_complete_large_plan(tmp_path):
    provider = LargePlanProvider(6, check_queue(["task_1", "task_2", "task_3"]))
    agent = make_agent(provider, tmp_path)
    agent.run_agent_loop()

    provider.extend(check_queue(["task_4", "task_5", "task_6"]))
    agent.resume_workflow()

    resumes = 0
    for i in range(1, 7):
        provider.extend([action("propose_ticket_creation", f"task_{i}")])
        agent.resume_workflow()
        task = agent.tool_dispatcher._get_task(f"task_{i}")
        agent.request_approval(task.id, "create_ticket")
        assert agent.grant_approval(task.id)
        ticket_id = agent.create_ticket(task)
        assert ticket_id
        # create_ticket hands control back to the loop (RUN_TOOLS), as the
        # TUI/REPL flows do.
        if i < 6:
            provider.extend([action("propose_ticket_creation", f"task_{i + 1}")])
        else:
            provider.extend([action("finish")])
    # Final bounded run after the last ticket resolves the workflow.
    success, _ = agent.run_agent_loop()

    assert success is True
    assert agent.current_plan.next_action == NextAction.COMPLETED
    assert agent._get_unresolved_task_ids() == []
    resumes = [e for e in agent.audit_log.get_all() if e["event"] == "workflow_resumed"]
    assert len(resumes) >= 2


def test_continue_without_paused_workflow_is_controlled(tmp_path):
    provider = LargePlanProvider(2, [])
    agent = make_agent(provider, tmp_path)

    success, observations = agent.resume_workflow()

    assert success is False
    assert observations == []
    assert not any(e["event"] == "workflow_resumed"
                   for e in agent.audit_log.get_all())


def test_finish_only_succeeds_after_all_tasks_resolved(tmp_path):
    provider = LargePlanProvider(2, [action("finish"), action("finish")])
    agent = make_agent(provider, tmp_path)

    success, observations = agent.run_agent_loop()

    assert all(not (o.action == "finish" and o.status == "complete")
               for o in observations)
    assert agent.current_plan.next_action != NextAction.COMPLETED
    assert agent.workflow_paused is False  # stalled, not a resumable pause


def test_ticket_hitl_still_required_after_resume(tmp_path):
    provider = LargePlanProvider(4, check_queue(["task_1", "task_2", "task_3"]))
    agent = make_agent(provider, tmp_path)
    agent.run_agent_loop()
    provider.extend([action("check_budget", "task_4"),
                     action("check_schedule", "task_4"),
                     action("propose_ticket_creation", "task_1")])
    agent.resume_workflow()
    task_1 = agent.tool_dispatcher._get_task("task_1")

    # HITL is not bypassed by resume: no approval, no ticket.
    assert agent.create_ticket(task_1) is None
    assert not (tmp_path / "tickets.json").exists()

    agent.request_approval(task_1.id, "create_ticket")
    agent.grant_approval(task_1.id)
    ticket_id = agent.create_ticket(task_1)
    assert ticket_id == "OPS-001"
    assert "task_1" in agent.created_ticket_tasks


def test_activity_records_pause_and_resume(tmp_path):
    provider = LargePlanProvider(4, check_queue(["task_1", "task_2", "task_3"]))
    agent = make_agent(provider, tmp_path)
    agent.run_agent_loop()
    provider.extend([action("check_budget", "task_4"),
                     action("check_schedule", "task_4"),
                     action("propose_ticket_creation", "task_1")])
    agent.resume_workflow()

    events = [e["event"] for e in agent.audit_log.get_all()]
    assert "agent_step_limit_reached" in events
    assert "workflow_paused" in events
    assert "workflow_resumed" in events
    paused = next(e for e in agent.audit_log.get_all()
                  if e["event"] == "workflow_paused")
    assert paused["details"]["reason"] == "step_limit"
    assert paused["details"]["executed_checks"] == 6


def test_data_files_unchanged_by_resume(tmp_path):
    before = data_dir_hashes()
    provider = LargePlanProvider(6, check_queue(["task_1", "task_2", "task_3"]))
    agent = make_agent(provider, tmp_path)
    agent.run_agent_loop()
    provider.extend(check_queue(["task_4", "task_5", "task_6"]))
    agent.resume_workflow()
    provider.extend([action("propose_ticket_creation", "task_1")])
    agent.resume_workflow()
    task = agent.tool_dispatcher._get_task("task_1")
    agent.request_approval(task.id, "create_ticket")
    agent.grant_approval(task.id)
    agent.create_ticket(task)

    assert data_dir_hashes() == before
    assert not (tmp_path / "tickets.json").read_text().count('"task_id"') == 0


def test_continue_intents_parse():
    assert parse_intent("continue") == "continue"
    assert parse_intent("resume") == "continue"
    assert parse_intent("lanjut") == "continue"


def test_repl_continue_without_pause_message(monkeypatch, tmp_path, capsys):
    from opshub import repl
    from tests.test_repl import CountingProvider

    provider = CountingProvider()
    agent = OpsHubAgent(llm_provider=provider, tickets_file=tmp_path / "tickets.json")
    monkeypatch.setattr(repl, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(repl, "OpsHubAgent", lambda llm_provider: agent)
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")
    answers = iter(["meeting notes about budget and schedule", "", "continue",
                    "lanjut", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert repl.main() == 0
    output = capsys.readouterr().out
    assert output.count("No paused workflow to continue.") == 2


def test_repl_pause_status_and_resume(monkeypatch, tmp_path, capsys):
    from opshub import repl

    actions = (check_queue(["task_1", "task_2", "task_3"])
               + [action("check_budget", "task_4"),
                  action("check_schedule", "task_4"),
                  action("propose_ticket_creation", "task_1"),
                  action("finish"), action("finish")])
    provider = LargePlanProvider(4, actions)
    agent = OpsHubAgent(llm_provider=provider, tickets_file=tmp_path / "tickets.json")
    monkeypatch.setattr(repl, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(repl, "OpsHubAgent", lambda llm_provider: agent)
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")
    answers = iter([
        "notulensi rapat operational besar", "",
        "create tickets", "2", "15000000",   # budget prompts, run 1 pauses
        "status",
        "continue",                           # run 2: last checks + proposal
        "y",                                  # HITL ticket approval
        "finish", "finish",                   # stall out the continuation run
        "exit",
    ])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert repl.main() == 0
    output = capsys.readouterr().out

    assert "AUTONOMOUS RUN PAUSED" in output
    assert "The six-step safety limit was reached." in output
    assert "Completed work has been preserved." in output
    assert "Type 'continue' to resume from the current state." in output
    assert "paused" in output and "continue" in output  # status line
    assert "Workflow: paused" in output
    assert "Ticket OPS-001 created." in output
    # No repeated checks across the resumed run.
    tool_events = [e for e in agent.audit_log.get_all() if e["event"] == "tool_observation"]
    pairs = [(e["details"]["action"], e["details"]["task_id"]) for e in tool_events]
    assert len(pairs) == len(set(pairs))
    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
