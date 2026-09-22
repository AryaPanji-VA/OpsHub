# OpsHub Agent

Terminal agent for a local operational planning demo. Phase 5 keeps the six-step
ReAct loop, per-task checks, human ticket approval, and local JSON storage.

## Run

Install with `pip install -e ".[dev]"`, then run `python -m opshub.cli`.
The default `LLM_PROVIDER=mock` is deterministic and needs no API key. Type meeting
notes, then `/run`; use `/log` to inspect the in-memory audit trail, `/new` to
reset the session, or `/exit` to leave.

Provider options are `mock`, `qwen` (Groq), `nex` (OpenRouter), and `fallback`
(Qwen/Groq primary, Nex/OpenRouter fallback). For the latter, set
`LLM_PROVIDER=fallback`, `GROQ_API_KEY`, and `OPENROUTER_API_KEY`. Recoverable
provider failures stop the run safely; free-tier availability is not guaranteed.

## Deterministic demos

Run `python -m pytest tests/test_phase5_scenarios.py -q` to replay all four cases
with temporary ticket and schedule files. The scripted plan has a budget task
requiring Rp12,000,000 and a schedule task due 2026-12-01.

| Scenario | Deterministic inputs | Expected result |
| --- | --- | --- |
| Safe flow | Budget Rp15,000,000; empty schedule; approve both proposals | Two tickets, then finish |
| Insufficient budget | Budget Rp10,000,000 | Failed check and human review; no ticket |
| Schedule conflict | Event on 2026-12-01 | Failed check and human review; no ticket |
| Missing critical context | No budget value and no budget file | Missing-context observation and human review; no ticket |

For the interactive mock demo, use the notes in `samples/grand_summit.txt`, type
`/run`, choose `2` to enter a budget, enter `15000000` for the safe path or
`10000000` for the budget block, and answer `y` only when a ticket approval prompt
appears. The scripted tests provide the two-task flow and schedule conflict without
editing `data/`.

## Safety boundary

The model returns only `{action, task_id, reason}`. Pydantic rejects extra or
missing fields and unknown actions. Python validates task IDs against the current
plan, derives required checks from each task, and supplies trusted arguments to
read-only budget and schedule tools. A ticket requires a separate human approval
for that task. `finish` requires all actionable tasks resolved and all required
checks clear. Repeated invalid actions reach `MAX_AGENT_STEPS=6` and escalate to
human review. Entering budget context is not ticket approval.

The CLI reads user-controlled `data/budgets.json` and `data/schedules.json` and
writes `data/tickets.json` only after approval. Tests use temporary fixtures and
do not modify runtime data. `/log` shows agent selections, tool observations,
approval decisions, ticket creation, escalation, and finish for the current
process. It is not persisted across restarts; copy it before exiting if an
external audit record is needed. See `ANALYSIS.md` for assumptions and rollback.

## Scope

This demo has no frontend, database, authentication, organization-system
integration, or durable audit service. Run the full suite with `python -m pytest`.
