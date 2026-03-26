# AGENTS.md (repository root)

Guidance for coding agents working in this repository.

## Scope
This file applies to the entire repository unless a deeper `AGENTS.md` overrides it.

## Workflow
1. Create a feature branch (or use the assigned branch).
2. Make focused commits with clear messages.
3. Run relevant tests before opening/updating a PR.
4. Summarize what changed, what was tested, and any known limitations.

## Safety and quality
- Prefer minimal, targeted changes over broad refactors.
- Keep behavior-compatible changes unless the task explicitly requires behavior changes.
- Avoid adding new runtime dependencies unless necessary.
- Document any new scripts, workflows, or developer commands.

## Testing expectations
- Run tests for the area you changed.
- If you cannot run a check due to environment limits, explicitly state what blocked execution.

## Repository structure
- `job-pipeline-service/` contains the FastAPI backend and tests.
- `job-scraper-chrome/` contains the browser extension code.
- `exports/` and `docs/` contain seed/workflow artifacts and documentation.
