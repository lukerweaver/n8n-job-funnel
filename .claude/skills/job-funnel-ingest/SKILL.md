---
name: job-funnel-ingest
description: Ingest jobs into Job Funnel through the local HTTP API. Use when the user provides a job description, normalized job payload, or asks to add jobs without browser capture.
disable-model-invocation: true
---

Use the Job Funnel API. Default API base URL: `http://localhost:8000`.

Rules:
- Start with `GET /health`.
- Use HTTP API routes only.
- Do not edit the database.
- Use `POST /jobs/ingest` for normalized job objects.
- Use `POST /jobs/paste` for pasted descriptions.
- Report created/skipped counts or the returned job/application IDs.
- Do not queue classification or scoring unless the user explicitly asks.
- Read `docs/agent-cli-playbook.md` for PowerShell examples and payload shapes.

Workflow:
1. Check `GET /health`.
2. Choose `/jobs/ingest` or `/jobs/paste` based on the user input.
3. Send the request.
4. Summarize the API response and stop before processing unless requested.
