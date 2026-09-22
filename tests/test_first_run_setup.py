"""Credential onboarding and launch regression tests."""

import asyncio
import os
from pathlib import Path
from unittest.mock import Mock

from dotenv import dotenv_values
from textual.widgets import Button, Input, Static

from opshub import config
from opshub.cli import format_llm_error
from opshub.llm.exceptions import RecoverableLLMError
from opshub.tui.app import OpsHubApp
from opshub.tui import app as tui_app
from opshub.tui.setup import FirstRunSetup
from opshub.agent import OpsHubAgent
from tests.test_runtime_flow import ScriptedProvider


def isolated_config(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "opshub").mkdir()
    monkeypatch.setattr(config, "__file__", str(project / "opshub" / "config.py"))
    path = tmp_path / "user" / "OpsHub" / "config.env"
    monkeypatch.setattr(config, "user_config_path", lambda: path)
    for key in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    return project, path


def test_first_run_and_later_launch(monkeypatch, tmp_path):
    _, path = isolated_config(monkeypatch, tmp_path)
    config.load_configuration()
    assert config.needs_setup()
    config.save_credentials("sample-groq", "")
    assert path.exists()
    assert Path(__file__).parents[1] not in path.parents
    config.load_configuration()
    assert not config.needs_setup()
    assert os.environ["LLM_PROVIDER"] == "qwen"
    assert not os.getenv("OPENROUTER_API_KEY")


def test_optional_fallback_and_required_groq(monkeypatch, tmp_path):
    isolated_config(monkeypatch, tmp_path)
    try:
        config.save_credentials("", "sample-openrouter")
        assert False, "missing Groq key must be rejected"
    except ValueError:
        pass
    config.save_credentials("sample-groq", "sample-openrouter")
    assert dotenv_values(config.user_config_path())["LLM_PROVIDER"] == "fallback"


def test_precedence_and_reset(monkeypatch, tmp_path):
    project, _ = isolated_config(monkeypatch, tmp_path)
    (project / ".env").write_text("GROQ_API_KEY=project-key\nLLM_PROVIDER=qwen\n")
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-key")
    config.save_credentials("old-key", "old-fallback")
    protected = config.load_configuration()
    assert os.environ["GROQ_API_KEY"] == "project-key"
    assert os.environ["OPENROUTER_API_KEY"] == "environment-key"
    assert os.environ["LLM_PROVIDER"] == "qwen"
    config.save_credentials("new-key", "")
    config.apply_saved_credentials(protected)
    assert os.environ["GROQ_API_KEY"] == "project-key"
    assert os.environ["OPENROUTER_API_KEY"] == "environment-key"


def test_reset_replaces_user_config_for_current_run(monkeypatch, tmp_path):
    isolated_config(monkeypatch, tmp_path)
    config.save_credentials("old-key", "old-fallback")
    protected = config.load_configuration()
    config.save_credentials("new-key", "")
    config.apply_saved_credentials(protected)
    assert os.environ["GROQ_API_KEY"] == "new-key"
    assert "OPENROUTER_API_KEY" not in os.environ
    assert os.environ["LLM_PROVIDER"] == "qwen"


def test_setup_screen_requires_groq_and_masks_keys():
    async def scenario():
        app = OpsHubApp(setup_required=True)
        async with app.run_test() as pilot:
            assert isinstance(app.screen, FirstRunSetup)
            groq = app.screen.query_one("#setup-groq", Input)
            fallback = app.screen.query_one("#setup-openrouter", Input)
            assert groq.password and fallback.password
            app.screen.query_one("#setup-save", Button).press()
            await pilot.pause()
            assert "required" in str(app.screen.query_one("#setup-error", Static).render()).lower()

    asyncio.run(scenario())


def test_setup_saves_and_continues_without_fallback(monkeypatch, tmp_path):
    _, path = isolated_config(monkeypatch, tmp_path)
    monkeypatch.setattr("opshub.tui.app.get_llm_provider", lambda: Mock())

    async def scenario():
        app = OpsHubApp(setup_required=True)
        async with app.run_test() as pilot:
            app.screen.query_one("#setup-groq", Input).value = "sample-groq"
            app.screen.query_one("#setup-save", Button).press()
            await pilot.pause()
            assert not isinstance(app.screen, FirstRunSetup)
            assert app.agent is not None

    asyncio.run(scenario())
    assert dotenv_values(path)["GROQ_API_KEY"] == "sample-groq"
    assert os.environ["LLM_PROVIDER"] == "qwen"


def test_existing_config_skips_setup(monkeypatch):
    monkeypatch.setattr("opshub.tui.app.get_llm_provider", lambda: Mock())

    async def scenario():
        app = OpsHubApp()
        async with app.run_test():
            assert not isinstance(app.screen, FirstRunSetup)
            assert app.agent is not None

    asyncio.run(scenario())


def test_launcher_routes_first_run_and_forced_setup(monkeypatch, tmp_path):
    isolated_config(monkeypatch, tmp_path)
    launched = []

    class StubApp:
        def __init__(self, **kwargs):
            launched.append(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(tui_app, "OpsHubApp", StubApp)
    monkeypatch.setattr("sys.argv", ["opshub"])
    assert tui_app.main() == 0
    assert launched[-1]["setup_required"] is True
    config.save_credentials("sample-groq", "")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert tui_app.main() == 0
    assert launched[-1]["setup_required"] is False
    monkeypatch.setattr("sys.argv", ["opshub", "--setup"])
    assert tui_app.main() == 0
    assert launched[-1]["setup_required"] is True


def test_provider_failure_does_not_log_key(monkeypatch, tmp_path, capsys):
    class FailingProvider(ScriptedProvider):
        def choose_next_action(self, plan, observations, runtime_context):
            raise RecoverableLLMError(
                "sample-secret-value", provider="qwen", category="api_error"
            )

    agent = OpsHubAgent(
        llm_provider=FailingProvider([]), tickets_file=tmp_path / "tickets.json"
    )
    agent.ingest_notes("meeting notes")
    agent.generate_plan()
    monkeypatch.setattr("opshub.agent.DEBUG_LOOP", True)
    agent.run_agent_loop()
    assert "sample-secret-value" not in capsys.readouterr().out
    assert "sample-secret-value" not in str(agent.audit_log.events)


def test_provider_error_does_not_echo_key(capsys):
    secret = "sample-secret-value"
    message = format_llm_error(
        RecoverableLLMError(secret, provider="qwen", category="api_error")
    )
    print(message)
    assert secret not in capsys.readouterr().out
