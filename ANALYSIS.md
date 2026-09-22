# Analysis

## Architecture and trust boundary

`LLMProvider` generates an `OperationalPlan` and selects a strict
`AgentActionModel` containing exactly `action`, `task_id`, and `reason`. The
model does not supply tool arguments or perform writes. Python validates the
task ID against the current plan, derives budget and schedule checks from task
fields, dispatches read-only checks with runtime context, and gates each ticket
behind explicit human approval. A ticket-creation proposal alone cannot write
a ticket. `finish` is accepted only after required checks are clear and all
actionable tasks have tickets. Six agent steps are allowed per loop invocation;
exhaustion sets `wait_for_human`.

Qwen/Groq is primary and Nex/OpenRouter is fallback for provider failures.
Failures during plan generation or action selection do not authorize tickets.
The normal CLI reports recoverable errors without a traceback. Mock and scripted
providers make the four demo scenarios reproducible without network access.

## Assumptions and exclusions

- Local JSON files simulate operational sources; the actual finance/calendar
  authority and freshness guarantees were not specified.
- A missing budget file and no human budget value means missing critical context
  in the agent loop. The CLI requires manual budget input in that case. An empty
  schedule is currently treated as no known conflicts, so completeness of the
  calendar must be checked outside this prototype.
- Runtime budget or schedule context does not count as ticket approval.
- No frontend, database, authentication, organization integration, durable audit
  service, concurrent ticket writer, or automatic rollback is included.

## Audit and rollback

The in-memory audit records selected actions, tool statuses and messages,
invalid task IDs, human review and approval decisions, created ticket IDs,
step-limit escalation, and successful finish. `/log` displays it during the
session. It disappears when the process exits; export it before closing if it
must be retained. Tests use temporary ticket and schedule paths and leave the
user's `data/` files alone. For a real CLI run, save a copy of `data/tickets.json`
before approving a ticket. To roll back a mistaken demo ticket, restore that
copy after reviewing the audit and confirming no other ticket was added since.
There is no transactional rollback or protection against concurrent writers.
