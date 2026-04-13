---
name: job-funnel-review
description: Review Job Funnel applications through the local HTTP API. Use for read-only summaries of recent, active, high-scoring, or role-filtered job applications.
---

Use the Job Funnel API. Default API base URL: `http://localhost:8000`.

Rules:
- Start with `GET /health`.
- Use HTTP API routes only.
- Do not edit the database.
- Do not update statuses, settings, prompts, notifications, or scoring runs.
- Read `docs/agent-cli-playbook.md` when you need exact PowerShell examples or route payloads.

Workflow:
1. Check `GET /health`.
2. Read `GET /settings`.
3. List applications with `GET /applications?limit=25&offset=0`.
4. For active work, use `GET /applications?status_group=active&limit=25&offset=0`.
5. For target-role filtering, use `GET /applications?classification_key=<encoded role>&limit=25&offset=0`.
6. Summarize the strongest opportunities, obvious gaps, and records with score errors.
