---
name: job-funnel-onboarding
description: Guide a user through first-time Job Funnel setup with Codex, including app health checks, onboarding fields, AI provider setup, targeted resumes, and Chrome extension ingest. Use when the user asks Codex to help set up or onboard Job Funnel.
---

Use the Job Funnel UI and API. Default URLs:
- UI: `http://localhost:8080`
- API: `http://localhost:8000`

Core rules:
- Start with `GET /health` when operating the running app.
- Use the UI for secrets such as hosted AI provider API keys unless the user explicitly asks for API-based setup.
- Do not ask the user to paste API keys into chat by default.
- Do not edit the database directly.
- Do not queue classification, scoring, notifications, or status updates during onboarding unless the user explicitly asks.
- Follow repo guidance in `AGENTS.md`.
- Read `docs/chrome-extension-setup.md` for Chrome extension setup details.
- Read `docs/agent-cli-playbook.md` for API route examples when the user asks to operate through an agent CLI.

Workflow:
1. Confirm the app is running:
   - API: `GET /health`
   - UI: open `http://localhost:8080`
2. Guide first-run onboarding:
   - profile name
   - target roles used as classification labels
   - default resume content
   - AI provider choice: hosted, Ollama, or configure later
3. For targeted resumes:
   - use the Resumes page
   - create a resume with "Use this resume for" set to a target role
   - ensure Resume Strategy is not `default_only`
4. For Chrome extension ingest:
   - load `job-scraper-chrome/` as an unpacked extension
   - set App API URL to `http://localhost:8000`
   - use the popup Test button
5. Stop after setup and summarize what is ready, what remains unconfigured, and what check should be run next.
