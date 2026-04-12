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
- `job-funnel-ui/` contains the operator console frontend built with Vite, React, and TypeScript.
- `job-scraper-chrome/` contains the browser extension code.
- `exports/` and `docs/` contain seed/workflow artifacts and documentation.

## Frontend conventions
- The operator console is table-first and server-driven. Prefer filter bar + dense table + detail modal over dashboard cards or client-heavy data shaping.
- Existing page pattern for primary views is:
  `filter panel -> table -> row click opens modal -> arrow-key previous/next navigation -> escape closes modal`.
- Do not auto-open detail modals on page load. A modal should open only from explicit user action.
- Keep filter state in the URL query string with `useSearchParams` so navigation and refresh preserve the current view.
- Prefer reusing the existing `DetailModal` and `PaginationControls` components before introducing new interaction patterns.
- For new admin/edit flows, prefer modal-based create/edit forms that keep the main page list-focused unless the user asks for a dedicated editor layout.

## Backend and API notes
- Frontend pages should consume existing FastAPI endpoints directly where practical. Avoid introducing parallel client-only data models.
- Current operator UI routes are centered around:
  `/paste-job`, `/applications`, `/runs`, `/runs/{run_id}/applications`, `/resumes`, `/prompt-library`, and `/settings`.
- Keep service-managed workflow orchestration explicit. `job-pipeline-service/services/automation_service.py` owns automatic classification-to-scoring workflow decisions; `run_service.py` should stay focused on run enqueueing and execution.
- Preserve external/n8n orchestration support by honoring `automation_settings.auto_process_jobs == false` when changing automation behavior.
