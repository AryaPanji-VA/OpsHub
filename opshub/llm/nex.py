import json
import os
from typing import List

from opshub.models import OperationalPlan, AgentActionModel, AgentAction, AgentObservation, RuntimeContext, NextAction
from opshub.llm.base import LLMProvider
from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.llm.qwen import OPERATIONAL_PLAN_SCHEMA, AGENT_ACTION_SCHEMA
from opshub.checks import format_task_check_context


class NexProvider(LLMProvider):
    """Nex LLM provider via OpenRouter API."""

    def __init__(self):
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ConfigurationError(
                "OPENROUTER_API_KEY environment variable not set",
                provider="nex",
                category="configuration",
            )

        self.model = os.getenv("OPENROUTER_MODEL", "nex-agi/nex-n2.5-pro:free")
        self.api_key = api_key
        self.base_url = "https://openrouter.ai/api/v1"

    def generate_plan(self, meeting_notes: str) -> OperationalPlan:
        """Generate operational plan from meeting notes using Nex via OpenRouter."""
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx package not installed. Run: pip install httpx")

        system_prompt = """You are the OpsHub Operational Planning Agent.

RULES:
- Never invent missing information. If not explicitly stated, use null.
- Extract ONLY what is clearly present in the notes.
- Each distinct task becomes a separate Task object.
- Supported checks: budget, schedule
- next_action: use "run_tools" if checks needed, else "wait_for_human"

Output ONLY valid JSON matching the required schema."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://opshub.ai",
            "X-Title": "OpsHub",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Meeting notes:\n\n{meeting_notes}"},
            ],
            "temperature": 0,
            "max_tokens": 2000,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "operational_plan",
                    "schema": OPERATIONAL_PLAN_SCHEMA,
                    "strict": True,
                },
            },
        }

        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
        except httpx.TimeoutException:
            raise RecoverableLLMError(
                "Nex/OpenRouter request timed out.",
                provider="nex",
                category="timeout",
            )
        except httpx.ConnectError:
            raise RecoverableLLMError(
                "Cannot connect to Nex/OpenRouter API.",
                provider="nex",
                category="network",
            )

        if response.status_code == 429:
            raise RecoverableLLMError(
                "Rate limit exceeded on Nex/OpenRouter.",
                provider="nex",
                category="rate_limit",
            )
        elif response.status_code >= 500:
            raise RecoverableLLMError(
                f"Server error: {response.status_code}.",
                provider="nex",
                category="server_error",
            )

        try:
            data = response.json()
        except json.JSONDecodeError:
            raise RecoverableLLMError(
                "Malformed JSON response from Nex/OpenRouter.",
                provider="nex",
                category="parse_error",
            )

        choices = data.get("choices", [])
        if not choices:
            raise RecoverableLLMError(
                "Empty response from Nex/OpenRouter.",
                provider="nex",
                category="empty_response",
            )

        raw_content = choices[0].get("message", {}).get("content", "")

        if not raw_content:
            raise RecoverableLLMError(
                "Empty content in Nex/OpenRouter response.",
                provider="nex",
                category="empty_response",
            )

        try:
            response_json = json.loads(raw_content)
        except json.JSONDecodeError:
            raise RecoverableLLMError(
                "Malformed JSON in Nex/OpenRouter response.",
                provider="nex",
                category="parse_error",
            )

        return self._parse_plan(response_json)

    def _parse_plan(self, data: dict) -> OperationalPlan:
        """Validate and convert JSON response to OperationalPlan."""
        try:
            return OperationalPlan.model_validate(data)
        except Exception as e:
            raise RecoverableLLMError(
                f"OperationalPlan validation failed: {e}",
                provider="nex",
                category="validation",
            )

    def choose_next_action(
        self,
        plan: OperationalPlan,
        observations: List[AgentObservation],
        runtime_context: RuntimeContext,
    ) -> AgentActionModel:
        """Choose the next allowed action using Nex via OpenRouter."""
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx package not installed. Run: pip install httpx")

        tasks_summary = "\n".join(
            f"- {t.id}: {t.title}"
            for t in plan.tasks
        )

        obs_summary = "\n".join(
            f"- {o.action} {o.task_id}: {o.status}. {o.message}"
            for o in observations
        )
        check_context = format_task_check_context(plan.tasks, observations)

        system_prompt = """You are OpsHub's orchestration planner.

RULES:
- Choose EXACTLY ONE next action
- Allowed actions: check_budget, check_schedule, request_human_review, propose_ticket_creation, finish
- Never invent new tools
- Use request_human_review when conflicts exist
- If a read-only check remains missing, select that check before requesting human review or proposing a ticket.
- An already_checked observation means that check is clear; use the listed remaining checks.
- A clear check does not complete a task. Propose ticket creation for each task that lacks a ticket_created observation.
- A rejected finish observation explains what is still required. Follow it.
- Use finish with task_id=null only after every operational task has a ticket_created observation.

Output ONLY JSON."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://opshub.ai",
            "X-Title": "OpsHub",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"""Current plan: {plan.program}
Tasks:
{tasks_summary}

Observations:
{obs_summary if obs_summary else "None"}

Per-task check state:
{check_context}

Choose next action as JSON.""",
                },
            ],
            "temperature": 0,
            "max_tokens": 150,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_action",
                    "schema": AGENT_ACTION_SCHEMA,
                    "strict": True,
                },
            },
        }

        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
        except httpx.TimeoutException:
            raise RecoverableLLMError(
                "Nex/OpenRouter action selection timed out.",
                provider="nex",
                category="timeout",
            )
        except httpx.ConnectError:
            raise RecoverableLLMError(
                "Cannot connect to Nex/OpenRouter API.",
                provider="nex",
                category="network",
            )

        if response.status_code == 429:
            raise RecoverableLLMError(
                "Rate limit exceeded on Nex/OpenRouter.",
                provider="nex",
                category="rate_limit",
            )

        try:
            data = response.json()
        except json.JSONDecodeError:
            raise RecoverableLLMError(
                "Malformed JSON action response.",
                provider="nex",
                category="parse_error",
            )

        choices = data.get("choices", [])
        if not choices:
            raise RecoverableLLMError(
                "Empty action response.",
                provider="nex",
                category="empty_response",
            )

        raw_content = choices[0].get("message", {}).get("content", "")

        if not raw_content:
            raise RecoverableLLMError(
                "Empty content in action response.",
                provider="nex",
                category="empty_response",
            )

        try:
            action_data = json.loads(str(raw_content).strip())
            return AgentActionModel.model_validate(action_data)
        except Exception as e:
            raise RecoverableLLMError(
                f"AgentAction validation failed: {e}",
                provider="nex",
                category="validation",
            )
