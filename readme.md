# Automated Job Funnel

This repository combines:

- `job-pipeline-service/`: the FastAPI backend and current source of truth
- `job-funnel-ui/`: the internal operator UI for applications, runs, statistics, resumes, and prompts
- `job-scraper-chrome/`: the Chrome extension used to ingest jobs
- `exports/`: prompt seed data
- `docs/`: lightweight architecture artifacts

The default flow is:

1. open the Job Funnel UI
2. complete first-run onboarding
3. paste a resume
4. paste a job description, with an optional job URL
5. receive a job fit score and recommendation
6. optionally use advanced automation, the Chrome extension, or external n8n workflows

## Quick Start for Non-Technical Users

This path does not require editing prompts or installing the Chrome extension.

### 1. Install the basics

Install:

- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or another Docker runtime

Optional:

- A hosted AI provider API key, such as an OpenAI-compatible API key
- Ollama, if you prefer to run a local model

### 2. Download the app

From a terminal:

```bash
git clone https://github.com/lukerweaver/n8n-job-funnel.git
cd n8n-job-funnel
```

### 3. Start the app

From the repository root:

```bash
docker compose -f docker-compose-example.yml up --build -d
```

This starts:

- Job Funnel UI: `http://localhost:8080`
- Backend API: `http://localhost:8000`
- Postgres database: `localhost:5432`

Check that it started:

```bash
curl http://localhost:8000/health
```

The expected response is:

```json
{"ok":true}
```

### 4. Complete onboarding

Open:

```text
http://localhost:8080
```

The first screen asks for:

- Profile name
- Target roles, used as classification labels
- Resume text
- AI provider

Recommended AI provider choices:

- Hosted: choose this if you have an API key. Use an OpenAI-compatible base URL such as `https://api.openai.com/v1`, enter the model, and paste the API key.
- Local (Ollama): choose this if you already run Ollama. If the backend is running in Docker, the provider URL may need to be `http://host.docker.internal:11434` instead of `http://localhost:11434`.
- Configure later: choose this to explore the app first. Jobs will be saved, but scoring will wait until an AI provider is configured in Settings.

### 5. Paste a job and get a recommendation

After onboarding:

1. Go to **Paste Job**.
2. Paste the job description.
3. Add the job URL, company, and role title if you have them.
4. Click **Get Recommendation**.

The app saves the job, creates an application record for your default resume, and processes classification/scoring in the background. When the score is ready, the result includes:

- Role classification
- Job fit score
- Screening likelihood
- Recommendation
- Strengths
- Gaps

### 6. Optional advanced setup

Advanced users can open **Settings** and enable advanced navigation for:

- AI provider and model details
- Prompt editing
- Scoring and automation thresholds
- Resume strategy for automated scoring
- Batch runs

The Chrome extension remains optional. Use it only if you want browser-based job capture from LinkedIn or Hiring Cafe.

### Stop the app

From the repository root:

```bash
docker compose -f docker-compose-example.yml down
```

## Deployment Modes

There are now three practical ways to run this project:

1. Backend only
   Run `job-pipeline-service/` directly or with its local compose file.
2. Backend + UX + Postgres
   Run the repository root [`docker-compose-example.yml`](docker-compose-example.yml).
3. Separately deployed UX service
   Build and deploy [`job-funnel-ui/`](job-funnel-ui/) as its own container and point it at a browser-visible API URL.

## Repo Layout

- `job-pipeline-service/` - FastAPI app, SQLAlchemy models, async run worker, tests, Docker assets
- `job-funnel-ui/` - Vite/React internal UI for scored applications, runs, and run results
- `job-scraper-chrome/` - unpacked Chrome extension for LinkedIn and Hiring Cafe capture
- `exports/data/` - example prompt library seed data
- `docs/architecture.mmd` - simple architecture diagram source

## Current Architecture

```text
Job Funnel UI
    -> first-run onboarding
        -> users / resumes / app_settings / prompt_library
    -> paste job description and optional URL
        -> POST /jobs/paste
            -> job-pipeline-service
                -> job_postings
                -> job_applications
                -> backend run worker
                -> classify postings
                -> score applications with LLM prompts
                -> return job fit score and recommendation

Optional advanced ingestion:
LinkedIn / Hiring Cafe
    -> job-scraper-chrome
        -> POST /jobs/ingest

Optional advanced processing:
Runs page
    -> backend run worker
    -> classification and scoring batches

Optional advanced orchestration:
n8n
    -> owns run sequence when auto_process_jobs is false
    -> run and callback endpoints

Agent CLI
    -> uses the API-first workflow in docs/agent-cli-playbook.md
    -> reviews, ingests, classifies, generates, and scores through HTTP routes

Service-managed automation:
    -> auto_process_jobs = true
    -> backend worker queues classification when thresholds are met
    -> classification completion generates applications by resume_strategy
    -> backend worker queues scoring for new applications
```

## Backend Overview

The backend lives in [job-pipeline-service/README.md](job-pipeline-service/README.md).

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

- Onboarding: `/onboarding/status`, `/onboarding/complete`
- Settings: `/settings`
- Paste job: `/jobs/paste`
- Jobs: `/jobs/ingest`, `/jobs`, `/jobs/{id}`, `/jobs/{id}/classify/run`, `/jobs/classify/run`
- Runs: `/runs`, `/runs/{run_id}`, `/runs/{run_id}/items`, `/runs/{run_id}/applications`
- Statistics: `/statistics`
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
- LLM calls require explicit configuration through either `OLLAMA_BASE_URL` or the generic hosted-provider variables described in [`job-pipeline-service/README.md`](job-pipeline-service/README.md).

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

Build from [`job-funnel-ui/`](job-funnel-ui/):

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
2. open `chrome://extensions`
3. enable Developer mode
4. load `job-scraper-chrome/` as an unpacked extension
5. open the extension popup and select Test

Details are in [job-scraper-chrome/README.md](job-scraper-chrome/README.md) and [docs/chrome-extension-setup.md](docs/chrome-extension-setup.md).

## Internal UI

The internal operator UI lives in [`job-funnel-ui/`](job-funnel-ui/). It currently provides:

- All Applications, Active Applications, and Historical Applications views
- run history and run results drill-down
- direct launch actions for classification and scoring runs
- statistics for job ingest and score distribution
- resume and prompt library management

Details are in [job-funnel-ui/README.md](job-funnel-ui/README.md).

## Auto-Processing

By default, the backend service owns the main workflow. When `automation_settings.auto_process_jobs` is true and an AI provider is configured, the worker can:

1. queue classification for unclassified jobs when thresholds are met
2. generate applications after the classification run completes
3. queue scoring for the generated new applications

The automated application generation step uses `automation_settings.resume_strategy`:

- `default_fallback`: use resumes matching the classification key, or the default resume if none match
- `classification_first`: only use resumes matching the classification key
- `default_only`: only use the default resume

Set `automation_settings.auto_process_jobs` to false when n8n or another orchestrator should own that sequence. In that mode, the service still exposes the run endpoints, but it does not opportunistically queue classification and scoring workflows for you.

## n8n Workflows

Bundled n8n workflow exports are no longer part of the repository. The backend still supports external orchestration for users who want to keep their own n8n flow.

When `auto_process_jobs` is false, the intended n8n sequence is:

1. queue `POST /jobs/classify/run`
2. on callback, run `POST /applications/generate/run`
3. queue `POST /applications/score/run`
4. on callback, fetch `/runs/{run_id}/items`
5. notify or update downstream systems

## Agent CLI Workflows

Codex, Claude Code, and other terminal agents should use the HTTP API instead of editing the database directly. The recommended prompts, PowerShell examples, and safe run sequence are in [docs/agent-cli-playbook.md](docs/agent-cli-playbook.md).

Claude Code project skills are included under `.claude/skills/`:

- `/job-funnel-review`
- `/job-funnel-ingest`
- `/job-funnel-process`
- `/job-funnel-status`

Codex should follow the repo-level agent guidance in [AGENTS.md](AGENTS.md) and use the same playbook for API operations.

A portable Codex skill is included at `.codex/skills/job-funnel-operator/SKILL.md`. If your Codex install does not auto-discover repo-local skills, copy or symlink that folder into your personal Codex skills directory.

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
