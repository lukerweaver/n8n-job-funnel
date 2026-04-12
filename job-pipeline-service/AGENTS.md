# AGENTS.md (job-pipeline-service)

Agent instructions specific to `job-pipeline-service/`.

## Scope
This file applies to everything under `job-pipeline-service/`.

## Local validation checklist
Run these from `job-pipeline-service/` before finalizing changes:

1. `pytest`
2. `pytest --cov=app --cov=services.scoring_service --cov=services.scoring_parser --cov=services.llm_client --cov-branch --cov-report=term-missing --cov-report=json`
3. `python scripts/coverage_gate.py coverage.json 80`

If coverage tooling is unavailable locally, note that clearly and rely on CI to enforce the gate.

## Coverage policy
- Minimum line coverage target: **80%**
- Minimum branch coverage target: **80%**
- Current enforced scope: `app.py`, `services/scoring_service.py`, `services/scoring_parser.py`, `services/llm_client.py`

CI enforces this in `.github/workflows/job-pipeline-service-tests.yml`.

## Test conventions
- Use fixtures from `tests/conftest.py` for DB reset/session lifecycle.
- Use `tests/helpers.py` seed helpers for deterministic setup.
- Prefer explicit assertions for both success and error paths.
- Mock LLM/network interactions for unit tests; avoid real remote calls.

## App-specific notes
- The `/jobs/hiringcafe` endpoint uses Playwright and external navigation; keep it out of standard deterministic unit tests unless explicitly requested.
- For endpoint-level tests, prioritize behavior and response contract validation.
- Keep `services/run_service.py` focused on run enqueueing, worker polling, and run-item execution.
- Put service-managed workflow orchestration in `services/automation_service.py`, including auto classification triggers and classification-complete scoring handoff.
- Preserve n8n/external ownership by checking `automation_settings.workflow_owner` before adding automatic workflow behavior.
