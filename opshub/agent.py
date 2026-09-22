from pathlib import Path
from typing import Optional, List, Dict, Tuple
import json
import os

from opshub.models import (
    OperationalPlan,
    Task,
    TaskStatus,
    RiskFlag,
    NextAction,
    ToolResult,
    Approval,
    ApprovalStatus,
    RuntimeContext,
    ContextSource,
    AgentActionModel,
    AgentAction,
    AgentObservation,
)
from opshub.llm.base import LLMProvider
from opshub.llm.mock import MockLLMProvider
from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.checks import get_required_checks_for_task, get_check_states_for_task

TICKETS_FILE = Path(__file__).parent.parent / "data" / "tickets.json"
MAX_AGENT_STEPS = 6

DEBUG_LOOP = os.getenv("DEBUG_AGENT_LOOP") == "1"


class AuditLog:
    def __init__(self):
        self.events: List[dict] = []

    def add(self, event: str, details: dict = None):
        self.events.append({"event": event, "details": details or {}})

    def get_all(self) -> List[dict]:
        return self.events


class ToolDispatcher:
    """
    Dispatches validated actions to trusted Python functions.

    Tool execution uses trusted data from OperationalPlan and RuntimeContext.
    The LLM only decides WHAT action to take, not the tool arguments.
    """

    def __init__(self, current_plan: OperationalPlan, runtime_context: RuntimeContext):
        self.current_plan = current_plan
        self.runtime_context = runtime_context

    def _get_task(self, task_id: str) -> Optional[Task]:
        """Find task by ID in current plan. Returns None if not found."""
        for task in self.current_plan.tasks:
            if task.id == task_id:
                return task
        return None

    def dispatch(self, action: AgentAction, task_id: str) -> Tuple[bool, str, dict]:
        """Execute tool with trusted data from OperationalPlan. Returns (success, message, details)."""
        task = self._get_task(task_id)

        if task is None:
            return False, f"Task {task_id} not found in current plan", {}

        if action == AgentAction.CHECK_BUDGET:
            return self._check_budget(task)
        elif action == AgentAction.CHECK_SCHEDULE:
            return self._check_schedule(task)
        else:
            return False, f"Action {action.value} not dispatchable", {}

    def _check_budget(self, task: Task) -> Tuple[bool, str, dict]:
        """Execute budget check using trusted data from Task."""
        from opshub.tools.budget import check_budget

        if task.budget_required is None:
            return True, "Task has no budget requirement.", {"status": "missing_context"}

        if self.runtime_context.available_budget is None:
            from opshub.tools.budget import DATA_FILE
            if not DATA_FILE.exists():
                return False, "Available budget is unknown; human context required.", {
                    "status": "missing_context", "source": ContextSource.NONE.value,
                }

        ok, msg, source = check_budget(
            task.budget_required,
            available=self.runtime_context.available_budget,
        )

        return (
            ok,
            msg,
            {
                "required": task.budget_required,
                "available": self.runtime_context.available_budget,
                "source": (self.runtime_context.budget_source or source).value,
            },
        )

    def _check_schedule(self, task: Task) -> Tuple[bool, str, dict]:
        """Execute schedule check using trusted data from Task."""
        from opshub.tools.schedule import check_schedule

        if task.deadline is None:
            return True, "Task deadline is unknown.", {"status": "missing_context"}

        ok, msg, count, source = check_schedule(
            task.title, task.deadline,
            entries=self.runtime_context.schedule_entries,
        )

        return (
            ok,
            msg,
            {"deadline": task.deadline, "entry_count": count,
             "source": (self.runtime_context.schedule_source or source).value},
        )


class OpsHubAgent:
    def __init__(
        self,
        llm_provider: LLMProvider = None,
        tickets_file: Optional[Path] = None,
    ):
        self.llm_provider = llm_provider or MockLLMProvider()
        self.audit_log = AuditLog()
        self.current_plan: Optional[OperationalPlan] = None
        self.current_notes: str = ""
        self.approvals: List[Approval] = []
        self.tickets_file = tickets_file or TICKETS_FILE
        self.runtime_context = RuntimeContext()
        self.observations: List[AgentObservation] = []
        self.executed_actions: Dict[Tuple[str, str], int] = {}
        self.created_ticket_tasks: set[str] = set()
        self.tool_dispatcher: Optional[ToolDispatcher] = None
        # Bounded autonomy: True only when the last run ended by step limit.
        self.workflow_paused: bool = False
        self.paused_reason: Optional[str] = None

    def set_budget(self, available: float, source: ContextSource = ContextSource.HUMAN):
        """Set budget context for this session."""
        self.runtime_context.available_budget = available
        self.runtime_context.budget_source = source
        self.audit_log.add(
            "context_provided",
            {"type": "budget", "available": available, "source": source.value},
        )

    def set_schedule_entries(
        self, entries: list, source: ContextSource = ContextSource.HUMAN
    ):
        """Set schedule entries for this session."""
        self.runtime_context.schedule_entries = entries
        self.runtime_context.schedule_source = source
        self.audit_log.add(
            "context_provided",
            {"type": "schedule", "count": len(entries), "source": source.value},
        )

    def ingest_notes(self, notes: str):
        self.current_notes = notes
        self.audit_log.add("notes_received", {"length": len(notes)})

    def generate_plan(self) -> OperationalPlan:
        self.current_plan = self.llm_provider.generate_plan(self.current_notes)
        self.approvals = []
        self.observations = []
        self.executed_actions = {}
        self.created_ticket_tasks = set()
        self.workflow_paused = False
        self.paused_reason = None
        self.audit_log.add("plan_generated", {"program": self.current_plan.program})
        self.tool_dispatcher = ToolDispatcher(self.current_plan, self.runtime_context)
        return self.current_plan

    def run_checks(self, check_types: Optional[set[str]] = None) -> dict[str, List[ToolResult]]:
        """Execute selected read-only checks required by each task's trusted fields."""
        from opshub.tools.budget import check_budget
        from opshub.tools.schedule import check_schedule

        results: dict[str, List[ToolResult]] = {"budget": [], "schedule": []}

        if not self.current_plan:
            return results

        for task in self.current_plan.tasks:
            if "budget" in self.get_required_checks_for_task(task) and (
                check_types is None or "budget" in check_types
            ):
                ok, msg, source = check_budget(
                    task.budget_required,
                    available=self.runtime_context.available_budget,
                )
                tool_result = ToolResult(
                    tool="budget",
                    task_id=task.id,
                    success=ok,
                    status="clear" if ok else "insufficient",
                    message=msg,
                    details={
                        "required": task.budget_required,
                        "available": self.runtime_context.available_budget,
                    },
                    source=self.runtime_context.budget_source or source,
                )
                results["budget"].append(tool_result)
                self.audit_log.add(
                    "tool_result",
                    {
                        "tool": "budget",
                        "task_id": task.id,
                        "success": ok,
                        "message": msg,
                        "source": source.value,
                    },
                )

            if "schedule" in self.get_required_checks_for_task(task) and (
                check_types is None or "schedule" in check_types
            ):
                ok, msg, count, source = check_schedule(
                    task.title, task.deadline,
                    entries=self.runtime_context.schedule_entries,
                )
                tool_result = ToolResult(
                    tool="schedule",
                    task_id=task.id,
                    success=ok,
                    status="clear" if ok else "conflict",
                    message=msg,
                    details={"deadline": task.deadline, "entry_count": count},
                    source=self.runtime_context.schedule_source or source,
                )
                results["schedule"].append(tool_result)
                self.audit_log.add(
                    "tool_result",
                    {
                        "tool": "schedule",
                        "task_id": task.id,
                        "success": ok,
                        "message": msg,
                        "source": source.value,
                    },
                )

        return results

    def evaluate_policy(self, check_results: dict[str, List[ToolResult]]) -> tuple[bool, List[str]]:
        """Evaluate check results and return (requires_approval, reasons)."""
        reasons: List[str] = []
        requires_approval = False

        for result in check_results.get("budget", []):
            if not result.success:
                requires_approval = True
                reasons.append(f"Budget insufficient for {result.task_id}: {result.message}")

        for result in check_results.get("schedule", []):
            if not result.success:
                requires_approval = True
                reasons.append(f"Schedule conflict for {result.task_id}: {result.message}")

        return requires_approval, reasons

    def update_plan_with_results(
        self,
        check_results: dict[str, List[ToolResult]],
        requires_approval: bool,
        reasons: List[str],
    ) -> OperationalPlan:
        """Update current_plan with risk flags and next_action based on results."""
        if not self.current_plan:
            return None

        for result in check_results.get("budget", []):
            if not result.success:
                self.current_plan.risk_flags.append(
                    RiskFlag(
                        description=f"Budget exceeded for task {result.task_id}",
                        severity="high",
                    )
                )
                self.audit_log.add(
                    "conflict_detected",
                    {"type": "budget", "task_id": result.task_id},
                )

        for result in check_results.get("schedule", []):
            if not result.success:
                self.current_plan.risk_flags.append(
                    RiskFlag(
                        description=f"Schedule conflict for task {result.task_id}",
                        severity="high",
                    )
                )
                self.audit_log.add(
                    "conflict_detected",
                    {"type": "schedule", "task_id": result.task_id},
                )

        if requires_approval:
            self.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
            self.audit_log.add("approval_requested", {"reasons": reasons})
        elif (
            len(check_results.get("budget", []))
            + len(check_results.get("schedule", []))
        ) > 0:
            self.current_plan.next_action = NextAction.READY_TO_CREATE_TICKET
        else:
            self.current_plan.next_action = NextAction.WAIT_FOR_HUMAN

        return self.current_plan

    def _validate_task_id(self, task_id: str) -> bool:
        """Validate that task_id exists in current_plan. Returns True if valid."""
        if not self.current_plan:
            return False
        return any(task.id == task_id for task in self.current_plan.tasks)

    def _can_finish(self) -> bool:
        """
        Check if workflow may legitimately finish.
        Returns True only when:
        - All required checks have been performed
        - No pending risks remain unresolved
        - All actionable tasks have been handled
        """
        if not self.current_plan:
            return False

        if self._get_unresolved_task_ids():
            return False

        # Check if there are unresolved risks
        if self.current_plan.risk_flags:
            return False

        return all(not self.get_missing_checks_for_task(task.id)
                   for task in self.current_plan.tasks)

    def get_required_checks_for_task(self, task: Task) -> list[str]:
        return get_required_checks_for_task(task)

    def get_missing_checks_for_task(self, task_id: str) -> list[str]:
        if not self.current_plan:
            return []
        task = next((task for task in self.current_plan.tasks if task.id == task_id), None)
        if task is None:
            return []
        return [check for check, status in
                get_check_states_for_task(task, self.observations).items()
                if status != "clear"]

    def _remaining_check_message(self) -> str:
        remaining = [f"check_{check} {task.id}"
                     for task in self.current_plan.tasks
                     for check, status in get_check_states_for_task(
                         task, self.observations).items() if status == "missing"]
        return ", ".join(remaining) or "none"

    def _has_blocking_check_result(self) -> bool:
        for observation in self.observations:
            if observation.status not in {"failed", "missing_context"}:
                continue
            task = self.tool_dispatcher._get_task(observation.task_id or "")
            if (task is not None and observation.action.removeprefix("check_")
                    in self.get_required_checks_for_task(task)):
                return True
        return False

    def _get_unresolved_task_ids(self) -> List[str]:
        """
        Get actionable tasks for which ticket creation has not succeeded.
        """
        if not self.current_plan:
            return []

        return [task.id for task in self.current_plan.tasks
                if task.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
                and task.id not in self.created_ticket_tasks]

    def _finish_is_stalled(self) -> bool:
        """Stop a deterministic provider from spending the remaining steps on finish."""
        if len(self.observations) < 2 or not all(
            o.action == "finish" and o.status == "invalid_action"
            for o in self.observations[-2:]
        ):
            return False
        self.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
        self.audit_log.add("agent_stalled", {"reason": "repeated_invalid_finish"})
        return True

    def run_agent_loop(self) -> Tuple[bool, List[AgentObservation]]:
        """
        ReAct-lite agent loop.
        Returns (success, observations).
        """
        if not self.current_plan:
            return False, []

        self.audit_log.add("agent_loop_started", {"max_steps": MAX_AGENT_STEPS})
        # Each run starts unpaused; only a step-limit exit sets the pause flag,
        # so it always reflects the outcome of the most recent run.
        self.workflow_paused = False
        self.paused_reason = None

        last_action: Optional[AgentActionModel] = None

        for step in range(1, MAX_AGENT_STEPS + 1):
            try:
                action = self.llm_provider.choose_next_action(
                    self.current_plan,
                    self.observations,
                    self.runtime_context,
                )
            except (ConfigurationError, RecoverableLLMError) as e:
                if DEBUG_LOOP:
                    print(f"\nDEBUG: Agent loop failed at step {step}")
                    print(f"  Provider: {type(self.llm_provider).__name__}")
                    print(f"  Exception: {type(e).__name__}")
                    print(f"  Message: {e}")
                    if last_action:
                        print(f"  Last action: {last_action.action.value}")
                    print()
                self.audit_log.add(
                    "agent_action_failed",
                    {"step": step, "reason": str(e)},
                )
                self.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
                return False, self.observations

            # Validate task_id for task-specific actions
            if action.action in [AgentAction.CHECK_BUDGET, AgentAction.CHECK_SCHEDULE, AgentAction.PROPOSE_TICKET_CREATION]:
                if not action.task_id or not self._validate_task_id(action.task_id):
                    obs = AgentObservation(
                        action=action.action.value,
                        task_id=action.task_id,
                        status="invalid_action",
                        message=f"Invalid task_id '{action.task_id}' for task-specific action.",
                        details={},
                    )
                    self.observations.append(obs)
                    self.audit_log.add(
                        "task_id_validation_failed",
                        {"step": step, "action": action.action.value, "task_id": action.task_id},
                    )
                    continue

            task_id = action.task_id or ""
            action_key = (action.action.value, task_id)

            last_action = action

            if action.action in [AgentAction.CHECK_BUDGET, AgentAction.CHECK_SCHEDULE]:
                if action_key in self.executed_actions:
                    obs = AgentObservation(
                        action=action.action.value,
                        task_id=task_id,
                        status="already_checked",
                        message=("This action was already executed for this task. "
                                 f"Remaining read-only checks: {self._remaining_check_message()}."),
                        details={"step": step},
                    )
                    self.observations.append(obs)
                    self.audit_log.add(
                        "duplicate_action_blocked",
                        {"step": step, "action": action.action.value, "task_id": task_id},
                    )
                    continue

            self.audit_log.add(
                "agent_action_selected",
                {
                    "step": step,
                    "action": action.action.value,
                    "task_id": task_id,
                    "reason": action.reason,
                },
            )

            if action.action == AgentAction.REQUEST_HUMAN_REVIEW:
                has_blocker = bool(self.current_plan.risk_flags) or self._has_blocking_check_result()
                if not has_blocker and self._remaining_check_message() != "none":
                    self.observations.append(AgentObservation(
                        action=action.action.value, task_id=action.task_id,
                        status="invalid_action",
                        message=("Complete remaining read-only checks before human review: "
                                 f"{self._remaining_check_message()}."), details={}))
                    continue
                self.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
                self.observations.append(
                    AgentObservation(
                        action="request_human_review",
                        task_id=task_id,
                        status="interrupt",
                        message="Human review requested.",
                        details={"reason": action.reason},
                    )
                )
                self.audit_log.add(
                    "policy_interrupted_loop",
                    {"step": step, "reason": "human_review"},
                )
                return True, self.observations

            if action.action == AgentAction.PROPOSE_TICKET_CREATION:
                if task_id not in self._get_unresolved_task_ids():
                    self.observations.append(AgentObservation(
                        action=action.action.value, task_id=task_id,
                        status="invalid_action", message="Task already resolved.", details={}))
                    continue
                missing = self.get_missing_checks_for_task(task_id)
                if missing:
                    self.observations.append(AgentObservation(
                        action=action.action.value, task_id=task_id,
                        status="invalid_action",
                        message=(f"{task_id} is not ready for ticket creation. "
                                 f"Missing checks: {', '.join(missing)}."),
                        details={"missing_checks": missing}))
                    continue
                self.observations.append(
                    AgentObservation(
                        action="propose_ticket_creation",
                        task_id=task_id,
                        status="ready",
                        message="Ready to create ticket.",
                        details={},
                    )
                )
                self.audit_log.add(
                    "agent_loop_finished",
                    {"step": step, "reason": "ticket_proposed"},
                )
                self.current_plan.next_action = NextAction.READY_TO_CREATE_TICKET
                return True, self.observations

            if action.action == AgentAction.FINISH:
                # Validate finish action
                # Finish must not have task_id (only valid at workflow level)
                if action.task_id is not None:
                    obs = AgentObservation(
                        action="finish",
                        task_id=task_id,
                        status="invalid_action",
                        message="finish action must have task_id=null when valid workflow is complete.",
                        details={"reason": action.reason},
                    )
                    self.observations.append(obs)
                    self.audit_log.add(
                        "finish_rejected",
                        {"step": step, "reason": "task_id_should_be_null"},
                    )
                    if self._finish_is_stalled():
                        return True, self.observations
                    continue

                if not self._can_finish():
                    unresolved_tasks = self._get_unresolved_task_ids()
                    if unresolved_tasks:
                        remaining_checks = self._remaining_check_message()
                        next_step = (f"Complete remaining read-only checks: {remaining_checks}."
                                     if remaining_checks != "none" else
                                     "Select propose_ticket_creation for an unresolved task.")
                        msg = (
                            f"Workflow cannot finish. {len(unresolved_tasks)} operational task(s) remain unresolved: "
                            f"{', '.join(unresolved_tasks)}. {next_step}"
                        )
                    else:
                        msg = "Workflow cannot finish. Pending checks or unresolved risks exist."
                    obs = AgentObservation(
                        action="finish",
                        task_id=task_id,
                        status="invalid_action",
                        message=msg,
                        details={"reason": action.reason},
                    )
                    self.observations.append(obs)
                    self.audit_log.add(
                        "finish_rejected",
                        {"step": step, "reason": "pending_tasks"},
                    )
                    if self._finish_is_stalled():
                        return True, self.observations
                    continue

                self.observations.append(
                    AgentObservation(
                        action="finish",
                        task_id=task_id,
                        status="complete",
                        message="Workflow finished.",
                        details={"reason": action.reason},
                    )
                )
                self.audit_log.add(
                    "agent_loop_finished",
                    {"step": step, "reason": "finish"},
                )
                self.current_plan.next_action = NextAction.COMPLETED
                return True, self.observations

            if action.action in [AgentAction.CHECK_BUDGET, AgentAction.CHECK_SCHEDULE]:
                success, message, details = self.tool_dispatcher.dispatch(
                    action.action, task_id
                )

                if success and details.get("status") != "missing_context":
                    self.executed_actions[(action.action.value, task_id)] = step

                status = ("missing_context" if details.get("status") == "missing_context"
                          else "clear" if success else "failed")

                obs = AgentObservation(
                    action=action.action.value,
                    task_id=task_id,
                    status=status,
                    message=message,
                    details=details,
                )
                self.observations.append(obs)
                self.audit_log.add(
                    "tool_observation",
                    {
                        "step": step,
                        "action": action.action.value,
                        "task_id": task_id,
                        "status": obs.status,
                        "message": message,
                        "details": details,
                    },
                )
                continue

        self.audit_log.add(
            "agent_step_limit_reached",
            {"step": MAX_AGENT_STEPS, "next_action": NextAction.WAIT_FOR_HUMAN.value},
        )
        if self.current_plan:
            self.current_plan.next_action = NextAction.WAIT_FOR_HUMAN
        self.workflow_paused = True
        self.paused_reason = "step_limit"
        self.audit_log.add(
            "workflow_paused",
            {
                "reason": "step_limit",
                "preserved_observations": len(self.observations),
                "executed_checks": len(self.executed_actions),
            },
        )
        return True, self.observations

    def resume_workflow(self) -> Tuple[bool, List[AgentObservation]]:
        """
        Continue a workflow paused by the step limit.

        Reuses the current plan, observations, executed checks, approvals, and
        tickets. Grants up to another MAX_AGENT_STEPS autonomous actions; it
        does not approve tickets or override any HITL rule.
        Returns (False, []) when there is no paused workflow.
        """
        if not self.current_plan or not self.workflow_paused:
            return False, []
        self.audit_log.add(
            "workflow_resumed",
            {
                "preserved_observations": len(self.observations),
                "executed_checks": len(self.executed_actions),
                "tickets_created": len(self.created_ticket_tasks),
            },
        )
        return self.run_agent_loop()

    def count_missing_checks(self) -> int:
        """Count remaining required read-only checks across the current plan."""
        if not self.current_plan:
            return 0
        return sum(
            1 for task in self.current_plan.tasks
            for check, status in get_check_states_for_task(task, self.observations).items()
            if status == "missing"
        )

    def request_approval(self, task_id: str, action: str, reason: Optional[str] = None) -> Approval:
        approval = Approval(
            action=action,
            task_id=task_id,
            reason=reason,
            status=ApprovalStatus.PENDING,
        )
        self.approvals.append(approval)
        self.audit_log.add(
            "approval_requested",
            {"task_id": task_id, "action": action},
        )
        return approval

    def grant_approval(self, task_id: str, exception: bool = False) -> bool:
        for approval in self.approvals:
            if approval.task_id == task_id and approval.status == ApprovalStatus.PENDING:
                approval.status = ApprovalStatus.APPROVED
                event = "exception_approved" if exception else "approval_granted"
                self.audit_log.add(event, {"task_id": task_id})
                return True
        return False

    def reject_approval(self, task_id: str) -> bool:
        for approval in self.approvals:
            if approval.task_id == task_id and approval.status == ApprovalStatus.PENDING:
                approval.status = ApprovalStatus.REJECTED
                self.audit_log.add("approval_rejected", {"task_id": task_id})
                return True
        return False

    def has_pending_approval(self, task_id: str) -> bool:
        return any(
            a.task_id == task_id and a.status == ApprovalStatus.PENDING
            for a in self.approvals
        )

    def has_approved_approval(self, task_id: str) -> bool:
        return any(
            a.task_id == task_id and a.action == "create_ticket"
            and a.status == ApprovalStatus.APPROVED
            for a in self.approvals
        )

    def create_ticket(self, task: Task) -> Optional[str]:
        if not self.current_plan:
            return None
        if not self._validate_task_id(task.id) or task.id in self.created_ticket_tasks:
            return None
        task = self.tool_dispatcher._get_task(task.id)

        if not self.has_approved_approval(task.id):
            self.audit_log.add(
                "ticket_denied",
                {"task_id": task.id, "reason": "No approval"},
            )
            return None

        if self.tickets_file.exists():
            with open(self.tickets_file) as f:
                tickets = json.load(f)
        else:
            tickets = []

        ticket_id = f"OPS-{len(tickets)+1:03d}"

        ticket = {
            "id": ticket_id,
            "task_id": task.id,
            "title": task.title,
            "division": task.division,
            "pic": task.pic,
            "status": "pending",
            "source_program": self.current_plan.program,
        }

        tickets.append(ticket)

        self.tickets_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.tickets_file, "w") as f:
            json.dump(tickets, f, indent=2)

        self.audit_log.add(
            "ticket_created",
            {"ticket_id": ticket_id, "task_id": task.id},
        )
        self.created_ticket_tasks.add(task.id)
        self.observations.append(AgentObservation(
            action="ticket_created", task_id=task.id, status="complete",
            message=f"Ticket {ticket_id} created.", details={"ticket_id": ticket_id},
        ))

        self.current_plan.next_action = NextAction.RUN_TOOLS

        return ticket_id
