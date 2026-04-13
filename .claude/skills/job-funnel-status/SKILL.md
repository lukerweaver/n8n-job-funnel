---
name: job-funnel-status
description: Update Job Funnel application status, lifecycle notes, or interview rounds through the local HTTP API. Use only when the user explicitly asks to change application records.
disable-model-invocation: true
---

Use the Job Funnel API. Default API base URL: `http://localhost:8000`.

Rules:
- Start with `GET /health`.
- Fetch the target application before mutating it.
- Use HTTP API routes only.
- Do not edit the database.
- Ask for confirmation before bulk status changes.
- Do not send notifications unless the user explicitly asks.
- Read `docs/agent-cli-playbook.md` for PowerShell examples and payload shapes.

Workflow:
1. Check `GET /health`.
2. Fetch the application with `GET /applications/{application_id}`.
3. Apply the requested change with the narrowest route:
   - `POST /applications/{application_id}/status`
   - `PUT /applications/{application_id}/lifecycle-dates`
   - `POST /applications/{application_id}/interview-rounds`
   - `PUT /applications/{application_id}/interview-rounds/{interview_round_id}`
4. Read the updated record and summarize the change.
