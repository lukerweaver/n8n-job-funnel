# Automated Job Funnel

This repository combines:

- `job-pipeline-service/`: the FastAPI backend and current source of truth
- `job-funnel-ui/`: the internal operator UI for applications and runs
- `job-scraper-chrome/`: the Chrome extension used to ingest jobs
- `exports/`: sanitized n8n workflow exports and prompt seed data
- `docs/`: lightweight architecture artifacts

The active flow is:

1. scrape jobs in the browser
2. ingest them into `job_postings`
3. classify postings
4. generate user-owned `job_applications` from matching resumes
5. score applications
6. track notifications, lifecycle status, and interview rounds

## Deployment Modes

There are now three practical ways to run this project:

1. Backend only
   Run `job-pipeline-service/` directly or with its local compose file.
2. Backend + UX + Postgres
   Run the repository root [`docker-compose-example.yml`](/home/lrw5016/projects/n8n-job-funnel/docker-compose-example.yml).
3. Separately deployed UX service
   Build and deploy [`job-funnel-ui/`](/home/lrw5016/projects/n8n-job-funnel/job-funnel-ui) as its own container and point it at a browser-visible API URL.

## Repo Layout

- `job-pipeline-service/` - FastAPI app, SQLAlchemy models, async run worker, tests, Docker assets
- `job-funnel-ui/` - Vite/React internal UI for scored applications, runs, and run results
- `job-scraper-chrome/` - unpacked Chrome extension for LinkedIn and Hiring Cafe capture
- `exports/workflows/` - sanitized n8n workflow exports for callback-driven orchestration
- `exports/data/` - example prompt library seed data
- `docs/architecture.mmd` - simple architecture diagram source

## Current Architecture

```text
LinkedIn / Hiring Cafe
    -> job-scraper-chrome
        -> POST /jobs/ingest
            -> job-pipeline-service
                -> job_postings
                -> classify postings
                -> generate applications from resumes
                -> score applications with LLM prompts
                -> persist lifecycle + notification state
                -> expose run status to n8n callbacks
```

## Backend Overview

The backend lives in [job-pipeline-service/README.md](/home/lrw5016/projects/n8n-job-funnel/job-pipeline-service/README.md).

The current backend centers on these tables:

- `job_postings`
- `users`
- `resumes`
- `job_applications`
- `interview_rounds`
- `prompt_library`
- `runs`
- `run_items`

Two identifier types matter:

- `job_id`: external string ID used for ingest dedupe
- `id`: internal integer primary key used by most read/write routes

## Main API Surface

High-value route groups:

- Jobs: `/jobs/ingest`, `/jobs`, `/jobs/{id}`, `/jobs/{id}/classify/run`, `/jobs/classify/run`
- Runs: `/runs`, `/runs/{run_id}`, `/runs/{run_id}/items`, `/runs/{run_id}/applications`
- Users and resumes: `/users`, `/resumes`, `/resumes/{id}`
- Applications: `/applications`, `/applications/generate`, `/applications/generate/run`, `/applications/{id}/score/run`, `/applications/score/run`
- Prompt library: `/prompt-library`, `/prompt-library/{prompt_id}`

The root README intentionally stays high-level. Route payload details and examples live in the service README.

## Local Development

### API only

From `job-pipeline-service/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app:app --host 0.0.0.0 --port 8000
```

Database behavior:

- default: SQLite at `job-pipeline-service/data/jobs.db`
- override: set `DATABASE_URL` to use Postgres or another SQLAlchemy-supported database

### UX only

From `job-funnel-ui/`:

```bash
npm install
npm run dev
```

By default the UX targets `http://localhost:8000`.

### Full local stack

From the repository root:

```bash
docker compose -f docker-compose-example.yml up --build -d
```

This starts:

- the internal UI on `http://localhost:8080`
- the API on `http://localhost:8000`
- Postgres on `localhost:5432`

Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8080/healthz
```

Stop it:

```bash
docker compose -f docker-compose-example.yml down
```

## Container Deployment

### Full stack from the repository root

Use the root compose file when you want one template that starts the UX service, backend API, and Postgres together:

```bash
docker compose -f docker-compose-example.yml up --build -d
```

Services:

- `job-funnel-ui`
- `job-pipeline-service`
- `postgres`

Published ports:

- UX: `8080`
- API: `8000`
- Postgres: `5432`

### UX service as a standalone container

Build from [`job-funnel-ui/`](/home/lrw5016/projects/n8n-job-funnel/job-funnel-ui):

```bash
docker build -t job-funnel-ui:latest .
```

Run it:

```bash
docker run -d \
  --name job-funnel-ui \
  -p 8080:80 \
  -e API_BASE_URL=https://api.example.com \
  job-funnel-ui:latest
```

Important:

- `API_BASE_URL` must be reachable from the browser, not just from inside Docker.
- For local compose development, `http://localhost:8000` is correct.
- For deployed environments, set it to your public API hostname or reverse-proxied API URL.

## Chrome Extension

The extension lives in `job-scraper-chrome/`.

Setup:

1. start the API
2. update `POST_ENDPOINT` in `job-scraper-chrome/background.js` if needed
3. open `chrome://extensions`
4. enable Developer mode
5. load `job-scraper-chrome/` as an unpacked extension

Details are in [job-scraper-chrome/README.md](/home/lrw5016/projects/n8n-job-funnel/job-scraper-chrome/README.md).

## Internal UI

The internal operator UI lives in [`job-funnel-ui/`](/home/lrw5016/projects/n8n-job-funnel/job-funnel-ui). It currently provides:

- scored application review
- run history
- run results drill-down

Details are in [job-funnel-ui/README.md](/home/lrw5016/projects/n8n-job-funnel/job-funnel-ui/README.md).

## n8n Workflows

The workflow exports in `exports/workflows/` are sanitized templates. After import, you need to reconfigure:

- API base URLs
- webhook URLs
- credential IDs
- recipient addresses
- any external document or storage IDs

The current intended sequence is:

1. queue `POST /jobs/classify/run`
2. on callback, run `POST /applications/generate/run`
3. queue `POST /applications/score/run`
4. on callback, fetch `/runs/{run_id}/items`
5. notify or update downstream systems

## Testing

Backend:

```bash
cd job-pipeline-service
.venv/bin/pytest
```

Extension:

```bash
cd job-scraper-chrome
npm install
npm test
```

Frontend:

```bash
cd job-funnel-ui
npm install
npm run build
```

## Notes

- The backend still exposes `GET /jobs/hiringcafe` for browser-based capture, but the preferred ingest path is the Chrome extension posting to `POST /jobs/ingest`.
- Prompt templates are stored in the service database and versioned by `prompt_key` plus `prompt_type`.
- The root README no longer documents every field or payload shape; use the service README for that level of detail.
