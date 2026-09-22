"""Narrow demo gateway client; never sends a provider credential."""

import os
from typing import List
from urllib.parse import urlparse

import httpx

from opshub.llm.base import LLMProvider
from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.models import AgentActionModel, AgentObservation, OperationalPlan, RuntimeContext


def gateway_configured() -> bool:
    return bool(os.getenv("OPSHUB_GATEWAY_URL", "").strip())


class GatewayProvider(LLMProvider):
    def __init__(self, url: str | None = None):
        origin = (url or os.getenv("OPSHUB_GATEWAY_URL", "")).strip().rstrip("/")
        parsed = urlparse(origin)
        if not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ConfigurationError("Invalid gateway origin", provider="gateway", category="configuration")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            raise ConfigurationError("Gateway requires HTTPS", provider="gateway", category="configuration")
        self.endpoint = origin + "/api/llm"

    def _request(self, payload: dict) -> dict:
        try:
            response = httpx.post(self.endpoint, json=payload, timeout=15.0)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or set(body) != {"result"} or not isinstance(body["result"], dict):
                raise ValueError("Invalid gateway response")
            return body["result"]
        except (httpx.HTTPError, ValueError):
            # Do not include response bodies, URLs or transport exceptions: they may contain input.
            raise RecoverableLLMError("Demo gateway unavailable or returned an invalid response.", provider="gateway", category="unavailable") from None

    def generate_plan(self, meeting_notes: str) -> OperationalPlan:
        data = self._request({"operation": "plan", "meeting_notes": meeting_notes})
        try:
            return OperationalPlan.model_validate(data)
        except ValueError:
            raise RecoverableLLMError("Demo gateway returned an invalid plan.", provider="gateway", category="validation") from None

    def choose_next_action(
        self, plan: OperationalPlan, observations: List[AgentObservation], runtime_context: RuntimeContext
    ) -> AgentActionModel:
        data = self._request({
            "operation": "action",
            "plan": plan.model_dump(mode="json"),
            "observations": [item.model_dump(mode="json") for item in observations],
            "runtime_context": runtime_context.model_dump(mode="json"),
        })
        try:
            return AgentActionModel.model_validate(data)
        except ValueError:
            raise RecoverableLLMError("Demo gateway returned an invalid action.", provider="gateway", category="validation") from None


class GatewayFirstProvider(LLMProvider):
    """Try the demo gateway, then construct the existing direct provider lazily."""

    def __init__(self, gateway: LLMProvider):
        self.gateway = gateway

    def _direct(self) -> LLMProvider:
        from opshub.llm import get_direct_llm_provider

        if not os.getenv("GROQ_API_KEY") and not os.getenv("OPENROUTER_API_KEY"):
            raise ConfigurationError(
                "Gateway unavailable; run opshub --setup to configure a direct provider.",
                provider="gateway", category="configuration",
            )
        return get_direct_llm_provider()

    def generate_plan(self, meeting_notes: str) -> OperationalPlan:
        try:
            return self.gateway.generate_plan(meeting_notes)
        except RecoverableLLMError:
            return self._direct().generate_plan(meeting_notes)

    def choose_next_action(
        self, plan: OperationalPlan, observations: List[AgentObservation], runtime_context: RuntimeContext
    ) -> AgentActionModel:
        try:
            return self.gateway.choose_next_action(plan, observations, runtime_context)
        except RecoverableLLMError:
            return self._direct().choose_next_action(plan, observations, runtime_context)
