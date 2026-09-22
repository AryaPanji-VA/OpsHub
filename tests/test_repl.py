"""Focused tests for the bounded terminal interface."""

import json
import runpy
import tomllib
from pathlib import Path

import pytest

from opshub import repl
from opshub.agent import OpsHubAgent
from opshub.models import NextAction
from tests.test_runtime_flow import ScriptedProvider, action


class CountingProvider(ScriptedProvider):
    def __init__(self, actions=()):
        super().__init__(actions)
        self.plan_calls = 0
        self.action_calls = 0

    def generate_plan(self, notes):
        self.plan_calls += 1
        return super().generate_plan(notes)

    def choose_next_action(self, plan, observations, runtime_context):
        self.action_calls += 1
        return super().choose_next_action(plan, observations, runtime_context)


def run_repl(monkeypatch, tmp_path, capsys, commands, actions=()):
    provider = CountingProvider(actions)
    agent = OpsHubAgent(llm_provider=provider, tickets_file=tmp_path / "tickets.json")
    monkeypatch.setattr(repl, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(repl, "OpsHubAgent", lambda llm_provider: agent)
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")
    answers = iter(["meeting notes", "", *commands, "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    result = repl.main()
    return agent, provider, result, capsys.readouterr().out


def test_launch_extracts_plan_and_enters_repl(monkeypatch, tmp_path, capsys):
    agent, provider, result, output = run_repl(monkeypatch, tmp_path, capsys, [])
    assert result == 0
    assert provider.plan_calls == 1
    assert "OpsHub Agent" in output
    assert "Operational AI for SGA" in output
    assert "Plan ready: Internship" in output
    assert agent.current_plan is not None


def test_python_module_and_console_script_entrypoints(monkeypatch):
    monkeypatch.setattr(repl, "main", lambda: 0)
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("opshub", run_name="__main__")
    assert stopped.value.code == 0
    project = Path(__file__).parent.parent
    metadata = tomllib.loads((project / "pyproject.toml").read_text())
    assert metadata["project"]["scripts"]["opshub"] == "opshub.repl:main"


def test_summary_and_tasks_commands(monkeypatch, tmp_path, capsys):
    _, _, _, output = run_repl(monkeypatch, tmp_path, capsys, ["summary", "tasks"])
    assert "Internship: Two operational tasks" in output
    assert "task_1: Fund event" in output
    assert "task_2: Book event" in output


def test_check_all_routes_to_existing_read_only_checks(monkeypatch, tmp_path, capsys):
    agent, provider, _, output = run_repl(
        monkeypatch, tmp_path, capsys, ["check all", "2", "15000000", "status"])
    assert "[CLEAR] budget task_1" in output
    assert "[CLEAR] schedule task_2" in output
    assert "Checks completed: 2/2" in output
    assert provider.action_calls == 0
    assert not (tmp_path / "tickets.json").exists()
    assert len([e for e in agent.audit_log.events if e["event"] == "tool_result"]) == 2


def test_budget_and_schedule_aliases_keep_completed_check_state(monkeypatch, tmp_path, capsys):
    agent, _, _, output = run_repl(
        monkeypatch, tmp_path, capsys,
        ["cek budget", "2", "15000000", "cek jadwal", "status"])
    assert "Checks completed: 2/2" in output
    assert len([e for e in agent.audit_log.events if e["event"] == "tool_result"]) == 2


def test_create_tickets_reuses_react_and_human_approval(monkeypatch, tmp_path, capsys):
    actions = [action("check_budget", "task_1"), action("check_schedule", "task_2"),
               action("propose_ticket_creation", "task_1"),
               action("propose_ticket_creation", "task_2"), action("finish")]
    agent, provider, _, output = run_repl(
        monkeypatch, tmp_path, capsys,
        ["create tickets", "2", "15000000", "y", "y", "tickets", "status"], actions)
    assert provider.action_calls == 5
    assert "Create ticket for task_1?" in output
    assert "Create ticket for task_2?" in output
    assert "Next Action: completed" in output
    assert "Tickets created this session: 2" in output
    assert [ticket["task_id"] for ticket in json.loads(
        (tmp_path / "tickets.json").read_text())] == ["task_1", "task_2"]
    assert agent.current_plan.next_action == NextAction.COMPLETED


def test_rejected_ticket_cannot_be_silently_created(monkeypatch, tmp_path, capsys):
    actions = [action("check_budget", "task_1"), action("check_schedule", "task_2"),
               action("propose_ticket_creation", "task_1")]
    agent, _, _, output = run_repl(
        monkeypatch, tmp_path, capsys,
        ["buat ticket", "2", "15000000", "n", "buat ticket", "status"], actions)
    assert "Ticket for task_1 rejected." in output
    assert "Human review is required before continuing." in output
    assert "Tickets created this session: 0" in output
    assert agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
    assert not (tmp_path / "tickets.json").exists()


def test_status_help_tickets_and_exit(monkeypatch, tmp_path, capsys):
    _, _, result, output = run_repl(
        monkeypatch, tmp_path, capsys, ["status", "tickets", "help"])
    assert result == 0
    assert "Checks completed: 0/2" in output
    assert "Unresolved tasks: task_1, task_2" in output
    assert "Next action: run_tools" in output
    assert "No tickets created in this session." in output
    assert "Commands: summary, tasks, check all" in output
    assert "Goodbye!" in output


@pytest.mark.parametrize("text,intent", [
    ("show tasks", "tasks"), ("recap", "summary"),
    ("cek budget", "budget"), ("cek jadwal", "schedule"),
    ("buat ticket", "create tickets"), ("buat tiket", "create tickets"),
    ("keluar", "exit"), ("lihat ringkasan", "summary"),
])
def test_simple_english_and_indonesian_aliases(text, intent):
    assert repl.parse_intent(text) == intent


def test_out_of_scope_request_never_reaches_action_model(monkeypatch, tmp_path, capsys):
    _, provider, _, output = run_repl(
        monkeypatch, tmp_path, capsys, ["write me a portfolio website"])
    assert "outside OpsHub's operational scope" in output
    assert "program summaries" in output
    assert provider.plan_calls == 1
    assert provider.action_calls == 0


def test_out_of_scope_initial_request_never_reaches_plan_model(monkeypatch, capsys):
    provider = CountingProvider()
    monkeypatch.setattr(repl, "get_llm_provider", lambda: provider)
    answers = iter(["write me a portfolio website", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert repl.main() == 0
    assert "outside OpsHub's operational scope" in capsys.readouterr().out
    assert provider.plan_calls == 0
    assert provider.action_calls == 0
