# ANALYSIS

Phase 0: Initial Framework

## Architecture Decisions

- Local JSON storage for simplicity
- Abstract LLMProvider for future provider additions
- Policy layer separates approval logic from tools

## Design Patterns

- Strategy pattern for LLM providers
- Policy pattern for approval gates

## Assumptions & Brief Gaps

- Organizational budget source was not defined in the brief
- MVP supports local simulated data plus explicit runtime human context
- The agent does not invent missing operational values
- Runtime JSON files are user-controlled state (tests are isolated)

## TODOs

- [ ] Add real LLM providers (Qwen, GLM, Gemma)
- [ ] Implement audit log persistence
- [ ] Add database support
- [ ] Build ticket review UI
- [ ] Integrate with organization systems (finance API, calendar, etc.)
