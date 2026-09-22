import sys
import re
from dotenv import load_dotenv

load_dotenv()

from opshub.agent import OpsHubAgent
from opshub.llm import get_llm_provider
from opshub.llm.exceptions import RecoverableLLMError, ConfigurationError
from opshub.models import NextAction, ContextSource, RuntimeContext


def parse_budget_input(value: str) -> float:
    """Parse budget input from various formats."""
    value = value.strip()
    if re.match(r"^\d{1,3}(\.\d{3})+$", value):
        value = value.replace(".", "")
    if re.match(r"^\d{1,3}(,\d{3})+$", value):
        value = value.replace(",", "")
    value = value.replace("_", "")
    try:
        amount = float(value)
        if amount < 0:
            raise ValueError("Negative value not allowed")
        return amount
    except ValueError:
        raise ValueError(f"Invalid budget value: {value}")


def format_llm_error(e: Exception) -> str:
    """Format LLM exceptions for user display."""
    if isinstance(e, ConfigurationError):
        return (
            f"LLM Provider configuration error: {e}\n\n"
            f"Provider: {e.provider}\n"
            "Please check your environment variables:\n"
            "  - GROQ_API_KEY (for Qwen/Groq)\n"
            "  - OPENROUTER_API_KEY (for Nex/OpenRouter)"
        )
    elif isinstance(e, RecoverableLLMError):
        provider = e.provider.lower()
        category = e.category.lower()

        if "rate_limit" in category:
            if "nex" in provider or "openrouter" in provider:
                return (
                    "AI provider temporarily unavailable.\n\n"
                    "Nex/OpenRouter is currently rate-limited.\n"
                    "Please retry shortly or use another configured provider."
                )
            elif "qwen" in provider or "groq" in provider:
                return (
                    "AI provider temporarily unavailable.\n\n"
                    "Qwen/Groq is currently rate-limited.\n"
                    "Please retry shortly or use another configured provider."
                )
        elif "timeout" in category:
            return (
                "AI provider temporarily unavailable.\n\n"
                f"{provider.capitalize()} request timed out.\n"
                "Please retry later."
            )
        elif "network" in category or "connection" in category:
            return (
                "AI provider temporarily unavailable.\n\n"
                f"Cannot connect to {provider.capitalize()}.\n"
                "Please check your internet connection and retry."
            )
        elif "server_error" in category:
            return (
                "AI provider temporarily unavailable.\n\n"
                f"{provider.capitalize()} server error.\n"
                "Please retry later."
            )
        elif "all_failed" in category:
            return (
                "All configured AI providers are temporarily unavailable.\n\n"
                "Primary: Qwen/Groq\n"
                "Fallback: Nex/OpenRouter\n\n"
                "Please retry later."
            )

        return f"AI provider error: {e}"
    else:
        return f"AI provider error: {e}"


def prepare_runtime_context(agent, plan, show_schedule=True):
    # Budget input collection
    if agent.runtime_context.available_budget is None:
        has_budget_tasks = any(t.budget_required is not None for t in plan.tasks)
        if has_budget_tasks:
            print("\nBudget requirement detected:")
            first_task = next(t for t in plan.tasks if t.budget_required is not None)
            print(f"Task: {first_task.id}")
            print(f"Required: Rp{first_task.budget_required:,.0f}")
            print("\nAvailable budget source:")
            print("  [1] Use runtime data")
            print("  [2] Enter manually")

            while True:
                try:
                    choice = input("\n> ").strip()
                    if choice == "1":
                        from opshub.tools.budget import DATA_FILE, load_budgets

                        if not DATA_FILE.exists():
                            print("No runtime budget data found. Enter a budget manually.")
                            continue

                        budget_data = load_budgets()
                        available = budget_data.get("available", 0) - budget_data.get("allocated", 0)
                        agent.set_budget(available, ContextSource.RUNTIME_FILE)
                        print(f"\nUsing runtime budget:")
                        print(f"Rp{available:,.0f}")
                        break
                    elif choice == "2":
                        while True:
                            budget_input = input("\nEnter available budget: ").strip()
                            try:
                                amount = parse_budget_input(budget_input)
                                agent.set_budget(amount, ContextSource.HUMAN)
                                print(f"\nBudget set: Rp{amount:,.0f}")
                                break
                            except ValueError as e:
                                print(f"Invalid budget value: {e}")
                                print("Please enter a numeric amount (e.g., 15000000)")
                        break
                    else:
                        print("Invalid choice. Please enter 1 or 2.")
                except KeyboardInterrupt:
                    print("\nCancelled.")
                    continue

    # Schedule input display
    if show_schedule and "schedule" in plan.checks_required:
        schedule_count = len(agent.runtime_context.schedule_entries or [])
        if schedule_count == 0:
            print("\nNo known schedule entries are currently loaded.")
            print("Schedule check will run against an empty schedule.")


def run_workflow(agent):
    plan = agent.current_plan
    print("\nAgent loop started.")
    while True:
        seen = len(agent.observations)
        success, observations = agent.run_agent_loop()
        new_observations = observations[seen:]

        for obs in new_observations:
            print(f"\n[{obs.status.upper()}]")
            print(f"  Action: {obs.action}")
            print(f"  Task: {obs.task_id}")
            if "required" in obs.details:
                print(f"  Required: Rp{obs.details['required']:,.0f}")
            if "available" in obs.details and obs.details["available"] is not None:
                print(f"  Available: Rp{obs.details['available']:,.0f}")
            print(f"  Message: {obs.message}")

        if not success:
            print("\nAgent loop failed.")
            break

        next_action = plan.next_action
        print(f"\nNext Action: {next_action.value}")
        if next_action == NextAction.COMPLETED:
            print("\nWorkflow completed.")
            break
        if next_action != NextAction.READY_TO_CREATE_TICKET:
            if any(o.status in {"failed", "missing_context"} for o in new_observations):
                print("\nBlocking reasons:")
                for obs in new_observations:
                    if obs.status in {"failed", "missing_context"}:
                        print(f"  - {obs.action} for {obs.task_id}: {obs.message}")
            elif any(e["event"] in {"agent_step_limit_reached", "agent_stalled"}
                     for e in agent.audit_log.events[-2:]):
                if agent.workflow_paused:
                    print(
                        "\nAUTONOMOUS RUN PAUSED\n"
                        "\n"
                        "The six-step safety limit was reached.\n"
                        "Completed work has been preserved.\n"
                        "\n"
                        "Type 'continue' to resume from the current state.\n"
                        "Type 'status' to inspect remaining work."
                    )
                else:
                    print("Agent could not complete the workflow. Human review required.")
            break

        proposal = next(o for o in reversed(new_observations)
                        if o.action == "propose_ticket_creation" and o.status == "ready")
        task = next(t for t in plan.tasks if t.id == proposal.task_id)
        agent.request_approval(task.id, "create_ticket")
        print(f"\nCreate ticket for {task.id}?")
        try:
            confirm = input("[y/N] > ").strip().lower()
        except KeyboardInterrupt:
            confirm = "n"
        if confirm != "y":
            agent.reject_approval(task.id)
            print(f"\nTicket for {task.id} rejected.")
            plan.next_action = NextAction.WAIT_FOR_HUMAN
            break
        agent.grant_approval(task.id)
        ticket_id = agent.create_ticket(task)
        if not ticket_id:
            print("\nTicket creation failed.")
            plan.next_action = NextAction.WAIT_FOR_HUMAN
            break
        print(f"\nTicket {ticket_id} created.")


def main():
    try:
        agent = OpsHubAgent(llm_provider=get_llm_provider())
    except (ConfigurationError, RecoverableLLMError) as e:
        print(format_llm_error(e))
        sys.exit(1)

    print("OpsHub Agent v0.1")
    print("Paste meeting notes.")
    print("Type /run on a new line when finished.\n")

    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            print("\nGoodbye!")
            break

        if line == "/exit":
            print("Goodbye!")
            break

        if line == "/help":
            print("Commands: /help /new /run /plan /log /exit")
            continue

        if line == "/new":
            agent.current_notes = ""
            agent.current_plan = None
            agent.approvals = []
            agent.observations = []
            agent.executed_actions = {}
            agent.created_ticket_tasks = set()
            agent.runtime_context = RuntimeContext()
            print("Cleared. Start pasting notes.")
            continue

        if line == "/run":
            if not agent.current_notes.strip():
                print("No notes provided. Paste notes first.")
                continue

            try:
                agent.ingest_notes(agent.current_notes)
                plan = agent.generate_plan()
            except (ConfigurationError, RecoverableLLMError) as e:
                print(format_llm_error(e))
                continue

            print(f"\nProgram: {plan.program}")
            print(f"Summary: {plan.summary}")
            print(f"\nTasks ({len(plan.tasks)}):")
            for task in plan.tasks:
                print(f"  - {task.id}: {task.title} ({task.division})")

            print(f"\nChecks Required: {', '.join(plan.checks_required)}")

            prepare_runtime_context(agent, plan)
            run_workflow(agent)

            continue

        if line == "/plan":
            if agent.current_plan:
                print(f"Current: {agent.current_plan.program}")
            else:
                print("No plan generated yet.")
            continue

        if line == "/log":
            print("Audit Log:")
            for event in agent.audit_log.get_all():
                print(f"  - {event['event']}: {event['details']}")
            continue

        agent.current_notes += line + "\n"


if __name__ == "__main__":
    main()
