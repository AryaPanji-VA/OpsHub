"""Main terminal UI application for OpsHub."""

from functools import partial
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Input, Static, Label
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import events
from typing import Any, List, Optional
from opshub.agent import OpsHubAgent
from opshub.llm import get_llm_provider
from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.cli import format_llm_error
from opshub.repl import parse_intent, is_operational_notes
from opshub.models import NextAction, Task

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
        return "tab tasks   ctrl+v views   ctrl+p commands   ctrl+l logs   ? help   ctrl+q quit"


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
    }
    #view-title {
        color: #C7B166;
        text-style: bold;
    }
    #view-content {
        color: #e0e0e0;
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
        Binding("ctrl+p", "show_commands", "Commands", priority=True),
        Binding("ctrl+l", "show_logs", "Logs", priority=True),
        Binding("question_mark", "show_help", "Help"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    VIEW_TITLES = {
        "PLAN": "PLAN",
        "TASKS": "TASKS",
        "ACTIVITY": "ACTIVITY",
        "TICKETS": "TICKETS",
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.agent: Optional[OpsHubAgent] = None
        self.agent_error: Optional[str] = None
        self._current_view: str = "INPUT"
        self._output_lines: List[str] = []
        self._input_buffer: str = ""

    def compose(self) -> ComposeResult:
        with Container(id="main-container"):
            yield OpsHubHeader()
            yield StatusLine(id="status-line")
            yield Input(placeholder=INPUT_PLACEHOLDER, id="input-field")
            with Vertical(id="output-container"):
                yield Label("PLAN", id="view-title")
                yield Static("", id="view-content")
            yield ShortcutHints(id="shortcut-hints")
            yield BottomStatus(id="footer-status")

    def on_mount(self) -> None:
        self._init_agent()
        self.query_one("#input-field", Input).focus()

    def _init_agent(self) -> None:
        """Initialize the agent with LLM provider."""
        try:
            self.agent = OpsHubAgent(llm_provider=get_llm_provider())
            self.query_one(StatusLine).status = "ready"
            self.query_one(StatusLine).provider = "Qwen 3.8 27B"
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
            self.query_one("#output-container", Vertical).scroll_end(animate=False)
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
            "  summary       Show program summary\n"
            "  tasks         List all tasks\n"
            "  check all     Run all checks\n"
            "  budget        Check budget\n"
            "  schedule      Check schedule\n"
            "  tickets       Show created tickets\n"
            "  create tickets Create tickets from workflow\n"
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

        # Parse command
        intent = parse_intent(line)

        if intent == "exit":
            self.exit()
            return

        if intent == "help":
            self.action_show_commands()
            return

        if intent == "new plan":
            self._append_output("Starting new plan...")
            self._append_output("Type your operational notes and submit.")
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
            else:
                self._append_output("No plan loaded. Type operational notes or 'new plan'.")
            return

        # Handle commands
        if intent == "summary":
            self._append_output(f"{self.agent.current_plan.program}: {self.agent.current_plan.summary}")
        elif intent == "tasks":
            if not self.agent.current_plan.tasks:
                self._append_output("No tasks in the current plan.")
            else:
                for task in self.agent.current_plan.tasks:
                    self._append_output(f"  {task.id}: {task.title} ({task.division or 'division unknown'})")
        elif intent in {"check all", "budget", "schedule"}:
            selected = None if intent == "check all" else {intent}
            results = self.agent.run_checks(check_types=selected)
            for check in (selected or {"budget", "schedule"}):
                for result in results.get(check, []):
                    self._append_output(f"[{result.status.upper()}] {check} {result.task_id}: {result.message}")
        elif intent == "tickets":
            if not self.agent.created_ticket_tasks:
                self._append_output("No tickets created in this session.")
            else:
                for i, tid in enumerate(self.agent.created_ticket_tasks):
                    self._append_output(f"  OPS-{i+1:03d}: {tid}")
        elif intent == "create tickets":
            if self.agent.current_plan.next_action == NextAction.COMPLETED:
                self._append_output("Workflow already completed.")
            elif self.agent.current_plan.next_action == NextAction.WAIT_FOR_HUMAN and self.agent.observations:
                self._append_output("Human review is required before continuing.")
            else:
                # Run the workflow
                self._append_output("Running agent workflow...")
                for obs in self.agent.observations:
                    self._append_output(f"[{obs.status.upper()}] {obs.action} for {obs.task_id}: {obs.message}")

                # Check if ticket creation is proposed
                ready_obs = [o for o in self.agent.observations if o.action == "propose_ticket_creation" and o.status == "ready"]
                if ready_obs:
                    task_id = ready_obs[0].task_id
                    task = next((t for t in self.agent.current_plan.tasks if t.id == task_id), None)
                    if task:
                        # HITL confirmation via modal; resume in callback
                        self.push_screen(
                            TicketConfirmModal(f"Create ticket for {task.id}?"),
                            callback=partial(self._handle_ticket_confirmation, task),
                        )
        elif intent == "status":
            plan = self.agent.current_plan
            required = sum(1 for task in plan.tasks for check in self.agent.get_required_checks_for_task(task))
            completed = len(self.agent.observations)
            self._append_output(f"Checks completed: {completed}/{required}")
            unresolved = self.agent._get_unresolved_task_ids()
            self._append_output(f"Unresolved tasks: {', '.join(unresolved) if unresolved else 'none'}")
            self._append_output(f"Tickets created this session: {len(self.agent.created_ticket_tasks)}")
            self._append_output(f"Next action: {plan.next_action.value}")
        else:
            self._append_output("Unknown command. Type 'help' for commands.")

        self._append_output("")  # Blank line after output

    def _handle_ticket_confirmation(self, task: Task, confirmed: bool) -> None:
        """Resume ticket creation after the HITL modal resolves."""
        if not self.agent:
            return
        if confirmed:
            self.agent.grant_approval(task.id)
            ticket_id = self.agent.create_ticket(task)
            if ticket_id:
                self._append_output(f"Ticket {ticket_id} created.")
            else:
                self._append_output("Ticket creation failed.")
        else:
            self.agent.reject_approval(task.id)
            self._append_output(f"Ticket for {task.id} rejected.")


def main() -> int:
    """Launch the TUI."""
    try:
        app = OpsHubApp()
        app.run()
        return 0
    except KeyboardInterrupt:
        return 0
