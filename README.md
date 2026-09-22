# OpsHub Agent

Terminal-native autonomous AI agent for SGA operational coordination.

## Status

Phase 4 - Automatic LLM provider fallback.

## Features (Implemented)

- Interactive CLI for pasting meeting notes
- Mock LLM provider for development
- **Qwen/Groq primary provider** with automatic fallback
- **Nex/OpenRouter fallback** for recoverable failures
- Strict structured OperationalPlan output
- Pydantic validation
- Read-only tools:
  - check_budget()
  - check_schedule()
- Policy evaluation
- Human-in-the-loop approval
- Per-task ticket creation
- Runtime operational context (manual budget input)
- Audit logging for all actions

## LLM Provider Fallback

**Primary:** Qwen 3.8 27B via Groq (free tier)

**Fallback:** Nex-N2.5-Pro via OpenRouter (free tier)

When Qwen/Groq is unavailable due to rate limits, timeouts, or temporary failures, OpsHub automatically switches to Nex/OpenRouter. This ensures continued operation while respecting the Rp0 budget constraint.

**Both services are free-tier** and may independently enforce rate limits. The fallback mechanism provides reliability but does not guarantee unlimited availability.

### Configuration

| LLM_PROVIDER | Behavior |
|--------------|----------|
| `mock` | Mock provider (no API calls) |
| `qwen` | Qwen/Groq only |
| `nex` | Nex/OpenRouter only |
| `fallback` | Qwen primary, Nex fallback |

## Runtime Operational Context

Meeting notes do not always contain all operational data. OpsHub never invents missing operational values.

**Budget sources:**
- Runtime data files (data/budgets.json)
- Explicit human input during CLI session

**Important:** Human-provided context is separate from human approval. Entering a budget amount does NOT grant approval to create a ticket.

**Local JSON files** are currently the simulation source for the internship MVP.

## Not Implemented (Future)

- Web frontend
- Database
- RAG/embeddings
- Authentication
- Networking
- Native LLM tool calling
- ReAct loop

## Architecture

```
opshub/
    ├── cli.py          # Interactive terminal interface
    ├── agent.py        # Core orchestration
    ├── models.py       # Type definitions
    ├── policy.py       # Approval logic
    └── llm/
        ├── base.py     # LLMProvider interface
        ├── mock.py     # Mock implementation
        ├── qwen.py     # Qwen/Groq provider
        ├── nex.py      # Nex/OpenRouter provider
        ├── fallback.py # Fallback provider
        └── exceptions.py # Custom exceptions
    └── tools/
        ├── budget.py   # Budget checks
        ├── schedule.py # Schedule checks
        └── ticket.py   # Ticket creation

data/                 # JSON storage for ops data (user-controlled runtime)
tests/
    └── fixtures/     # Test fixtures (isolated from runtime)
```

## Running

```bash
python -m opshub.cli
```

### With Qwen Provider (Primary)

```bash
# Set environment variables
export GROQ_API_KEY=your_key
export MODEL_NAME=qwen/qwen3.8-27b
export LLM_PROVIDER=qwen

python -m opshub.cli
```

### With Automatic Fallback

```bash
# Set both providers
export GROQ_API_KEY=your_key
export MODEL_NAME=qwen/qwen3.8-27b
export OPENROUTER_API_KEY=your_key
export OPENROUTER_MODEL=nex-agi/nex-n2.5-pro:free
export LLM_PROVIDER=fallback

python -m opshub.cli
```

### With Fallback Only (for testing)

```bash
export OPENROUTER_API_KEY=your_key
export OPENROUTER_MODEL=nex-agi/nex-n2.5-pro:free
export LLM_PROVIDER=nex

python -m opshub.cli
```

### Manual Test

```bash
export LLM_PROVIDER=mock
python -m opshub.cli
# Paste content from samples/grand_summit.txt
# Type /run to generate plan
# Follow budget input prompts
# Type /run again after entering budget
```

## Human-in-the-loop Workflow

**Safe workflow:**
```
Next Action: ready_to_create_ticket
Create ticket for task_1?
[y/N] > y
Ticket OPS-001 created.
Workflow completed.
```

**Blocked workflow with exception:**
```
Next Action: wait_for_human
Blocking reasons:
  - Budget insufficient for task_1
Options:
  [A] Approve exception
  [R] Reject
  [E] Exit

> A
Exception approved by human.
Risk remains recorded.
Create ticket for task_1?
[y/N] > y
Ticket OPS-002 created.
Workflow completed.
```

## Development

```bash
# Setup
pip install -e ".[dev]"

# Run tests
pytest

# Type check
mypy opshub/
```

## License

MIT
