# Job Pipeline Service

FastAPI backend for:

1. ingesting normalized jobs
2. classifying job postings
3. generating resume-specific applications
4. scoring applications with an LLM
5. tracking notification, lifecycle, and interview state
6. managing the default classification-to-scoring workflow
7. exposing async run status for external orchestration such as n8n

The current operator UI consumes this service directly for:

- application review across all, active, and historical views
- paste-job recommendations
- run inspection plus direct classification/scoring run launch
- statistics for ingest volume and score spread
- resume management
- prompt library management

## Requirements

- Python 3.11+
- optional Docker runtime for the compose example
- an LLM endpoint if you want service-side classification or scoring

## Database

The service supports SQLite and Postgres.

- If `DATABASE_URL` is set, that value is used.
- Otherwise the service uses SQLite at `./data/jobs.db`.

Tables are created on startup. Startup also runs lightweight schema/backfill helpers for the current models.

Current core tables:

- `job_postings`
- `users`
- `resumes`
- `job_applications`
- `interview_rounds`
- `prompt_library`
- `runs`
- `run_items`

## Configuration

Supported environment variables:

- `DATABASE_URL`
- `SCORING_PROVIDER` optional
- `SCORING_MODEL` optional, required for `openai_compatible`
- `OLLAMA_BASE_URL` optional, required for `ollama`
- `OLLAMA_MODEL` optional, defaults to `qwen2.5:14b-instruct` when using Ollama
- `OLLAMA_NUM_CTX` default `50000`
- `LLM_BASE_URL` optional, required for `openai_compatible`
- `LLM_API_KEY` optional, required for `openai_compatible`
- `LLM_TIMEOUT_SECONDS` default `180`

The current LLM implementation supports:

- `ollama`
- `openai_compatible`

`openai_compatible` is the generic hosted-provider path and works with any provider that exposes an OpenAI-style chat completions API given a host, API key, and model.

Accepted explicit `SCORING_PROVIDER` values:

- `ollama`
- `openai_compatible`
- `openai` (alias of `openai_compatible`)
- `groq` (alias of `openai_compatible`)

Provider resolution rules:

1. If `SCORING_PROVIDER` is set, that provider is used.
2. Otherwise if `OLLAMA_BASE_URL` is set, the service uses `ollama`.
3. Otherwise if `LLM_BASE_URL` and `LLM_API_KEY` are set, the service uses `openai_compatible`.
4. Otherwise classification and scoring calls fail with a clear "No LLM provider configured" error.

There is intentionally no default `OLLAMA_BASE_URL`. This prevents installs from silently assuming a local Ollama instance exists.

Settings can also store workflow controls in `automation_settings`:

- `auto_process_jobs`: when false, disables service-managed automatic processing so n8n or another orchestrator can own the workflow
- `unprocessed_jobs_threshold`: minimum pending unclassified jobs before automatic classification runs
- `minutes_since_last_run_threshold`: time-based fallback for automatic classification runs
- `resume_strategy`: `default_fallback`, `classification_first`, or `default_only`

The backend reads these settings from the database, not only from environment variables, so they can be updated through `/settings` and the operator UI.

### LLM configuration examples

Ollama:

```bash
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=qwen2.5:14b-instruct
```

Generic OpenAI-compatible host:

```bash
export SCORING_PROVIDER=openai_compatible
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_API_KEY=your-api-key
export SCORING_MODEL=gpt-4.1-mini
```

Groq using the same generic client:

```bash
export SCORING_PROVIDER=groq
export LLM_BASE_URL=https://api.groq.com/openai/v1
export LLM_API_KEY=your-api-key
export SCORING_MODEL=llama-3.3-70b-versatile
```

## Prompt Model

Prompts live in `prompt_library` and are keyed by:

- `prompt_key`
- `prompt_type`
- `prompt_version`

Prompt types in current use:

- `classification`
- `scoring`
- `tailoring`

Current routing contract:

- `classification_key` is the business/domain key used to match jobs to resumes
- `prompt_key` is the prompt-family selector used to load an active prompt
- classify and score routes may derive the prompt selector from the passed `classification_key`
- explicit `prompt_key` still overrides derived prompt selection

Resume contract:

- targeted resumes use a non-null `classification_key`
- fallback resumes can use `is_default = true`
- generation routes choose resumes with `resume_strategy`

Current `resume_strategy` values:

- `classification_first`: use only resumes whose `classification_key` matches the job
- `default_only`: use only the default resume
- `default_fallback`: use matching resumes first, then fall back to the default resume

## Local Run

From `job-pipeline-service/`:

### 1. Create and activate a virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Start the API

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

### 4. Verify

```bash
curl http://localhost:8000/health
```

## Docker

Build:

```bash
docker build -t job-pipeline-service:latest .
```

Run directly:

```bash
docker run -d --name job-pipeline-service -p 8000:8000 job-pipeline-service:latest
```

This is the backend-only container path.

Run service-only with Postgres:

```bash
docker compose -f docker-compose-example.yml up --build -d
```

The compose example:

- builds the local image
- exposes the API on `localhost:8000`
- starts Postgres on `localhost:5432`
- sets `DATABASE_URL` for the API container
- includes an example LLM configuration block you can switch between Ollama and hosted providers

Stop it:

```bash
docker compose -f docker-compose-example.yml down
```

Run the full stack from the repository root:

```bash
docker compose -f ../docker-compose-example.yml up --build -d
```

That starts:

- the internal UI on `http://localhost:8080`
- the API on `http://localhost:8000`
- Postgres on `localhost:5432`

Use the repository-root compose file when you want the new UX service included.

Published services in the root compose template:

- `job-funnel-ui`
- `job-pipeline-service`
- `postgres`

Browser-facing URLs:

- UX: `http://localhost:8080`
- API: `http://localhost:8000`

## Testing

From `job-pipeline-service/`:

```bash
.venv/bin/pytest
```

Coverage command:

```bash
.venv/bin/pytest \
  --cov=app \
  --cov=services.scoring_service \
  --cov=services.scoring_parser \
  --cov=services.llm_client \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=json
```

Optional threshold gate:

```bash
.venv/bin/python scripts/coverage_gate.py coverage.json 80
```

## API Summary

### System

- `GET /health`

### Jobs

- `POST /jobs/paste`
- `POST /jobs/ingest`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/classify/run`
- `POST /jobs/classify/run`
- `GET /jobs/hiringcafe?search_url=<HIRING_CAFE_URL>`

### Runs

- `GET /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/items`
- `GET /runs/{run_id}/applications`

### Statistics

- `GET /statistics`

### Users and resumes

- `GET /users`
- `POST /users`
- `GET /resumes`
- `POST /resumes`
- `PUT /resumes/{resume_id}`

### Applications

- `GET /applications`
- `GET /applications/{application_id}`
- `POST /applications`
- `POST /applications/generate`
- `POST /applications/generate/run`
- `POST /applications/{application_id}/score`
- `POST /applications/{application_id}/score/run`
- `POST /applications/score/run`
- `POST /applications/{application_id}/notify`
- `POST /applications/{application_id}/error`
- `POST /applications/{application_id}/status`
- `PUT /applications/{application_id}/lifecycle-dates`
- `GET /applications/{application_id}/interview-rounds`
- `POST /applications/{application_id}/interview-rounds`
- `PUT /applications/{application_id}/interview-rounds/{interview_round_id}`
- `DELETE /applications/{application_id}/interview-rounds/{interview_round_id}`

### Prompt library

- `GET /prompt-library`
- `GET /prompt-library/{prompt_id}`
- `POST /prompt-library`
- `PUT /prompt-library/{prompt_id}`
- `DELETE /prompt-library/{prompt_id}`

## Important Semantics

Two job identifiers exist:

- `job_id`: external string identifier used at ingest time
- `id`: internal integer primary key used by most route paths and relationships

Default service-managed automation:

1. The run worker checks for queued/running work.
2. If there is no active classification or scoring run, `auto_process_jobs` is enabled, and an AI provider is configured, the service may queue `POST /jobs/classify/run` behavior internally.
3. When that classification run completes, the service generates missing applications for classified jobs using `resume_strategy`.
4. The service queues scoring for the generated applications.

External automation sequence:

1. `POST /jobs/classify/run`
2. callback fetches `/runs/{run_id}` or `/runs/{run_id}/items`
3. `POST /applications/generate/run`
4. `POST /applications/score/run`
5. downstream notification or tracking writes

Set `automation_settings.auto_process_jobs` to false if n8n or another tool should own that sequence. The run endpoints remain available in both modes.

## Selected Route Notes

### `GET /settings` and `PUT /settings`

Reads and updates operator settings, including provider configuration, default prompt key, scoring preferences, and automation settings.

Example automation payload:

```json
{
  "automation_settings": {
    "auto_process_jobs": true,
    "unprocessed_jobs_threshold": 5,
    "minutes_since_last_run_threshold": 60,
    "opportunistic_trigger_enabled": true,
    "resume_strategy": "default_fallback"
  }
}
```

Use `"auto_process_jobs": false` for n8n-managed workflows.

### `POST /jobs/paste`

Creates or updates a manual job posting, creates an application for the selected user's resume, and optionally queues classification and scoring immediately.

The current UI sends a job description and an optional job URL. The API still accepts `input_type`, which defaults to `description`.

Example:

```json
{
  "description": "Full job description",
  "url": "https://example.com/jobs/123",
  "company_name": "Example Co",
  "title": "Product Manager",
  "process_now": true,
  "mode": "async"
}
```

### `POST /jobs/ingest`

Accepts one job object or an array. Ingest is insert-only by external `job_id`; duplicates are skipped.

Example:

```json
{
  "job_id": "linkedin_123",
  "company_name": "Example Co",
  "title": "Product Manager",
  "yearly_min_compensation": 150000,
  "yearly_max_compensation": 180000,
  "apply_url": "https://example.com/jobs/123",
  "description": "Full job description",
  "source": "linkedin"
}
```

### `GET /jobs`

Current query filters:

- `source`
- `classification_key`
- `q`
- `has_classification`
- `has_applications`
- `classified_since`
- `limit`
- `offset`

### `POST /jobs/classify/run`

Queues async classification across postings.

Example:

```json
{
  "limit": 100,
  "source": "linkedin",
  "classification_key": "product_classification",
  "force": false
}
```

### `POST /applications/generate`

Creates `job_applications` for one posting and user using one of:

- `classification_first`
- `default_only`
- `default_fallback`

Example:

```json
{
  "job_posting_id": 123,
  "user_id": 1,
  "resume_strategy": "default_fallback"
}
```

### `POST /applications/generate/run`

Creates missing applications for a user across classified postings.

Example:

```json
{
  "user_id": 1,
  "limit": 100,
  "resume_strategy": "classification_first"
}
```

### `POST /applications/score/run`

Queues async scoring for application rows.

Example:

```json
{
  "limit": 100,
  "status": "new",
  "force": false
}
```

### `GET /statistics`

Returns the operator-facing statistics payload used by the Statistics tab.

Current response sections:

- `ingested_jobs`: daily ingest counts, high-score counts, rolling 7-day averages, and high-score percentages
- `score_distribution`: scored-job count, min/max/average score, and histogram buckets

## Prompt Library Seed

The repository includes a sanitized example seed at `../exports/data/prompt_library.seed.mock.json`.

`POST /prompt-library` accepts one prompt object at a time. To load the example seed from the repo root in PowerShell:

```powershell
$seed = Get-Content .\exports\data\prompt_library.seed.mock.json | ConvertFrom-Json
foreach ($prompt in $seed) {
  $prompt | ConvertTo-Json -Depth 10 | curl.exe -X POST http://localhost:8000/prompt-library `
    -H "Content-Type: application/json" `
    --data-binary @-
}
```

Verify:

```bash
curl http://localhost:8000/prompt-library
```

## Notes

- `GET /jobs/hiringcafe` remains available for service-side capture, but the preferred ingest path is still the Chrome extension posting to `POST /jobs/ingest`.
- Async work is tracked in `runs` and `run_items`, not the older `score_runs` naming.
- Application scoring is the primary scoring flow. The docs no longer treat job-level scoring as the main path.
