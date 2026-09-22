from dataclasses import dataclass
from typing import List

@dataclass
class PolicyResult:
    requires_approval: bool
    reasons: List[str]
    approved: bool = False

def check_budget_policy(amount: float) -> PolicyResult:
    from .tools.budget import check_budget
    sufficient, msg, _source = check_budget(amount)
    if not sufficient:
        return PolicyResult(
            requires_approval=True,
            reasons=[msg]
        )
    return PolicyResult(requires_approval=False, reasons=[])

def check_schedule_policy(event_name: str, date: str) -> PolicyResult:
    from .tools.schedule import check_schedule
    clear, msg, _count, _source = check_schedule(event_name, date)
    if not clear:
        return PolicyResult(
            requires_approval=True,
            reasons=[msg]
        )
    return PolicyResult(requires_approval=False, reasons=[])

def check_ticket_policy() -> PolicyResult:
    return PolicyResult(
        requires_approval=True,
        reasons=["Ticket creation requires human approval"]
    )

def check_all_policies(tasks: list, event_name: str, event_date: str) -> PolicyResult:
    reasons = []
    requires_approval = False
    
    for task in tasks:
        if task.budget_required and task.budget_required > 0:
            budget_result = check_budget_policy(task.budget_required)
            if budget_result.requires_approval:
                requires_approval = True
                reasons.extend(budget_result.reasons)
    
    schedule_result = check_schedule_policy(event_name, event_date)
    if schedule_result.requires_approval:
        requires_approval = True
        reasons.extend(schedule_result.reasons)
    
    return PolicyResult(requires_approval=requires_approval, reasons=reasons)

def approve_ticket() -> PolicyResult:
    return PolicyResult(requires_approval=False, reasons=[], approved=True)
