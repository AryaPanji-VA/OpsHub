"""The demo gateway must not disturb direct provider or first-run setup."""

import importlib.util
from pathlib import Path

import httpx
import pytest

from opshub.llm import get_llm_provider
from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.llm.gateway import GatewayFirstProvider, GatewayProvider
from opshub.llm.qwen import OPERATIONAL_PLAN_SCHEMA, AGENT_ACTION_SCHEMA
from opshub.models import OperationalPlan


MODULE_PATH = Path(__file__).parents[1] / "gateway" / "api" / "llm.py"
spec = importlib.util.spec_from_file_location("demo_gateway", MODULE_PATH)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

PLAN = {
    "program": "Demo", "summary": "One task", "tasks": [],
    "checks_required": [], "risk_flags": [], "next_action": "wait_for_human",
}


def test_gateway_success_and_fixed_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "server-only-secret")
    captured = {}

    def fake_groq(body, key):
        captured.update(body)
        assert key == "server-only-secret"
        return {"choices": [{"message": {"content": __import__("json").dumps(PLAN)}}]}

    result = server.run_request({"operation": "plan", "meeting_notes": "Plan a demo"}, call_groq=fake_groq)
    assert result == {"result": PLAN}
    assert captured["model"] == "qwen/qwen3.8-27b"
    assert captured["max_tokens"] <= 1200
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert "server-only-secret" not in str(result)


def test_standalone_gateway_schemas_match_direct_provider():
    assert server.PLAN_SCHEMA == OPERATIONAL_PLAN_SCHEMA
    assert server.ACTION_SCHEMA == AGENT_ACTION_SCHEMA


def test_gateway_client_success_and_no_secret_sent(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "client-secret-must-not-travel")
    monkeypatch.setenv("OPSHUB_GATEWAY_URL", "https://demo.example")

    def fake_post(url, *, json, timeout):
        assert url == "https://demo.example/api/llm"
        assert json == {"operation": "plan", "meeting_notes": "Demo notes"}
        assert "client-secret-must-not-travel" not in str(json)
        return httpx.Response(200, json={"result": PLAN}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    assert get_llm_provider().generate_plan("Demo notes").program == "Demo"


def test_gateway_unavailable_uses_direct_provider(monkeypatch):
    from opshub.llm import gateway as gateway_module

    monkeypatch.setenv("GROQ_API_KEY", "configured-direct-key")
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("OPSHUB_GATEWAY_URL", "https://demo.example")

    def broken_post(*args, **kwargs):
        raise httpx.ConnectError("gateway offline")

    class Direct:
        def generate_plan(self, notes):
            return OperationalPlan.model_validate(PLAN)

    monkeypatch.setattr(httpx, "post", broken_post)
    monkeypatch.setattr("opshub.llm.get_direct_llm_provider", lambda: Direct())
    assert get_llm_provider().generate_plan("Demo notes").program == "Demo"


def test_malformed_gateway_response_falls_back(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "configured-direct-key")
    monkeypatch.setenv("OPSHUB_GATEWAY_URL", "https://demo.example")

    def malformed_post(url, **kwargs):
        return httpx.Response(200, json={"result": {"unexpected": True}}, request=httpx.Request("POST", url))

    class Direct:
        def generate_plan(self, notes):
            return OperationalPlan.model_validate(PLAN)

    monkeypatch.setattr(httpx, "post", malformed_post)
    monkeypatch.setattr("opshub.llm.get_direct_llm_provider", lambda: Direct())
    assert get_llm_provider().generate_plan("Demo notes").program == "Demo"


def test_gateway_down_without_key_asks_for_existing_setup(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = GatewayFirstProvider(GatewayProvider("https://demo.example"))
    monkeypatch.setattr(provider.gateway, "generate_plan", lambda notes: (_ for _ in ()).throw(
        RecoverableLLMError("offline", provider="gateway")))
    with pytest.raises(ConfigurationError, match="opshub --setup"):
        provider.generate_plan("Demo notes")


def test_gateway_rejects_proxy_fields_and_large_payload():
    with pytest.raises(ValueError):
        server.build_messages({"operation": "plan", "meeting_notes": "hello", "model": "other"})
    with pytest.raises(ValueError):
        server.build_messages({"operation": "plan", "meeting_notes": "x" * 20_001})
    with pytest.raises(ConfigurationError):
        GatewayProvider("http://external.example")


def test_action_prompt_preserves_check_state():
    task = {"id": "T1", "title": "Prepare room", "budget_required": 50, "deadline": "Friday"}
    messages, tokens = server.build_messages({
        "operation": "action",
        "plan": {"program": "Demo", "tasks": [task]},
        "observations": [{"action": "check_budget", "task_id": "T1", "status": "clear", "message": "Enough"}],
        "runtime_context": {"available_budget": 100},
    })
    assert "budget: clear, schedule: missing" in messages[1]["content"]
    assert "check_schedule T1" in messages[1]["content"]
    assert tokens == 150


def test_gateway_server_does_not_log_secret(monkeypatch, capsys):
    secret = "server-only-secret"
    monkeypatch.setenv("GROQ_API_KEY", secret)

    def broken_groq(body, key):
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError):
        server.run_request({"operation": "plan", "meeting_notes": "Demo"}, call_groq=broken_groq)
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
