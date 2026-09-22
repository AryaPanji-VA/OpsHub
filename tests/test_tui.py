"""Tests for the Terminal UI."""

import asyncio

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from textual.widgets import Input

from opshub.agent import OpsHubAgent
from opshub.models import NextAction
from opshub.tui.app import OpsHubApp, TicketConfirmModal, INPUT_PLACEHOLDER


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
