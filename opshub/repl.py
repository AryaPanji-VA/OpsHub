"""A bounded terminal interface for the existing operational agent."""

import sys
import re

from dotenv import load_dotenv

from opshub.agent import OpsHubAgent
from opshub.checks import get_required_checks_for_task
from opshub.cli import format_llm_error, prepare_runtime_context, run_workflow
from opshub.llm import get_llm_provider
from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.models import NextAction


_INTENTS = {
    "summary": "summary", "recap": "summary", "ringkasan": "summary",
    "show summary": "summary", "lihat ringkasan": "summary",
    "tasks": "tasks", "show tasks": "tasks", "tugas": "tasks",
    "lihat tugas": "tasks", "daftar tugas": "tasks",
    "check all": "check all", "cek semua": "check all",
    "periksa semua": "check all",
    "budget": "budget", "check budget": "budget", "cek budget": "budget",
    "cek anggaran": "budget", "anggaran": "budget",
    "schedule": "schedule", "check schedule": "schedule",
    "cek jadwal": "schedule", "jadwal": "schedule",
    "tickets": "tickets", "show tickets": "tickets", "tiket": "tickets",
    "lihat tiket": "tickets",
    "create tickets": "create tickets", "create ticket": "create tickets",
    "buat ticket": "create tickets", "buat tiket": "create tickets",
    "status": "status", "show status": "status", "cek status": "status",
    "help": "help", "bantuan": "help",
    "exit": "exit", "quit": "exit", "keluar": "exit",
}

_HELP = (
    "Commands: summary, tasks, check all, budget, schedule, tickets, "
    "create tickets, status, help, exit"
)
_OUT_OF_SCOPE = (
    "This request is outside OpsHub's operational scope.\n\n"
    "I can help with:\n"
    "- program summaries\n"
    "- task breakdown\n"
    "- budget checks\n"
    "- schedule checks\n"
    "- ticket creation\n"
    "- operational status"
)


def parse_intent(text: str) -> str | None:
    """Map a small, explicit vocabulary without asking an LLM."""
    normalized = " ".join(text.casefold().strip().rstrip(".!?").split())
    return _INTENTS.get(normalized)


def is_operational_notes(text: str) -> bool:
    """Keep clear general-assistant requests out of the extraction pipeline."""
    normalized = text.casefold().strip()
    if parse_intent(normalized):
        return False
    if re.match(
        r"^(?:(?:can|could) you\s+|please\s+|tolong\s+)?"
        r"(write|build|design|code|make|create|tell|explain|translate|"
        r"generate|buatkan|bikin)\b",
        normalized,
    ):
        return False
    return bool(re.search(
        r"\b(program|meeting|notes|rapat|notulensi|event|acara|budget|anggaran|"
        r"schedule|jadwal|task|tugas|vendor|peserta|logistik|finance|keuangan|"
        r"deadline|tenggat|catering|ticket|tiket|operational|operasional|"
        r"project|proyek|conference|summit|seminar|workshop|kegiatan|"
        r"agenda|koordinasi|pelaksanaan|biaya|dana|lokasi)\b",
        normalized,
    ))


def _read_notes() -> str:
    print("Describe your program or paste meeting notes:")
    print("(Press Enter on an empty line to submit.)")
    lines = []
    while True:
        line = input("> ")
        if not line.strip():
            return "\n".join(lines).strip()
        lines.append(line)


def _show_checks(agent, check_types: set[str] | None = None) -> dict:
    if check_types is None or "budget" in check_types:
        prepare_runtime_context(agent, agent.current_plan, show_schedule=False)
    results = agent.run_checks(check_types=check_types)
    selected = check_types or {"budget", "schedule"}
    found = False
    for check in ("budget", "schedule"):
        if check not in selected:
            continue
        for result in results[check]:
            found = True
            print(f"[{result.status.upper()}] {check} {result.task_id}: {result.message}")
    if not found:
        print("No applicable checks for this plan.")
    return results


def _show_status(agent, check_results: dict):
    plan = agent.current_plan
    required = {(f"check_{check}", task.id)
                for task in plan.tasks
                for check in get_required_checks_for_task(task)}
    clear = {(observation.action, observation.task_id)
             for observation in agent.observations if observation.status == "clear"}
    clear.update((f"check_{check}", result.task_id)
                 for check, results in check_results.items()
                 for result in results if result.success)
    completed = len(required & clear)
    unresolved = agent._get_unresolved_task_ids()
    print(f"Checks completed: {completed}/{len(required)}")
    print(f"Unresolved tasks: {', '.join(unresolved) if unresolved else 'none'}")
    print(f"Tickets created this session: {len(agent.created_ticket_tasks)}")
    print(f"Next action: {plan.next_action.value}")


def _show_tickets(agent):
    tickets = [event["details"] for event in agent.audit_log.get_all()
               if event["event"] == "ticket_created"]
    if not tickets:
        print("No tickets created in this session.")
        return
    for ticket in tickets:
        print(f"{ticket['ticket_id']}: {ticket['task_id']}")


def main() -> int:
    load_dotenv()
    print("OpsHub Agent")
    print("Operational AI for SGA\n")
    try:
        notes = _read_notes()
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye!")
        return 0
    if not notes:
        print("No meeting notes provided.")
        return 0
    if not is_operational_notes(notes):
        print(_OUT_OF_SCOPE)
        return 0

    try:
        agent = OpsHubAgent(llm_provider=get_llm_provider())
        agent.ingest_notes(notes)
        plan = agent.generate_plan()
    except (ConfigurationError, RecoverableLLMError) as error:
        print(format_llm_error(error))
        return 1

    print(f"\nPlan ready: {plan.program}")
    print(_HELP)
    check_results = {"budget": [], "schedule": []}
    while True:
        try:
            command = input("opshub> ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return 0
        intent = parse_intent(command)
        if intent == "exit":
            print("Goodbye!")
            return 0
        if intent == "help":
            print(_HELP)
        elif intent == "summary":
            print(f"{plan.program}: {plan.summary}")
        elif intent == "tasks":
            if not plan.tasks:
                print("No tasks in the current plan.")
            for task in plan.tasks:
                print(f"{task.id}: {task.title} ({task.division or 'division unknown'})")
        elif intent in {"check all", "budget", "schedule"}:
            selected = None if intent == "check all" else {intent}
            new_results = _show_checks(agent, selected)
            for check in selected or {"budget", "schedule"}:
                check_results[check] = new_results[check]
        elif intent == "tickets":
            _show_tickets(agent)
        elif intent == "create tickets":
            if plan.next_action == NextAction.COMPLETED:
                print("Workflow already completed.")
            elif plan.next_action == NextAction.WAIT_FOR_HUMAN and agent.observations:
                print("Human review is required before continuing.")
            else:
                prepare_runtime_context(agent, plan)
                run_workflow(agent)
        elif intent == "status":
            _show_status(agent, check_results)
        else:
            print(_OUT_OF_SCOPE)


if __name__ == "__main__":
    sys.exit(main())
