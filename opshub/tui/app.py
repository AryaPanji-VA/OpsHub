"""Main terminal UI application for OpsHub."""

from functools import partial
from datetime import date
import sys
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static, Label
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import events
from textual.worker import Worker, WorkerState
from typing import Any, List, Optional
from opshub.agent import MAX_AGENT_STEPS, OpsHubAgent
from opshub.llm import get_llm_provider
from opshub.llm.gateway import gateway_configured
from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.cli import format_llm_error
from opshub.repl import parse_intent, is_operational_notes
from opshub.cli import parse_budget_input
from opshub.models import NextAction, Task, ContextSource
from opshub.config import apply_saved_credentials, load_configuration, needs_setup, save_credentials
from opshub.tui.setup import FirstRunSetup

# Branding colors
OPS_COLOR = "#06465A"
HUB_COLOR = "#C7B166"
BG_COLOR = "#1a1a1a"
TEXT_COLOR = "#e0e0e0"
MUTED_COLOR = "#888888"

INPUT_PLACEHOLDER = "Paste meeting notes or describe your program..."

# Large header, split so "Ops" and "Hub" can carry their own brand colors.
ASCII_OPS = """
 █████  ██████   ██████
██   ██ ██   ██ ██
██   ██ ██████   █████
██   ██ ██           ██
 █████  ██      ██████
"""

ASCII_HUB = """
██   ██ ██   ██ ██████
██   ██ ██   ██ ██   ██
███████ ██   ██ ██████
██   ██ ██   ██ ██   ██
██   ██  █████  ██████
"""

SUBTITLE = "Operational AI Agent"


class OpsHubHeader(Static):
    """Header widget with the branded OpsHub logo."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="logo-row"):
            yield Static(ASCII_OPS, id="logo-ops", classes="logo-part")
            yield Static(ASCII_HUB, id="logo-hub", classes="logo-part")
        yield Static(SUBTITLE, id="subtitle")


class StatusLine(Static):
    """Status line showing agent state."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._status: str = "ready"
        self._provider: str = "Qwen 3.8 27B"

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str) -> None:
        self._status = value
        self.refresh()

    @property
    def provider(self) -> str:
        return self._provider

    @provider.setter
    def provider(self, value: str) -> None:
        self._provider = value
        self.refresh()

    def render(self) -> str:
        return f"Agent · {self.provider} · {self.status}"


class ShortcutHints(Static):
    """Shortcut hint bar."""

    def render(self) -> str:
        return "tab tasks  ctrl+v views  ctrl+o scroll  ctrl+p cmds  ctrl+q quit"


class BottomStatus(Static):
    """Bottom status bar."""

    def render(self) -> str:
        return "OpsHub-Agent:main   ready"


class TicketConfirmModal(ModalScreen):
    """Modal for HITL confirmation."""

    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message
        self.result: Optional[bool] = None

    def compose(self) -> ComposeResult:
        yield Static(self.message, id="confirm-message")
        yield Label("[y] Yes  [n/N] No", id="confirm-hint")

    def action_confirm(self) -> None:
        self.result = True
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.result = False
        self.dismiss(False)


class BudgetSourceModal(ModalScreen):
    """Modal for selecting budget source."""

    BINDINGS = [
        Binding("1", "use_runtime", "Runtime Data"),
        Binding("2", "use_manual", "Manual"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.result: Optional[int] = None

    def compose(self) -> ComposeResult:
        with Vertical(id="budget-source-dialog"):
            yield Static("Available budget source:", id="budget-title")
            yield Label("[1] Use runtime data", id="budget-opt1")
            yield Label("[2] Enter manually", id="budget-opt2")

    def action_use_runtime(self) -> None:
        self.result = 1
        self.dismiss(1)

    def action_use_manual(self) -> None:
        self.result = 2
        self.dismiss(2)

    def action_cancel(self) -> None:
        self.result = None
        self.dismiss(None)


class ManualBudgetModal(ModalScreen):
    """Modal for manual budget input."""

    BINDINGS = [
        Binding("enter", "submit", "Submit"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.result: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Vertical(id="manual-budget-dialog"):
            yield Static("Enter available budget:", id="manual-title")
            yield Input(id="manual-input", placeholder="15000000 or 15,000,000")
            yield Label("Press Enter to use this amount; Esc to cancel.")

    def on_mount(self) -> None:
        self.query_one("#manual-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_submit()

    def action_submit(self) -> None:
        input_widget = self.query_one("#manual-input", Input)
        value = input_widget.value.strip()
        if value:
            self.result = value
            self.dismiss(value)
        else:
            self.notify("Input required. Press Enter to submit.", severity="warning")

    def action_cancel(self) -> None:
        self.result = None
        self.dismiss(None)


class OpsHubApp(App):
    """Main OpsHub Terminal UI Application."""

    TITLE = "OpsHub"
    CSS = """
    Screen {
        background: #1a1a1a;
        color: #e0e0e0;
    }
    OpsHubHeader {
        width: 100%;
        height: auto;
        align-horizontal: center;
        margin-bottom: 1;
    }
    #logo-row {
        height: auto;
        width: 1fr;
        align-horizontal: center;
    }
    .logo-part {
        width: auto;
        height: auto;
    }
    #logo-ops {
        color: #06465A;
        text-style: bold;
    }
    #logo-hub {
        color: #C7B166;
        text-style: bold;
    }
    #subtitle {
        color: #C7B166;
        text-align: center;
    }
    #main-container {
        width: 100%;
        height: 1fr;
        padding: 0 1;
    }
    #status-line {
        color: #888888;
        height: 1;
        margin-bottom: 1;
    }
    #input-field {
        border: round #C7B166;
        background: #2a2a2a;
        color: #e0e0e0;
        margin-bottom: 1;
    }
    #output-container {
        height: 1fr;
        border: round #888888;
        padding: 0 1;
        margin-bottom: 1;
        scrollbar-background: #303030;
        scrollbar-color: #867950;
        scrollbar-color-hover: #C7B166;
    }
    #view-title {
        color: #C7B166;
        text-style: bold;
    }
    #view-content {
        color: #e0e0e0;
        width: 100%;
        height: auto;
    }
    #shortcut-hints {
        color: #888888;
        height: 1;
    }
    #footer-status {
        background: #2a2a2a;
        color: #888888;
        height: auto;
        border-top: solid #888888;
    }
    TicketConfirmModal {
        align: center middle;
    }
    BudgetSourceModal, ManualBudgetModal {
        align: center middle;
    }
    #budget-source-dialog, #manual-budget-dialog {
        width: 60;
        height: auto;
        border: round #C7B166;
        padding: 1 2;
        background: #2a2a2a;
        color: #e0e0e0;
    }
    #budget-source-dialog Label, #manual-budget-dialog Label {
        height: 1;
        color: #888888;
    }
    #manual-input {
        width: 100%;
    }
    #confirm-message {
        border: round #C7B166;
        padding: 1 2;
        background: #1a1a1a;
        color: #e0e0e0;
        width: auto;
        height: auto;
    }
    #confirm-hint {
        color: #888888;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("tab", "show_tasks", "Tasks", priority=True),
        Binding("ctrl+v", "toggle_view", "Cycle View", priority=True),
        Binding("ctrl+o", "focus_output", "Scroll Output", priority=True),
        Binding("ctrl+p", "show_commands", "Commands", priority=True),
        Binding("ctrl+l", "show_logs", "Logs", priority=True),
        Binding("question_mark", "show_help", "Help"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    VIEW_TITLES = {
        "OVERVIEW": "FULL OPERATIONAL OVERVIEW",
        "PLAN": "PLAN",
        "TASKS": "TASKS",
        "ACTIVITY": "ACTIVITY",
        "TICKETS": "TICKETS",
    }

    def __init__(self, *args: Any, setup_required: bool = False,
                 setup_protected: Optional[set[str]] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._setup_required = setup_required
        self._setup_protected = setup_protected or set()
        self.agent: Optional[OpsHubAgent] = None
        self.agent_error: Optional[str] = None
        self._current_view: str = "INPUT"
        self._output_lines: List[str] = []
        self._input_buffer: str = ""
        self._budget_source_set: bool = False
        self._budget_check_pending: Optional[set] = None
        self._schedule_input_pending = False
        self._ticket_workflow_requested = False
        self._workflow_worker: Optional[Worker] = None
        self._workflow_seen = 0
        self._run_all_requested = False

    def compose(self) -> ComposeResult:
        with Container(id="main-container"):
            yield OpsHubHeader()
            yield StatusLine(id="status-line")
            yield Input(placeholder=INPUT_PLACEHOLDER, id="input-field")
            with VerticalScroll(id="output-container", can_focus=True):
                yield Label("PLAN", id="view-title")
                yield Static("", id="view-content")
            yield ShortcutHints(id="shortcut-hints")
            yield BottomStatus(id="footer-status")

    def on_mount(self) -> None:
        if self._setup_required:
            self.push_screen(FirstRunSetup(), self._handle_setup)
        else:
            self._init_agent()
            self.query_one("#input-field", Input).focus()

    def _handle_setup(self, credentials: Optional[tuple[str, str]]) -> None:
        if credentials is None:
            if needs_setup():
                self.exit()
            else:
                self._init_agent()
                self.query_one("#input-field", Input).focus()
            return
        try:
            save_credentials(*credentials)
            apply_saved_credentials(self._setup_protected)
        except (OSError, ValueError):
            self.notify("Could not save credentials. Check your user config directory.", severity="error")
            self.push_screen(FirstRunSetup(), self._handle_setup)
            return
        self._init_agent()
        self.query_one("#input-field", Input).focus()

    def _init_agent(self) -> None:
        """Initialize the agent with LLM provider."""
        try:
            self.agent = OpsHubAgent(llm_provider=get_llm_provider())
            self.query_one(StatusLine).status = "ready"
            self.query_one(StatusLine).provider = "Qwen 3.8 27B"
            self._budget_source_set = False
            self._budget_check_pending = None
        except (ConfigurationError, RecoverableLLMError) as e:
            self.agent_error = format_llm_error(e)
            self.query_one(StatusLine).status = "error"

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard shortcuts."""
        if event.key == "escape":
            self._clear_input()

    def _clear_input(self) -> None:
        """Clear input buffer."""
        self._input_buffer = ""
        try:
            input_widget = self.query_one("#input-field", Input)
            input_widget.value = ""
        except Exception:
            pass

    def _append_output(self, line: str) -> None:
        """Append to output."""
        self._output_lines.append(line)
        self._output_lines = self._output_lines[-200:]
        try:
            content = self.query_one("#view-content", Static)
            content.update("\n".join(self._output_lines))
            self.query_one("#output-container", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    def _set_view_title(self, view_name: str) -> None:
        try:
            self.query_one("#view-title", Label).update(self.VIEW_TITLES.get(view_name, view_name))
        except Exception:
            pass

    def _show_view(self, view_name: str) -> None:
        """Show a different view."""
        self._current_view = view_name
        self._output_lines = []
        self._set_view_title(view_name)

        if view_name == "PLAN":
            if self.agent and self.agent.current_plan:
                plan = self.agent.current_plan
                self._append_output(f"### {plan.program}\n{plan.summary}")
            else:
                self._append_output("No plan loaded.")
        elif view_name == "TASKS":
            if self.agent and self.agent.current_plan:
                tasks = "\n".join(f"  {t.id}: {t.title} ({t.division})" for t in self.agent.current_plan.tasks)
                self._append_output(f"## Tasks ({len(self.agent.current_plan.tasks)})\n{tasks}")
            else:
                self._append_output("No plan loaded.")
        elif view_name == "ACTIVITY":
            if self.agent:
                events = [f"  {e['event']}: {e.get('details')}" for e in self.agent.audit_log.events[-20:]]
                self._append_output("## Recent Activity\n" + "\n".join(events))
            else:
                self._append_output("No activity recorded.")
        elif view_name == "TICKETS":
            if self.agent and self.agent.created_ticket_tasks:
                tickets = "\n".join(f"  OPS-{i+1:03d}: {tid}" for i, tid in enumerate(self.agent.created_ticket_tasks))
                self._append_output(f"## Tickets ({len(self.agent.created_ticket_tasks)})\n{tickets}")
            else:
                self._append_output("No tickets created.")
        else:
            self._append_output("No plan loaded.")
        if self.is_running:
            self.query_one("#output-container", VerticalScroll).scroll_home(animate=False)

    def action_focus_output(self) -> None:
        """Focus the output so built-in arrow and page scrolling work."""
        self.query_one("#output-container", VerticalScroll).focus()

    def action_show_tasks(self) -> None:
        """Show tasks view."""
        self._show_view("TASKS")

    def action_toggle_view(self) -> None:
        """Cycle through views."""
        views = ["PLAN", "TASKS", "ACTIVITY", "TICKETS"]
        idx = views.index(self._current_view) if self._current_view in views else 0
        self._show_view(views[(idx + 1) % len(views)])

    def action_show_commands(self) -> None:
        """Show commands help."""
        self._append_output(
            "Commands:\n"
            "  run all       Full overview, checks, ticket approvals, and final recap (alias: semua)\n"
            "  summary       Show program summary\n"
            "  tasks         List all tasks\n"
            "  check all     Run all checks\n"
            "  budget        Check budget\n"
            "  schedule      Check schedule\n"
            "  tickets       Show created tickets\n"
            "  create tickets Create tickets from workflow\n"
            "  continue      Resume a paused workflow (aliases: resume, lanjut)\n"
            "  status        Show operational status\n"
            "  help          Show this help\n"
            "  new plan      Start new plan\n"
        )

    def action_show_logs(self) -> None:
        """Show audit logs."""
        self._show_view("ACTIVITY")

    def action_show_help(self) -> None:
        """Show help."""
        self._append_output(
            "OpsHub Terminal UI\n"
            "\n"
            "Shortcuts:\n"
            "  tab         Show tasks\n"
            "  ctrl+v      Cycle views (plan/tasks/activity/tickets)\n"
            "  ctrl+o      Focus output for arrow/PageUp/PageDown scrolling\n"
            "  ctrl+p      Show commands\n"
            "  ctrl+l      Show activity logs\n"
            "  ?           Help\n"
            "  ctrl+q      Quit\n"
            "  escape      Clear input\n"
            "\n"
            "Type commands in the input field."
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        event.stop()
        if not self.agent:
            self._append_output("Agent error. Check configuration.")
            return

        line = event.value.strip()
        if not line:
            return

        self._input_buffer = line
        self.query_one("#input-field", Input).value = ""

        if self._schedule_input_pending:
            self._handle_schedule_entry(line)
            return

        # Parse command
        intent = parse_intent(line)
        if line.casefold() in {"run all", "semua", "jalankan semua"}:
            intent = "run all"

        if intent == "exit":
            self.exit()
            return

        if intent == "help":
            self.action_show_commands()
            return

        if intent == "new plan":
            self._append_output("Starting new plan...")
            self._append_output("Type your operational notes and submit.")
            self._budget_source_set = False
            self._budget_check_pending = None
            self._run_all_requested = False
            return

        if intent == "continue":
            self._resume_paused_workflow()
            return

        if line.casefold() in {"schedule add", "tambah jadwal"}:
            if self.agent.current_plan:
                self._budget_check_pending = {"schedule"}
                self._request_schedule_entry()
            else:
                self._append_output("No plan loaded.")
            return

        # Check if we have a plan
        if not self.agent.current_plan:
            # Try to interpret as notes
            if is_operational_notes(line):
                # Install plan from these notes
                self.agent.ingest_notes(line)
                try:
                    plan = self.agent.generate_plan()
                    self._append_output(f"Plan ready: {plan.program}")
                    self._append_output(f"Summary: {plan.summary}")
                except (ConfigurationError, RecoverableLLMError) as e:
                    self._append_output(format_llm_error(e))
                    if isinstance(e, ConfigurationError) and gateway_configured() and needs_setup():
                        self.push_screen(FirstRunSetup(), self._handle_setup)
            else:
                self._append_output("No plan loaded. Type operational notes or 'new plan'.")
            return

        # Handle commands
        if intent == "run all":
            self._start_run_all()
        elif intent == "summary":
            self._append_output(f"{self.agent.current_plan.program}: {self.agent.current_plan.summary}")
        elif intent == "tasks":
            if not self.agent.current_plan.tasks:
                self._append_output("No tasks in the current plan.")
            else:
                for task in self.agent.current_plan.tasks:
                    self._append_output(f"  {task.id}: {task.title} ({task.division or 'division unknown'})")
        elif intent == "set budget":
            self._budget_check_pending = {"budget"}
            self._append_output("Select budget source:")
            self._show_budget_source_modal()
        elif intent in {"check all", "budget", "schedule"}:
            if intent in {"check all", "schedule"} and self._needs_schedule_context():
                self._budget_check_pending = {"budget", "schedule"} if intent == "check all" else {"schedule"}
                self._request_schedule_entry()
                return
            self._budget_check_pending = {"budget", "schedule"} if intent == "check all" else {intent}
            if "budget" in self._budget_check_pending and not self._budget_source_set and self.agent:
                self._append_output("Select budget source:")
                self._show_budget_source_modal()
            else:
                selected = self._budget_check_pending if self._budget_check_pending else set()
                results = self.agent.run_checks(check_types=selected)
                for check in selected or {"budget", "schedule"}:
                    for result in results.get(check, []):
                        self._append_output(f"[{result.status.upper()}] {check} {result.task_id}: {result.message}")
                self._budget_check_pending = None
        elif intent == "tickets":
            if not self.agent.created_ticket_tasks:
                self._append_output("No tickets created in this session.")
            else:
                for i, tid in enumerate(self.agent.created_ticket_tasks):
                    self._append_output(f"  OPS-{i+1:03d}: {tid}")
        elif intent == "create tickets":
            self._start_ticket_workflow()
        elif intent == "status":
            plan = self.agent.current_plan
            required = sum(1 for task in plan.tasks for check in self.agent.get_required_checks_for_task(task))
            completed = len(self.agent.observations)
            self._append_output(f"Checks completed: {completed}/{required}")
            unresolved = self.agent._get_unresolved_task_ids()
            self._append_output(f"Unresolved tasks: {', '.join(unresolved) if unresolved else 'none'}")
            self._append_output(f"Tickets created this session: {len(self.agent.created_ticket_tasks)}")
            if self.agent.workflow_paused:
                self._append_output(
                    f"Workflow: paused — type 'continue' to resume (up to {MAX_AGENT_STEPS} more actions)"
                )
            self._append_output(f"Remaining checks: {self.agent.count_missing_checks()}")
            next_action = f"Next action: {plan.next_action.value}"
            if self.agent.workflow_paused:
                next_action += " ('continue' available)"
            self._append_output(next_action)
        else:
            self._append_output("Unknown command. Type 'help' for commands.")

        self._append_output("")  # Blank line after output

    @staticmethod
    def _format_budget(value: Optional[float]) -> str:
        return f"Rp{value:,.0f}" if value is not None else "not specified"

    def _start_run_all(self) -> None:
        """Present the plan clearly, then reuse the existing checks and HITL flow."""
        plan = self.agent.current_plan
        self._run_all_requested = True
        self._current_view = "OVERVIEW"
        self._output_lines = []
        self._set_view_title("OVERVIEW")
        self._append_output(
            "PROGRAM OVERVIEW\n"
            f"Program : {plan.program}\n"
            f"Summary : {plan.summary}\n"
            f"Tasks   : {len(plan.tasks)}"
        )
        self._append_output("\nTASK DETAILS")
        for task in plan.tasks:
            self._append_output(
                f"{task.id} — {task.title}\n"
                f"  Division : {task.division or 'not specified'}\n"
                f"  PIC      : {task.pic or 'not specified'}\n"
                f"  Deadline : {task.deadline or 'not specified'}\n"
                f"  Budget   : {self._format_budget(task.budget_required)}"
            )
        total_budget = sum(task.budget_required or 0 for task in plan.tasks)
        self._append_output(
            f"\nTOTAL TASK BUDGET: {self._format_budget(total_budget) if total_budget else 'not specified'}"
        )
        self._append_output("\nNEXT: operational checks and ticket approval")
        self._start_ticket_workflow()

    def _append_run_all_report(self) -> None:
        if not self._run_all_requested:
            return
        plan = self.agent.current_plan
        budget_checks = [obs for obs in self.agent.observations if obs.action == "check_budget"]
        schedule_checks = [obs for obs in self.agent.observations if obs.action == "check_schedule"]
        unresolved = self.agent._get_unresolved_task_ids()
        self._append_output("\nFINAL RECAP")
        self._append_output(
            "Budget\n"
            f"  Available : {self._format_budget(self.agent.runtime_context.available_budget)}\n"
            f"  Result    : {', '.join(obs.status for obs in budget_checks) or 'not required'}"
        )
        self._append_output(
            "Schedule\n"
            f"  Known entries : {len(self.agent.runtime_context.schedule_entries or [])}\n"
            f"  Result        : {', '.join(obs.status for obs in schedule_checks) or 'not required'}"
        )
        self._append_output(
            "Tickets and status\n"
            f"  Tickets created : {len(self.agent.created_ticket_tasks)}/{len(plan.tasks)}\n"
            f"  Unresolved      : {', '.join(unresolved) if unresolved else 'none'}\n"
            f"  Workflow        : {plan.next_action.value}"
        )
        self._run_all_requested = False

    def _needs_schedule_context(self) -> bool:
        if not self.agent or not self.agent.current_plan:
            return False
        if not any("schedule" in self.agent.get_required_checks_for_task(task)
                   for task in self.agent.current_plan.tasks):
            return False
        if self.agent.runtime_context.schedule_entries is not None:
            return False
        from opshub.tools.schedule import load_schedules
        return not load_schedules()

    def _request_schedule_entry(self) -> None:
        self._schedule_input_pending = True
        self._append_output(
            "No known schedule entries are loaded. A task deadline alone cannot reveal "
            "a conflict. Enter an existing booking as YYYY-MM-DD | event name, "
            "type 'none' to confirm the schedule is empty, or 'cancel'."
        )

    def _handle_schedule_entry(self, line: str) -> None:
        if line.casefold() == "cancel":
            self._schedule_input_pending = False
            self._ticket_workflow_requested = False
            self._budget_check_pending = None
            self._append_output("Schedule input cancelled; no check was run.")
            self._append_run_all_report()
            return
        from opshub.tools.schedule import load_schedules
        entries = list(self.agent.runtime_context.schedule_entries
                       if self.agent.runtime_context.schedule_entries is not None
                       else load_schedules())
        if line.casefold() == "none":
            self._append_output("Confirmed: no other schedule entries are known.")
        else:
            parts = [part.strip() for part in line.split("|", 1)]
            if len(parts) != 2 or not parts[1]:
                self._append_output("Use YYYY-MM-DD | event name, 'none', or 'cancel'.")
                return
            try:
                booking_date = date.fromisoformat(parts[0]).isoformat()
            except ValueError:
                self._append_output("Invalid date. Use YYYY-MM-DD | event name.")
                return
            entries.append({"date": booking_date, "name": parts[1]})
            self._append_output(f"Known booking added for this session: {parts[1]} on {booking_date}.")
        self.agent.set_schedule_entries(entries, ContextSource.HUMAN)
        self._schedule_input_pending = False
        if self._ticket_workflow_requested:
            self._start_ticket_workflow()
        else:
            self._budget_check_pending = self._budget_check_pending or {"schedule"}
            if "budget" in self._budget_check_pending and self.agent.runtime_context.available_budget is None:
                self._show_budget_source_modal()
            else:
                self._execute_pending_budget_checks()

    def _start_ticket_workflow(self) -> None:
        if self._workflow_worker is not None:
            self._append_output("Agent workflow is still running.")
            return
        plan = self.agent.current_plan
        if plan.next_action == NextAction.COMPLETED:
            self._append_output("Workflow already completed.")
            self._append_run_all_report()
            return
        if plan.next_action == NextAction.WAIT_FOR_HUMAN and self.agent.observations:
            self._show_human_review_guidance()
            self._append_run_all_report()
            return
        self._ticket_workflow_requested = True
        if (any("budget" in self.agent.get_required_checks_for_task(task) for task in plan.tasks)
                and self.agent.runtime_context.available_budget is None):
            self._append_output("Select an available budget before creating tickets.")
            self._show_budget_source_modal()
            return
        if self._needs_schedule_context():
            self._request_schedule_entry()
            return
        self._ticket_workflow_requested = False
        self._workflow_seen = len(self.agent.observations)
        self._append_output("Running agent workflow...")
        self.query_one(StatusLine).status = "working"
        self._workflow_worker = self.run_worker(
            self.agent.run_agent_loop, thread=True, exit_on_error=False,
            name="ticket-workflow",
        )

    def _resume_paused_workflow(self) -> None:
        """Resume a step-limit-paused workflow with preserved state."""
        if self._workflow_worker is not None:
            self._append_output("Agent workflow is still running.")
            return
        plan = self.agent.current_plan
        if plan is None:
            self._append_output("No plan loaded.")
            return
        if plan.next_action == NextAction.COMPLETED:
            self._append_output("Workflow already completed.")
            return
        if not self.agent.workflow_paused:
            self._append_output("No paused workflow to continue.")
            return
        self._ticket_workflow_requested = False
        self._workflow_seen = len(self.agent.observations)
        self._append_output("Resuming agent workflow from preserved state...")
        self.query_one(StatusLine).status = "working"
        self._workflow_worker = self.run_worker(
            self.agent.resume_workflow, thread=True, exit_on_error=False,
            name="ticket-workflow",
        )

    def _show_paused_guidance(self) -> None:
        """Explain a bounded-autonomy pause; the workflow is safe to resume."""
        self._append_output(
            "AUTONOMOUS RUN PAUSED\n"
            "\n"
            "The six-step safety limit was reached.\n"
            "Completed work has been preserved.\n"
            "\n"
            "Type `continue` to resume from the current state.\n"
            "Type `status` to inspect remaining work.\n"
            "Press Ctrl+L to inspect ACTIVITY."
        )

    def _show_human_review_guidance(self) -> None:
        """Explain why automation stopped and give safe, concrete next steps."""
        latest_checks = {}
        for observation in self.agent.observations:
            if observation.action in {"check_budget", "check_schedule"}:
                latest_checks[(observation.action, observation.task_id)] = observation
        blockers = [observation for observation in latest_checks.values()
                    if observation.status in {"failed", "missing_context"}]
        rejected = [approval.task_id for approval in self.agent.approvals
                    if approval.status.value == "rejected"]
        audit_events = {event["event"] for event in self.agent.audit_log.events[-8:]}

        lines = ["HUMAN REVIEW REQUIRED", "Why automation stopped:"]
        if blockers:
            for observation in blockers:
                check = observation.action.removeprefix("check_").capitalize()
                lines.append(f"  - {observation.task_id} — {check}: {observation.message}")
        if rejected:
            lines.append(f"  - Ticket approval was rejected for: {', '.join(rejected)}.")
        if "agent_step_limit_reached" in audit_events:
            lines.append("  - The agent reached its six-step safety limit before completion.")
        if "agent_stalled" in audit_events:
            lines.append("  - The agent repeated an invalid action and was stopped safely.")
        if "agent_action_failed" in audit_events:
            lines.append("  - The AI provider failed while selecting the next action.")
        if len(lines) == 2:
            interrupt = next((observation for observation in reversed(self.agent.observations)
                              if observation.action == "request_human_review"), None)
            reason = interrupt.details.get("reason") if interrupt else None
            lines.append(f"  - {reason or 'The workflow needs a human decision before it can continue.'}")

        lines.append("What to do:")
        if any(observation.action == "check_budget" for observation in blockers):
            lines.append("  1. Verify the available budget and the task requirement.")
            lines.append("  2. If the amount was wrong, restart OpsHub and enter the corrected manual budget.")
        if any(observation.action == "check_schedule" for observation in blockers):
            lines.append("  1. Resolve or move the conflicting booking/date.")
            lines.append("  2. Restart OpsHub with the corrected notes or schedule entries.")
        if rejected:
            lines.append("  - No rejected ticket was created. Restart only if you now intend to approve it.")
        if audit_events & {"agent_step_limit_reached", "agent_stalled", "agent_action_failed"}:
            lines.append("  - Type 'continue' to resume a paused run from the current state.")
        lines.append("  - Press Ctrl+L to inspect ACTIVITY.")
        lines.append("  - Type status for the unresolved tasks. Press Ctrl+Q to exit safely.")
        self._append_output("\n".join(lines))

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._workflow_worker or event.state not in {
            WorkerState.SUCCESS, WorkerState.ERROR,
        }:
            return
        worker = self._workflow_worker
        self._workflow_worker = None
        self.query_one(StatusLine).status = "ready"
        if event.state == WorkerState.ERROR:
            self.agent.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
            self._append_output(f"Agent workflow failed: {worker.error}")
            self._show_human_review_guidance()
            self._append_run_all_report()
            return
        success, _ = worker.result
        new_observations = self.agent.observations[self._workflow_seen:]
        for observation in new_observations:
            self._append_output(
                f"[{observation.status.upper()}] {observation.action} "
                f"for {observation.task_id}: {observation.message}"
            )
        if not success:
            self._append_output("Agent loop failed.")
            self._show_human_review_guidance()
            self._append_run_all_report()
        elif self.agent.current_plan.next_action == NextAction.READY_TO_CREATE_TICKET:
            proposal = next((obs for obs in reversed(new_observations)
                             if obs.action == "propose_ticket_creation" and obs.status == "ready"), None)
            task = next((task for task in self.agent.current_plan.tasks
                         if proposal and task.id == proposal.task_id), None)
            if task is None:
                self.agent.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
                self._append_output("No valid ticket proposal found.")
                self._show_human_review_guidance()
                self._append_run_all_report()
                return
            self.agent.request_approval(task.id, "create_ticket")
            self.push_screen(
                TicketConfirmModal(f"Create ticket for {task.id}?"),
                callback=partial(self._handle_ticket_confirmation, task),
            )
        elif self.agent.current_plan.next_action == NextAction.COMPLETED:
            self._append_output("Workflow completed.")
            self._append_run_all_report()
        else:
            if self.agent.workflow_paused:
                self._show_paused_guidance()
            else:
                self._show_human_review_guidance()
            self._append_run_all_report()

    def _handle_ticket_confirmation(self, task: Task, confirmed: bool) -> None:
        """Resume ticket creation after the HITL modal resolves."""
        if not self.agent:
            return
        if confirmed:
            if not self.agent.grant_approval(task.id):
                self._append_output("Ticket approval was not recorded.")
                self.agent.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
                self._append_run_all_report()
                return
            ticket_id = self.agent.create_ticket(task)
            if ticket_id:
                self._append_output(f"Ticket {ticket_id} created.")
                self._start_ticket_workflow()
            else:
                self._append_output("Ticket creation failed.")
                self.agent.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
                self._append_run_all_report()
        else:
            self.agent.reject_approval(task.id)
            self._append_output(f"Ticket for {task.id} rejected.")
            self.agent.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
            self._show_human_review_guidance()
            self._append_run_all_report()

    def _show_budget_source_modal(self) -> None:
        """Show budget source selection modal."""
        self.push_screen(
            BudgetSourceModal(),
            callback=self._handle_budget_source,
        )

    def _handle_budget_source(self, source: Optional[int]) -> None:
        """Handle budget source selection."""
        if source == 1:
            # Use runtime data
            from opshub.tools.budget import load_budgets
            budget = load_budgets()
            available = budget.get("available", 0) - budget.get("allocated", 0)
            self.agent.set_budget(available, ContextSource.RUNTIME_FILE)
            self._budget_source_set = True
            self._append_output(f"Using runtime budget: Rp{available:,.0f}")
            if self._ticket_workflow_requested:
                self._start_ticket_workflow()
            else:
                self._execute_pending_budget_checks()
        elif source == 2:
            # Show manual input modal
            self.push_screen(
                ManualBudgetModal(),
                callback=self._handle_manual_budget,
            )
        else:
            self._ticket_workflow_requested = False
            self._budget_check_pending = None
            self._append_output("Budget source selection cancelled.")
            self._append_run_all_report()

    def _handle_manual_budget(self, value: Optional[str]) -> None:
        """Handle manual budget input."""
        if value is None:
            self._ticket_workflow_requested = False
            self._budget_check_pending = None
            self._append_output("Budget entry cancelled.")
            self._append_run_all_report()
            return

        try:
            amount = parse_budget_input(value)
            self.agent.set_budget(amount, ContextSource.HUMAN)
            self._budget_source_set = True
            self._append_output(f"Budget set: Rp{amount:,.0f}")
            self._append_output("Source: manual")
            if self._ticket_workflow_requested:
                self._start_ticket_workflow()
            else:
                self._execute_pending_budget_checks()
        except ValueError:
            self._append_output(f"Invalid input: {value}. Try a number like 15000000 or 15,000,000.")

    def _execute_pending_budget_checks(self) -> None:
        """Execute pending budget checks after budget is set."""
        if self._budget_check_pending and self.agent:
            results = self.agent.run_checks(check_types=self._budget_check_pending)
            for check in self._budget_check_pending:
                for result in results.get(check, []):
                    self._append_output(f"[{result.status.upper()}] {check} {result.task_id}: {result.message}")
            self._budget_check_pending = None


def main() -> int:
    """Launch the TUI."""
    try:
        protected = load_configuration()
        app = OpsHubApp(
            setup_required="--setup" in sys.argv[1:] or (
                not gateway_configured()
                and needs_setup()
            ),
            setup_protected=protected,
        )
        app.run()
        return 0
    except KeyboardInterrupt:
        return 0
