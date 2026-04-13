---
name: job-funnel-operator
description: Operate Job Funnel through its local HTTP API for read-only application review, job ingest, classification, application generation, scoring, and guarded status updates. Use when the user asks Codex to work with a running Job Funnel instance, manage jobs/applications, or automate the job funnel workflow.
---

Use the Job Funnel API. Default API base URL: `http://localhost:8000`.

Core rules:
- Start with `GET /health` and, for anything beyond a single read, `GET /settings`.
- Use HTTP API routes only.
- Do not edit the database directly.
- Prefer read-only review unless the user explicitly asks for ingestion, classification, scoring, or record updates.
- Ask before changing application statuses, lifecycle dates, interview rounds, notification state, prompts, provider settings, or automation settings.
- If an external agent owns classification/generation/scoring, set or confirm `automation_settings.auto_process_jobs == false` before queueing runs.
- Do not use `force: true` unless the user explicitly asks to reprocess existing work.

Primary reference:
- Read `docs/agent-cli-playbook.md` for route payloads, PowerShell examples, prompt templates, and failure handling.

Workflows:
1. Review: `GET /health`, `GET /settings`, then `GET /applications?limit=25&offset=0` or filtered application lists.
2. Ingest: use `POST /jobs/ingest` for normalized jobs or `POST /jobs/paste` for pasted job descriptions, then report created/skipped counts.
3. Process: queue `POST /jobs/classify/run`, poll `/runs/{run_id}`, run `POST /applications/generate/run`, then queue `POST /applications/score/run`.
4. Status updates: fetch the target application first, then use the narrowest status, lifecycle, or interview-round route.
