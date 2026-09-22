import json
import os
from typing import List

from opshub.models import OperationalPlan, AgentActionModel, AgentAction, AgentObservation, RuntimeContext, NextAction
from opshub.llm.base import LLMProvider
from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.checks import format_task_check_context


# Schema from OperationalPlan model (shared)
OPERATIONAL_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "program": {"type": "string"},
        "summary": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "division": {"type": ["string", "null"]},
                    "pic": {"type": ["string", "null"]},
                    "deadline": {"type": ["string", "null"]},
                    "budget_required": {"type": ["number", "null"]},
                    "priority": {"type": ["string", "null"]},
                    "status": {"type": ["string", "null"], "enum": ["pending", "in_progress", "completed", "cancelled", None]},
                },
                "required": ["id", "title", "division", "pic", "deadline", "budget_required", "priority", "status"],
            },
        },
        "checks_required": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["description", "severity"],
            },
        },
        "next_action": {
            "type": "string",
            "enum": ["run_tools", "wait_for_human", "ready_to_create_ticket", "completed", "failed"],
        },
    },
    "required": ["program", "summary", "tasks", "checks_required", "risk_flags", "next_action"],
}

# AgentAction schema
AGENT_ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": ["check_budget", "check_schedule", "request_human_review", "propose_ticket_creation", "finish"],
        },
        "task_id": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["action", "task_id", "reason"],
}


class QwenProvider(LLMProvider):
    """Qwen LLM provider via Groq API with Structured Outputs."""

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ConfigurationError(
                "GROQ_API_KEY environment variable not set",
                provider="qwen",
                category="configuration",
            )

        self.model = os.getenv("MODEL_NAME", "qwen/qwen3.8-27b")
        self.api_key = api_key

    def generate_plan(self, meeting_notes: str) -> OperationalPlan:
        """Generate operational plan from meeting notes using Qwen via Groq."""
        try:
            from groq import Groq
        except ImportError:
            raise ImportError("groq package not installed. Run: pip install groq")

        system_prompt = """You are the OpsHub Operational Planning Agent.

RULES:
- Never invent missing information. If not explicitly stated, use null.
- Extract ONLY what is clearly present in the notes.
- Each distinct task becomes a separate Task object.
- Supported checks: budget, schedule
- next_action: use "run_tools" if checks needed, else "wait_for_human"

Output ONLY valid JSON matching the required schema."""

        client = Groq(api_key=self.api_key)

        try:
            completion = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Meeting notes:\n\n{meeting_notes}"},
                ],
                temperature=0,
                max_tokens=2000,
                reasoning_effort="none",
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "operational_plan",
                        "schema": OPERATIONAL_PLAN_SCHEMA,
                        "strict": True,
                    },
                },
            )
        except Exception as e:
            raise RecoverableLLMError(
                f"Groq API error: {e}",
                provider="qwen",
                category="api_error",
            )

        if not completion.choices:
            raise RecoverableLLMError(
                "Qwen returned an empty response.",
                provider="qwen",
                category="empty_response",
            )

        raw_content = completion.choices[0].message.content

        if raw_content is None or not str(raw_content).strip():
            raise RecoverableLLMError(
                "Qwen returned an empty response.",
                provider="qwen",
                category="empty_response",
            )

        raw_content = str(raw_content).strip()

        try:
            response_json = json.loads(raw_content)
        except json.JSONDecodeError:
            raise RecoverableLLMError(
                "Malformed JSON response from Qwen.",
                provider="qwen",
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
                provider="qwen",
                category="validation",
            )

    def choose_next_action(
        self,
        plan: OperationalPlan,
        observations: List[AgentObservation],
        runtime_context: RuntimeContext,
    ) -> AgentActionModel:
        """Choose the next allowed action using Qwen via Groq."""
        try:
            from groq import Groq
        except ImportError:
            raise ImportError("groq package not installed. Run: pip install groq")

        # Build compact prompt
        tasks_summary = "\n".join(
            f"- {t.id}: {t.title} (budget: {t.budget_required}, deadline: {t.deadline})"
            for t in plan.tasks
        )

        obs_summary = "\n".join(
            f"- {o.action} {o.task_id}: {o.status}. {o.message}"
            for o in observations
        )

        budget_status = "known" if runtime_context.available_budget is not None else "unknown"
        check_context = format_task_check_context(plan.tasks, observations)

        system_prompt = """You are OpsHub's orchestration planner.

RULES:
- Choose EXACTLY ONE next action from the allowed set
- Never invent new tools or execute tools directly
- Never bypass human approval
- Use request_human_review when conflicts exist
- If a read-only check remains missing, select that check before requesting human review or proposing a ticket.
- An already_checked observation means that check is clear; use the listed remaining checks.
- A clear check does not complete a task. Propose ticket creation for each task that lacks a ticket_created observation.
- A rejected finish observation explains what is still required. Follow it.
- Use finish with task_id=null only after every operational task has a ticket_created observation.

Allowed actions: check_budget, check_schedule, request_human_review, propose_ticket_creation, finish"""

        client = Groq(api_key=self.api_key)

        try:
            completion = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"""Current plan: {plan.program}
Tasks:
{tasks_summary}

Previous observations:
{obs_summary if obs_summary else "None"}

Available budget: {budget_status}

Per-task check state:
{check_context}

Choose the next action as JSON.""",
                    },
                ],
                temperature=0,
                max_tokens=150,
                reasoning_effort="none",
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "agent_action",
                        "schema": AGENT_ACTION_SCHEMA,
                        "strict": True,
                    },
                },
            )
        except Exception as e:
            raise RecoverableLLMError(
                f"Groq API error: {e}",
                provider="qwen",
                category="api_error",
            )

        if not completion.choices:
            raise RecoverableLLMError(
                "Qwen returned an empty action response.",
                provider="qwen",
                category="empty_response",
            )

        raw_content = completion.choices[0].message.content

        if raw_content is None or not str(raw_content).strip():
            raise RecoverableLLMError(
                "Qwen returned an empty action response.",
                provider="qwen",
                category="empty_response",
            )

        try:
            data = json.loads(str(raw_content).strip())
            return AgentActionModel.model_validate(data)
        except Exception as e:
            raise RecoverableLLMError(
                f"AgentAction validation failed: {e}",
                provider="qwen",
                category="validation",
            )
