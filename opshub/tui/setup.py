"""First-run credential screen for the terminal launcher."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class FirstRunSetup(ModalScreen[tuple[str, str] | None]):
    CSS = """
    FirstRunSetup { align: center middle; background: #1a1a1a; }
    #setup-dialog {
        width: 66; height: auto; padding: 1 2;
        border: round #C7B166; background: #2a2a2a; color: #e0e0e0;
    }
    #setup-title { color: #C7B166; text-style: bold; margin-bottom: 1; }
    #setup-dialog Label { margin-top: 1; }
    #setup-dialog Input { width: 100%; }
    #setup-error { color: #f28b82; height: auto; }
    #setup-buttons { height: auto; margin-top: 1; }
    #setup-save { margin-right: 2; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-dialog"):
            yield Static("OpsHub First-Time Setup", id="setup-title")
            yield Static("Primary model: Qwen 3.8 27B via Groq")
            yield Static("Fallback model: Nex N2.5 Pro via OpenRouter (optional)")
            yield Label("Groq API Key (required)")
            yield Input(password=True, id="setup-groq")
            yield Label("OpenRouter API Key (optional)")
            yield Input(password=True, id="setup-openrouter")
            yield Static("", id="setup-error")
            with Horizontal(id="setup-buttons"):
                yield Button("Save & Continue", id="setup-save", variant="primary")
                yield Button("Cancel", id="setup-cancel")

    def on_mount(self) -> None:
        self.query_one("#setup-groq", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "setup-cancel":
            self.dismiss(None)
            return
        groq = self.query_one("#setup-groq", Input).value.strip()
        openrouter = self.query_one("#setup-openrouter", Input).value.strip()
        if not groq:
            self.query_one("#setup-error", Static).update("Groq API Key is required.")
            return
        if any(char in key for key in (groq, openrouter) for char in "\r\n\x00"):
            self.query_one("#setup-error", Static).update("Keys must be single-line values.")
            return
        self.dismiss((groq, openrouter))
