"""Single-purpose Vercel function for OpsHub's two structured LLM decisions.

Deploy the gateway/ directory separately. No OpsHub client credential is accepted.
"""

import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MODEL = "qwen/qwen3.8-27b"
MAX_REQUEST_BYTES = 32_768
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# Kept in the standalone deployment so its output contract matches QwenProvider.
PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "program": {"type": "string"},
        "summary": {"type": "string"},
        "tasks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "id": {"type": "string"}, "title": {"type": "string"},
                "division": {"type": ["string", "null"]}, "pic": {"type": ["string", "null"]},
                "deadline": {"type": ["string", "null"]}, "budget_required": {"type": ["number", "null"]},
                "priority": {"type": ["string", "null"]},
                "status": {"type": ["string", "null"], "enum": ["pending", "in_progress", "completed", "cancelled", None]},
            },
            "required": ["id", "title", "division", "pic", "deadline", "budget_required", "priority", "status"],
        }},
        "checks_required": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"description": {"type": "string"}, "severity": {"type": "string", "enum": ["low", "medium", "high"]}},
            "required": ["description", "severity"],
        }},
        "next_action": {"type": "string", "enum": ["run_tools", "wait_for_human", "ready_to_create_ticket", "completed", "failed"]},
    },
    "required": ["program", "summary", "tasks", "checks_required", "risk_flags", "next_action"],
}
ACTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["check_budget", "check_schedule", "request_human_review", "propose_ticket_creation", "finish"]},
        "task_id": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["action", "task_id", "reason"],
}

PLAN_PROMPT = """You are the OpsHub Operational Planning Agent.
RULES:
- Never invent missing information. If not explicitly stated, use null.
- Extract ONLY what is clearly present in the notes.
- Each distinct task becomes a separate Task object.
- Supported checks: budget, schedule
- next_action: use "run_tools" if checks needed, else "wait_for_human"
Output ONLY valid JSON with program, summary, tasks, checks_required, risk_flags, next_action.
Each task has id, title, division, pic, deadline, budget_required, priority, status.
Each risk flag has description and severity."""

ACTION_PROMPT = """You are OpsHub's orchestration planner.
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
Allowed actions: check_budget, check_schedule, request_human_review, propose_ticket_creation, finish
Output ONLY JSON with action, task_id, reason."""


def _check_context(tasks: list[dict], observations: list[dict]) -> str:
    lines = []
    for task in tasks:
        states = {}
        if task.get("budget_required") is not None:
            states["budget"] = "missing"
        if task.get("deadline") is not None:
            states["schedule"] = "missing"
        for observation in observations:
            action = observation.get("action", "")
            if observation.get("task_id") == task.get("id") and isinstance(action, str) and action.startswith("check_"):
                check = action.removeprefix("check_")
                if check in states and observation.get("status") in {"clear", "failed", "missing_context"}:
                    states[check] = observation["status"]
        summary = ", ".join(f"{check}: {status}" for check, status in states.items()) or "none required"
        remaining = ", ".join(
            f"check_{check} {task['id']}" for check, status in states.items() if status == "missing"
        ) or "none"
        lines.append(f"- {task['id']}: {summary}; remaining read-only checks: {remaining}")
    return "\n".join(lines) or "No tasks"


def build_messages(payload: dict) -> tuple[list[dict], int]:
    """Accept only OpsHub's plan/action contract, never arbitrary model messages."""
    if not isinstance(payload, dict):
        raise ValueError("Request must be an object")
    if payload.get("operation") == "plan" and set(payload) == {"operation", "meeting_notes"}:
        notes = payload["meeting_notes"]
        if not isinstance(notes, str) or not notes.strip() or len(notes) > 20_000:
            raise ValueError("Invalid meeting notes")
        return [
            {"role": "system", "content": PLAN_PROMPT},
            {"role": "user", "content": f"Meeting notes:\n\n{notes}"},
        ], 1200
    if payload.get("operation") == "action" and set(payload) == {"operation", "plan", "observations", "runtime_context"}:
        plan, observations, context = payload["plan"], payload["observations"], payload["runtime_context"]
        if not isinstance(plan, dict) or not isinstance(plan.get("program"), str) or not isinstance(plan.get("tasks"), list):
            raise ValueError("Invalid plan")
        if not isinstance(observations, list) or len(observations) > 100 or not all(isinstance(item, dict) for item in observations):
            raise ValueError("Invalid observations")
        if not isinstance(context, dict) or set(context) - {"available_budget", "schedule_entries", "budget_source", "schedule_source"}:
            raise ValueError("Invalid runtime context")
        if len(plan["tasks"]) > 100 or not all(isinstance(task, dict) for task in plan["tasks"]):
            raise ValueError("Invalid tasks")
        if not all(isinstance(task.get("id"), str) and isinstance(task.get("title"), str) for task in plan["tasks"]):
            raise ValueError("Invalid task fields")
        tasks_summary = "\n".join(
            f"- {task['id']}: {task['title']} (budget: {task.get('budget_required')}, deadline: {task.get('deadline')})"
            for task in plan["tasks"]
        )
        obs_summary = "\n".join(
            f"- {item.get('action')} {item.get('task_id')}: {item.get('status')}. {item.get('message')}"
            for item in observations
        )
        budget_status = "known" if context.get("available_budget") is not None else "unknown"
        # The gateway does not execute tools; structured state is context only.
        return [
            {"role": "system", "content": ACTION_PROMPT},
            {"role": "user", "content": f"""Current plan: {plan['program']}
Tasks:
{tasks_summary}

Previous observations:
{obs_summary if obs_summary else 'None'}

Available budget: {budget_status}

Per-task check state:
{_check_context(plan['tasks'], observations)}

Choose the next action as JSON."""},
        ], 150
    raise ValueError("Unsupported operation")


def run_request(payload: dict, *, call_groq=None) -> dict:
    messages, max_tokens = build_messages(payload)
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("Gateway provider not configured")
    body = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "reasoning_effort": "none",
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "operational_plan" if payload["operation"] == "plan" else "agent_action",
            "schema": PLAN_SCHEMA if payload["operation"] == "plan" else ACTION_SCHEMA,
            "strict": True,
        }},
    }
    if call_groq is None:
        call_groq = _call_groq
    upstream = call_groq(body, key)
    content = upstream["choices"][0]["message"]["content"]
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("Invalid provider response")
    return {"result": result}


def _call_groq(body: dict, key: str) -> dict:
    request = Request(
        GROQ_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=12) as response:
        return json.load(response)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/llm":
            return self._reply(404, {"error": "Not found"})
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self._reply(415, {"error": "JSON required"})
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or int(length) > MAX_REQUEST_BYTES:
            return self._reply(413, {"error": "Request too large"})
        try:
            payload = json.loads(self.rfile.read(int(length)))
            build_messages(payload)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return self._reply(400, {"error": "Invalid request"})
        try:
            result = run_request(payload)
        except (HTTPError, URLError, TimeoutError, RuntimeError, KeyError, IndexError, TypeError, ValueError):
            # Never log upstream responses, request bodies, or credentials.
            return self._reply(502, {"error": "Provider unavailable"})
        return self._reply(200, result)

    def _reply(self, status: int, body: dict):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        # Do not log paths, headers, prompts, response bodies, or secrets.
        pass
