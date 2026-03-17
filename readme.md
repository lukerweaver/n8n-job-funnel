# Automated Job Funnel (n8n + LLM)

An automated job search pipeline built with n8n workflows and a Postgres-backed FastAPI service.

The pipeline ingests jobs, scores them against a structured rubric, and tracks outcomes for follow-up.

---

## Overview

This project automates:

1. Job collection (from Chrome plugin scraping HiringCafe + LinkedIn)
2. LLM scoring with strict schema
3. Job filtering by score/recommendation
4. Score + metadata persistence
5. Notification + tracker sync

---

## Architecture

```text
HiringCafe + LinkedIn via Chrome plugin
    -> job-pipeline-service (FastAPI)
        -> Postgres (job_postings + prompt_library)
            -> n8n score workflow
                -> Ollama (or external LLM)
                    -> Google Sheets tracker + email
```

`job-pipeline-service` is the operational source of truth for jobs and prompt templates.

---

## Workflows

The repo includes two n8n workflow exports:

- `exports/workflows/01_ingest_jobs.json`
- `exports/workflows/02_score_jobs_llm.json`

### 1) Job Import Workflow

**Flow**

```text
Chrome plugin -> POST /jobs/ingest -> upsert into job_postings
```

### 2) Job Scoring Workflow

**Flow**

```text
Get new jobs -> GET /jobs?status=new -> build prompt context -> LLM -> PUT /jobs/{id}/score -> mark/notify
```

---

## API (primary control plane)

### Jobs

- `POST /jobs/ingest` — upsert by `job_id`
- `GET /jobs` — list jobs (filter by status/source)
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/score`
- `POST /jobs/scores` — batch score update
- `POST /jobs/{job_id}/notify`
- `POST /jobs/notify` — batch notify

### Prompt Library

- `GET /prompt-library`
- `GET /prompt-library/{prompt_id}`
- `POST /prompt-library`
- `PUT /prompt-library/{prompt_id}`
- `DELETE /prompt-library/{prompt_id}`

The service stores prompt templates in `prompt_library` and does not require n8n Data Tables.

---

## Data model

### `job_postings`

- `id` (int PK)
- `job_id` (string unique)
- `status` (`new`, `scored`, `notified`, etc.)
- score fields (`score`, `recommendation`, `strengths`, etc.)
- `prompt_key`, `prompt_version`
- timestamps (`created_at`, `updated_at`, `scored_at`, `notified_at`)

### `prompt_library`

- `id` (int PK)
- `prompt_key`
- `prompt_version`
- `system_prompt`
- `user_prompt_template`
- `base_resume_template`
- `is_active`

`prompt_key` + `prompt_version` is unique and used for lookup/versioning.

---

## Project status notes

- SQLite path issues are avoided in production by using Postgres in compose.
- Job IDs are used for dedupe in ingestion, not required for prompt selection.
- Prompt selection is done via dedicated `prompt_library` endpoints and versioned records.
- Seeding from static JSON is optional and **not** run automatically on startup.

---

## Runtime environments

- Local development:
  - n8n (`5678`)
  - Ollama (`11434`) or external LLM
  - `job-pipeline-service` (`8000`)
  - Postgres (`5432`)

- Deployment:
  - service stack can run in any container host with Postgres connectivity
  - set `DATABASE_URL` and keep `DATABASE_URL` consistent across restarts

---

## Setup

### 1) Import workflows

In n8n, import:

- `exports/workflows/01_ingest_jobs.json`
- `exports/workflows/02_score_jobs_llm.json`

Both are inactive by default.

### 2) Start local stack

From repo root:

```bash
docker compose up -d
```

This brings up:

- `job-pipeline-service` (`job-pipeline-service/docker-compose.yml`)
- `postgres` (`postgres:17`)

### 3) Configure app endpoints in n8n

Point workflow calls at your service URL, e.g. `http://job-pipeline-service:8000` (inside compose) or `http://localhost:8000` locally.

### 4) Seed prompt library (optional)

Use one of these options:

- API:
  - `POST /prompt-library` with payload from `exports/data/prompt_library.seed.mock.json`
- Local helper:
  - `prompt_library_manual_tool.ps1` (manual entry / CSV helper)
- Browser UI:
  - `prompt-library-admin.html` (CRUD tool for local use)

> There is no startup auto-seed anymore.

### 5) Test health

```bash
curl http://localhost:8000/health
```

---

## Development notes

- Use `POST /jobs/ingest` for raw job payload import.
- Use `POST /jobs/{job_id}/score` to write evaluation output.
- Use prompt endpoints to iterate quickly on prompt quality without code deploys.

---

## Dependencies

- n8n
- Ollama or equivalent LLM API
- PostgreSQL
- Chrome plugin integration for scraping HiringCafe + LinkedIn and posting job payloads to `/jobs/ingest`

---

### Ingestion architecture note

- Playwright was removed as the source scraping mechanism.
- Jobs are now collected via a Chrome plugin that scrapes HiringCafe and LinkedIn, then posts directly to `POST /jobs/ingest` on `job-pipeline-service`.
- This avoids in-service browser automation and reduces scraping fragility in container/runtime environments.

---

## License

MIT
