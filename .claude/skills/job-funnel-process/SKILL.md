---
name: job-funnel-process
description: Run Job Funnel classification, application generation, and scoring through the local HTTP API. Use when the user explicitly asks an agent to process saved jobs or run the pipeline.
disable-model-invocation: true
---

Use the Job Funnel API. Default API base URL: `http://localhost:8000`.

Rules:
- Start with `GET /health` and `GET /settings`.
- Use HTTP API routes only.
- Do not edit the database.
- If the agent owns the sequence, ensure `automation_settings.auto_process_jobs` is `false` before running classification/generation/scoring.
- Poll `/runs/{run_id}` and inspect `/runs/{run_id}/items` before starting the next dependent step.
- Do not use `force: true` unless the user explicitly asks to reprocess existing work.
- Do not update statuses or notifications as part of processing.
- Read `docs/agent-cli-playbook.md` for exact PowerShell examples and payload shapes.

Workflow:
1. Check `GET /health`.
2. Read `GET /settings`.
3. Confirm whether the backend or the agent owns automation.
4. Queue classification with `POST /jobs/classify/run`.
5. Poll `GET /runs/{run_id}` until complete.
6. Generate applications with `POST /applications/generate/run`.
7. Queue scoring with `POST /applications/score/run`.
8. Poll scoring with `GET /runs/{run_id}` and summarize `/runs/{run_id}/applications`.
