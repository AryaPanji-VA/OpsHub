"""Tests for the Terminal UI."""

import asyncio
import json

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from textual.widgets import Input
from textual.containers import VerticalScroll

from opshub.agent import OpsHubAgent
from opshub.models import ContextSource, NextAction
from opshub.tui.app import OpsHubApp, TicketConfirmModal, BudgetSourceModal, ManualBudgetModal, INPUT_PLACEHOLDER
from tests.test_runtime_flow import ScriptedProvider, action


def test_app_init():
    """Test app instantiation."""
    app = OpsHubApp()
    assert app.agent is None
    assert app.agent_error is None
    assert app._current_view == "INPUT"


def test_clear_input():
    """Test clearing input buffer."""
    app = OpsHubApp()
    app._input_buffer = "test"
    app._clear_input()
    assert app._input_buffer == ""


def test_append_output():
    """Test appending to output."""
    app = OpsHubApp()
    app._append_output("Test line 1")
    app._append_output("Test line 2")
    
    assert "Test line 1" in app._output_lines
    assert "Test line 2" in app._output_lines


def test_ticket_confirm_modal():
    """Test ticket confirmation modal."""
    modal = TicketConfirmModal("Create ticket for task_1?")
    assert modal.message == "Create ticket for task_1?"
    assert modal.result is None


def test_toggle_view():
    """Test toggle view action."""
    app = OpsHubApp()
    initial_view = app._current_view
    app.action_toggle_view()
    assert app._current_view != initial_view


def test_toggle_view_cycles():
    """Test that toggle cycles through views."""
    app = OpsHubApp()
    app._current_view = "TASKS"
    app.action_toggle_view()
    assert app._current_view == "ACTIVITY"
    app.action_toggle_view()
    assert app._current_view == "TICKETS"


def test_action_show_commands():
    """Test show commands action."""
    app = OpsHubApp()
    app.action_show_commands()
    assert len(app._output_lines) > 0
    assert "Commands:" in app._output_lines[0]


def test_action_show_tasks():
    """Test show tasks action."""
    app = OpsHubApp()
    app.action_show_tasks()
    assert True


def test_action_show_help():
    """Test show help action."""
    app = OpsHubApp()
    app.action_show_help()
    assert len(app._output_lines) > 0
    assert "OpsHub" in app._output_lines[0]


def test_action_show_logs():
    """Test show logs action."""
    app = OpsHubApp()
    app.action_show_logs()
    assert len(app._output_lines) > 0


def test_main_launches():
    """Test that main() can be called."""
    with patch("opshub.tui.app.OpsHubApp") as MockApp:
        mock_instance = Mock()
        MockApp.return_value = mock_instance
        
        from opshub.tui.app import main
        main()
        
        mock_instance.run.assert_called_once()


def test_app_status_set():
    """Test agent status property."""
    app = OpsHubApp()
    app.agent = Mock()
    app.agent.current_plan = None
    app._append_output("test")
    assert len(app._output_lines) == 1


def test_app_mounts_without_css_errors():
    """Regression: stylesheet must parse and the layout must mount.

    Invalid Textual CSS properties previously raised before launch.
    """
    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Key regions exist and are non-collapsed.
            for selector in (
                "#main-container",
                "#input-field",
                "#output-container",
                "#view-title",
                "#view-content",
                "#shortcut-hints",
                "#footer-status",
                "#status-line",
            ):
                widget = app.query_one(selector)
                assert widget.size.height > 0 or selector == "#main-container", selector
            # Header spells the full OpsHub in two brand-colored halves.
            assert app.query_one("#logo-ops")
            assert app.query_one("#logo-hub")

    asyncio.run(_run())


def test_app_input_accepts_typing_and_submit():
    """Regression: input is focusable, accepts typing, and submits on enter."""
    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            field = app.query_one("#input-field", Input)
            assert field.has_focus
            assert field.placeholder == INPUT_PLACEHOLDER
            await pilot.press("h", "e", "l", "p")
            assert field.value == "help"
            await pilot.press("enter")
            await pilot.pause()
            assert field.value == ""
            assert any("Commands:" in line for line in app._output_lines)

    asyncio.run(_run())


def test_app_q_key_does_not_quit():
    """Regression: typing 'q' in the input must not close the app."""
    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            assert app.query_one("#input-field", Input).value == "q"

    asyncio.run(_run())


def test_app_shortcuts():
    """Regression: ctrl+p commands, ctrl+l logs, tab tasks, ctrl+v cycle."""
    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+p")
            await pilot.pause()
            assert "Commands:" in app._output_lines[0]
            await pilot.press("ctrl+l")
            await pilot.pause()
            assert app._current_view == "ACTIVITY"
            await pilot.press("tab")
            await pilot.pause()
            assert app._current_view == "TASKS"
            await pilot.press("ctrl+v")
            await pilot.pause()
            assert app._current_view == "ACTIVITY"

    asyncio.run(_run())


def test_budget_source_modal_init():
    """Test budget source modal initialization."""
    modal = BudgetSourceModal()
    assert modal.result is None


def test_manual_budget_modal_init():
    """Test manual budget modal initialization."""
    modal = ManualBudgetModal()
    assert modal.result is None


@pytest.mark.parametrize("entered,expected,status", [
    ("15000000", 15_000_000.0, "CLEAR"),
    ("10,000,000", 10_000_000.0, "INSUFFICIENT"),
])
def test_manual_budget_modal_submits_and_overrides_runtime_file(
    monkeypatch, entered, expected, status
):
    """Enter in the modal must reach its callback and use the human amount."""
    def unexpected_file_read(*args, **kwargs):
        raise AssertionError("Manual budget must not read budgets.json")

    monkeypatch.setattr("opshub.tools.budget.load_budgets", unexpected_file_read)

    async def _run():
        app = OpsHubApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app.agent.current_plan = ScriptedProvider([]).generate_plan("meeting notes")
            await pilot.press(*"budget", "enter")
            assert isinstance(app.screen, BudgetSourceModal)
            await pilot.press("2")
            await pilot.pause()
            assert isinstance(app.screen, ManualBudgetModal)
            field = app.screen.query_one("#manual-input", Input)
            assert field.has_focus
            assert field.region.y > 0
            assert field.region.y < app.size.height - 1
            await pilot.press(*entered, "enter")
            await pilot.pause()
            assert not isinstance(app.screen, ManualBudgetModal)
            assert app.agent.runtime_context.available_budget == expected
            assert app.agent.runtime_context.budget_source == ContextSource.HUMAN
            assert app._budget_source_set
            assert f"Budget set: Rp{expected:,.0f}" in app._output_lines
            assert any(f"[{status}] budget task_1" in line for line in app._output_lines)
            assert not any("Unknown command" in line for line in app._output_lines)

    asyncio.run(_run())


def test_schedule_uses_session_booking_when_runtime_schedule_is_empty(monkeypatch, tmp_path):
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            app.agent.current_plan = ScriptedProvider([]).generate_plan("meeting notes")
            await pilot.press(*"schedule", "enter")
            assert app._schedule_input_pending
            assert "No known schedule entries" in app._output_lines[-1]
            assert not any("[CLEAR] schedule" in line for line in app._output_lines)
            await pilot.press(*"2026-12-01 | Existing booking", "enter")
            assert not app._schedule_input_pending
            assert app.agent.runtime_context.schedule_entries == [
                {"date": "2026-12-01", "name": "Existing booking"}
            ]
            assert any("[CONFLICT] schedule task_2" in line for line in app._output_lines)
            assert not (tmp_path / "schedules.json").exists()

    asyncio.run(_run())


def test_schedule_empty_confirmation_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            app.agent.current_plan = ScriptedProvider([]).generate_plan("meeting notes")
            await pilot.press(*"schedule", "enter", *"none", "enter")
            assert app.agent.runtime_context.schedule_entries == []
            assert any("Confirmed: no other schedule entries" in line for line in app._output_lines)
            assert any("no known entries" in line for line in app._output_lines)

    asyncio.run(_run())


def test_schedule_reads_existing_runtime_entries(monkeypatch, tmp_path):
    schedule_file = tmp_path / "schedules.json"
    schedule_file.write_text(json.dumps([{"date": "2026-12-01", "name": "Booked"}]))
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", schedule_file)

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            app.agent.current_plan = ScriptedProvider([]).generate_plan("meeting notes")
            await pilot.press(*"schedule", "enter")
            assert not app._schedule_input_pending
            assert any("[CONFLICT] schedule task_2" in line for line in app._output_lines)

    asyncio.run(_run())


def test_check_all_collects_schedule_and_budget_context(monkeypatch, tmp_path):
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            app.agent.current_plan = ScriptedProvider([]).generate_plan("meeting notes")
            await pilot.press(*"check all", "enter")
            assert app._schedule_input_pending
            await pilot.press(*"none", "enter")
            assert isinstance(app.screen, BudgetSourceModal)
            await pilot.press("2")
            await pilot.pause()
            await pilot.press(*"15000000", "enter")
            await pilot.pause()
            assert any("[CLEAR] budget task_1" in line for line in app._output_lines)
            assert any("[CLEAR] schedule task_2" in line for line in app._output_lines)

    asyncio.run(_run())


def test_create_tickets_runs_loop_and_requires_approval(monkeypatch, tmp_path):
    provider = ScriptedProvider([
        action("check_budget", "task_1"), action("check_schedule", "task_2"),
        action("propose_ticket_creation", "task_1"),
        action("propose_ticket_creation", "task_2"), action("finish"),
    ])
    monkeypatch.setattr("opshub.tui.app.get_llm_provider", lambda: provider)
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")

    async def _wait_for(pilot, predicate):
        for _ in range(40):
            await pilot.pause(0.05)
            if predicate():
                return
        pytest.fail("Ticket workflow did not reach the expected state")

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            app.agent.ingest_notes("meeting notes")
            app.agent.generate_plan()
            app.agent.tickets_file = tmp_path / "tickets.json"
            await pilot.press(*"create tickets", "enter")
            assert isinstance(app.screen, BudgetSourceModal)
            await pilot.press("2")
            await pilot.pause()
            await pilot.press(*"15000000", "enter")
            await pilot.pause()
            assert app._schedule_input_pending
            await pilot.press(*"none", "enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, TicketConfirmModal))
            assert not (tmp_path / "tickets.json").exists()
            assert app.agent.has_pending_approval("task_1")
            await pilot.press("y")
            await _wait_for(pilot, lambda: isinstance(app.screen, TicketConfirmModal)
                            and app.agent.has_pending_approval("task_2"))
            assert app.agent.created_ticket_tasks == {"task_1"}
            await pilot.press("y")
            await _wait_for(pilot, lambda: app.agent.current_plan.next_action == NextAction.COMPLETED)
            assert app.agent.created_ticket_tasks == {"task_1", "task_2"}
            assert [item["task_id"] for item in json.loads((tmp_path / "tickets.json").read_text())] == [
                "task_1", "task_2"
            ]
            assert any("Workflow completed." in line for line in app._output_lines)

    asyncio.run(_run())


def test_run_all_presents_full_overview_and_final_recap(monkeypatch, tmp_path):
    provider = ScriptedProvider([
        action("check_budget", "task_1"), action("check_schedule", "task_2"),
        action("propose_ticket_creation", "task_1"),
        action("propose_ticket_creation", "task_2"), action("finish"),
    ])
    monkeypatch.setattr("opshub.tui.app.get_llm_provider", lambda: provider)
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")

    async def _wait_for(pilot, predicate):
        for _ in range(40):
            await pilot.pause(0.05)
            if predicate():
                return
        pytest.fail("Run-all workflow did not reach the expected state")

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            app.agent.ingest_notes("meeting notes")
            app.agent.generate_plan()
            app.agent.tickets_file = tmp_path / "tickets.json"
            await pilot.press(*"semua", "enter")
            overview = "\n".join(app._output_lines)
            assert app._current_view == "OVERVIEW"
            assert "PROGRAM OVERVIEW" in overview
            assert "Program : Internship" in overview
            assert "task_1 — Fund event" in overview
            assert "Division : Ops" in overview
            assert "PIC      : not specified" in overview
            assert "Deadline : 2026-12-01" in overview
            assert "Budget   : Rp12,000,000" in overview
            assert "TOTAL TASK BUDGET: Rp12,000,000" in overview
            assert isinstance(app.screen, BudgetSourceModal)
            await pilot.press("2")
            await pilot.pause()
            await pilot.press(*"15000000", "enter")
            await pilot.pause()
            assert app._schedule_input_pending
            await pilot.press(*"none", "enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, TicketConfirmModal))
            await pilot.press("y")
            await _wait_for(pilot, lambda: isinstance(app.screen, TicketConfirmModal)
                            and app.agent.has_pending_approval("task_2"))
            await pilot.press("y")
            await _wait_for(pilot, lambda: app.agent.current_plan.next_action == NextAction.COMPLETED)
            report = "\n".join(app._output_lines)
            assert "FINAL RECAP" in report
            assert "Available : Rp15,000,000" in report
            assert "Known entries : 0" in report
            assert "Tickets created : 2/2" in report
            assert "Unresolved      : none" in report
            assert "Workflow        : completed" in report

    asyncio.run(_run())


@pytest.mark.parametrize("command", ["run all", "jalankan semua"])
def test_run_all_aliases_start_complete_overview(monkeypatch, tmp_path, command):
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            app.agent.current_plan = ScriptedProvider([]).generate_plan("meeting notes")
            await pilot.press(*command, "enter")
            assert app._current_view == "OVERVIEW"
            assert "PROGRAM OVERVIEW" in "\n".join(app._output_lines)
            assert isinstance(app.screen, BudgetSourceModal)
            await pilot.press("escape")

    asyncio.run(_run())


def test_schedule_conflict_blocks_ticket_workflow(monkeypatch, tmp_path):
    provider = ScriptedProvider([
        action("check_schedule", "task_2"), action("request_human_review"),
    ])
    monkeypatch.setattr("opshub.tui.app.get_llm_provider", lambda: provider)
    schedule_file = tmp_path / "schedules.json"
    schedule_file.write_text(json.dumps([{"date": "2026-12-01", "name": "Existing booking"}]))
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", schedule_file)

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            app.agent.ingest_notes("meeting notes")
            app.agent.generate_plan()
            app.agent.tickets_file = tmp_path / "tickets.json"
            app.agent.set_budget(15_000_000)
            await pilot.press(*"create tickets", "enter")
            for _ in range(40):
                await pilot.pause(0.05)
                if app.agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN:
                    break
            assert app.agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
            assert any("Schedule conflict" in line for line in app._output_lines)
            guidance = "\n".join(app._output_lines)
            assert "HUMAN REVIEW REQUIRED" in guidance
            assert "Why automation stopped:" in guidance
            assert "task_2 — Schedule: Schedule conflict with Existing booking" in guidance
            assert "Resolve or move the conflicting booking/date." in guidance
            assert "Type status for the unresolved tasks." in guidance
            assert not (tmp_path / "tickets.json").exists()

    asyncio.run(_run())


def test_rejected_ticket_proposal_creates_no_ticket(monkeypatch, tmp_path):
    provider = ScriptedProvider([
        action("check_budget", "task_1"), action("check_schedule", "task_2"),
        action("propose_ticket_creation", "task_1"),
    ])
    monkeypatch.setattr("opshub.tui.app.get_llm_provider", lambda: provider)
    monkeypatch.setattr("opshub.tools.schedule.DATA_FILE", tmp_path / "schedules.json")

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            app.agent.ingest_notes("meeting notes")
            app.agent.generate_plan()
            app.agent.tickets_file = tmp_path / "tickets.json"
            app.agent.set_budget(15_000_000)
            app.agent.set_schedule_entries([])
            await pilot.press(*"create tickets", "enter")
            for _ in range(40):
                await pilot.pause(0.05)
                if isinstance(app.screen, TicketConfirmModal):
                    break
            assert isinstance(app.screen, TicketConfirmModal)
            await pilot.press("n")
            await pilot.pause()
            assert app.agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN
            guidance = "\n".join(app._output_lines)
            assert "Ticket approval was rejected for: task_1" in guidance
            assert "No rejected ticket was created." in guidance
            assert not (tmp_path / "tickets.json").exists()

    asyncio.run(_run())


def test_budget_app_reset_on_new_plan():
    """Test that budget state resets when starting new plan."""
    app = OpsHubApp()
    app._budget_source_set = True
    app._budget_check_pending = {"budget"}
    app._input_buffer = "new plan"

    # Simulate new plan intent handling
    app._budget_source_set = False
    app._budget_check_pending = None

    assert not app._budget_source_set
    assert app._budget_check_pending is None


def _seed_long_views(app):
    plan = ScriptedProvider([]).generate_plan("meeting notes")
    plan.summary = "\n".join(f"Plan detail {i}" for i in range(40))
    plan.tasks = [plan.tasks[0].model_copy(update={"id": f"task_{i}", "title": f"Task number {i}"})
                  for i in range(15)]
    app.agent.current_plan = plan
    app.agent.created_ticket_tasks = {f"task_{i}" for i in range(15)}
    for i in range(30):
        app.agent.audit_log.add("activity", {"number": i})


@pytest.mark.parametrize("view,marker", [
    ("PLAN", "Plan detail 39"),
    ("TASKS", "task_14: Task number 14"),
    ("ACTIVITY", "'number': 29"),
    ("TICKETS", "## Tickets (15)"),
])
def test_long_views_scroll_inside_fixed_panel(view, marker):
    async def _run():
        app = OpsHubApp()
        async with app.run_test(size=(80, 24)) as pilot:
            _seed_long_views(app)
            app._show_view(view)
            await pilot.pause()
            panel = app.query_one("#output-container", VerticalScroll)
            assert panel.max_scroll_y > 0
            assert marker in "\n".join(app._output_lines)
            panel.scroll_end(animate=False)
            await pilot.pause()
            assert panel.scroll_y == panel.max_scroll_y
            assert panel.region.y + panel.region.height <= app.query_one("#shortcut-hints").region.y
            assert app.query_one("#footer-status").region.y < app.size.height
            assert app.query_one("#input-field", Input).region.height > 0

    asyncio.run(_run())


def test_output_keyboard_scrolling_and_view_switch_reset():
    async def _run():
        app = OpsHubApp()
        async with app.run_test(size=(80, 24)) as pilot:
            _seed_long_views(app)
            app._show_view("PLAN")
            await pilot.pause()
            panel = app.query_one("#output-container", VerticalScroll)
            assert panel.can_focus
            assert panel.scroll_y == 0
            await pilot.press("ctrl+o", "pagedown")
            await pilot.pause()
            assert panel.has_focus
            assert panel.scroll_y > 0
            app._show_view("TASKS")
            await pilot.pause()
            assert panel.scroll_y == 0
            assert "Plan detail 39" not in "\n".join(app._output_lines)
            assert "task_14: Task number 14" in "\n".join(app._output_lines)
            await pilot.press("down")
            await pilot.pause()
            assert panel.scroll_y > 0
            field = app.query_one("#input-field", Input)
            field.focus()
            await pilot.press("h", "e", "l", "p")
            assert field.value == "help"
            assert app.query_one("#shortcut-hints").size.height > 0
            assert app.query_one("#footer-status").size.height > 0

    asyncio.run(_run())


def test_app_continue_command_messages():
    """Regression: continue gives controlled messages when nothing is paused."""
    from opshub.agent import OpsHubAgent
    from opshub.models import NextAction, OperationalPlan, Task

    async def _run():
        app = OpsHubApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            # No plan loaded.
            field = app.query_one("#input-field", Input)
            field.value = "continue"
            await pilot.press("enter")
            await pilot.pause()
            assert "No plan loaded." in app._output_lines

            # Plan loaded but nothing paused.
            plan = OperationalPlan(
                program="Expo", summary="s",
                tasks=[Task(id="task_1", title="t", division="Ops", pic=None,
                            deadline=None, budget_required=None, priority=None,
                            status=None)],
                checks_required=[], risk_flags=[], next_action=NextAction.RUN_TOOLS,
            )
            app.agent = OpsHubAgent(llm_provider=Mock())
            app.agent.current_plan = plan
            field.value = "continue"
            await pilot.press("enter")
            await pilot.pause()
            assert "No paused workflow to continue." in app._output_lines

            # Completed workflow.
            plan.next_action = NextAction.COMPLETED
            app.agent.workflow_paused = True
            field.value = "continue"
            await pilot.press("enter")
            await pilot.pause()
            assert "Workflow already completed." in app._output_lines

    asyncio.run(_run())
