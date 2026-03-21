# Job Pipeline Service

FastAPI service for:

1. ingesting normalized jobs from the Chrome extension
2. storing job records and prompt templates
3. exposing routes that n8n can use to trigger scoring and write notification state back
4. keeping a legacy Hiring Cafe Playwright capture route available

The primary ingestion path is `POST /jobs/ingest` from `job-scraper-chrome`.

## Requirements

- Python 3.11+
- Docker Desktop or another Docker runtime if you want to use the compose example

## Database behavior

This service supports both SQLite and Postgres.

- If `DATABASE_URL` is set, that value is used.
- If `DATABASE_URL` is not set and `./data/jobs.db` already exists, the service uses `sqlite:///./data/jobs.db`.
- Otherwise it uses `sqlite:///./jobs.db`.

Tables are created automatically on startup.

## Scoring configuration

The service can score jobs directly using a configured LLM provider.

Supported environment variables:

- `SCORING_PROVIDER` default `ollama`
- `SCORING_MODEL` default `qwen2.5:14b-instruct`
- `OLLAMA_BASE_URL` default `http://localhost:11434`
- `OLLAMA_NUM_CTX` default `50000`
- `LLM_TIMEOUT_SECONDS` default `180`
- `DEFAULT_PROMPT_KEY` optional

The current implementation supports `ollama` as the scoring provider.

### Scoring payload schema

The scoring parser accepts both legacy and updated LLM JSON outputs.

- Legacy supported fields: `total_score`, `recommendation`, `justification`, `strengths`, `gaps`, `missing_from_jd`.
- New optional fields:
  - `role_type`
  - `screening_likelihood`
  - `dimension_scores`
  - `gating_flags`

The parser is backwards compatible: old prompt outputs still parse and persist without requiring the new fields.

## Local run

From `job-pipeline-service/`:

### 1. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

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

### 4. Verify it is running

```bash
curl http://localhost:8000/health
```

## Docker

Build the image:

```bash
docker build -t job-pipeline-service:latest .
```

Run the image directly:

```bash
docker run -d --name job-pipeline-service -p 8000:8000 \
  job-pipeline-service:latest
```

To run with Postgres, use the compose example instead of a standalone container.

## Docker Compose

The included compose file is `docker-compose-example.yml`.

From `job-pipeline-service/`:

```bash
docker compose -f docker-compose-example.yml up --build -d
```

Stop it:

```bash
docker compose -f docker-compose-example.yml down
```

The compose example:

- builds the local `Dockerfile`
- exposes the API on `localhost:8000`
- starts Postgres `17` on `localhost:5432`
- sets `DATABASE_URL` to the Postgres service
- waits for Postgres to become healthy before starting the API

## API

- `GET /health`
- `POST /jobs/ingest`
- `GET /jobs`
- `GET /jobs/{id}`
- `POST /jobs/{id}/score/run`
- `POST /jobs/score/run`
- `GET /score-runs/{run_id}`
- `GET /score-runs/{run_id}/items`
- `POST /jobs/{id}/score`
- `POST /job/{id}/error`
- `POST /jobs/scores`
- `POST /jobs/{id}/notify`
- `POST /jobs/notify`
- `GET /prompt-library`
- `GET /prompt-library/{prompt_id}`
- `POST /prompt-library`
- `PUT /prompt-library/{prompt_id}`
- `DELETE /prompt-library/{prompt_id}`
- `GET /jobs/hiringcafe?search_url=<HIRING_CAFE_URL>`

### ID semantics

The service uses two job identifiers:

- `job_id` - external string identifier used for ingest dedupe
- `id` - internal numeric database primary key used by `GET /jobs/{id}`, score routes, and notify routes

That distinction matters for n8n integrations. Ingest works with external `job_id`, while score and notify writeback routes work with internal numeric `id`.

### `POST /jobs/ingest`

Accepts either a single job object or an array of jobs.

Example payload:

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

Each ingest inserts only new jobs. If a row with the same `job_id` already exists, the service skips it and leaves the existing status and timestamps unchanged.

Response fields:

- `received` - number of payload items received
- `created` - number of new rows inserted
- `updated` - currently always `0`; retained for compatibility with the earlier upsert response shape
- `skipped` - number of duplicate `job_id` values ignored
- `jobs` - the created `job_id` values

### `GET /jobs`

Supported query parameters:

- `status`
- `source`
- `score`
- `role_type`
- `screening_likelihood`
- `scored_since`
- `limit`
- `offset`

Example:

```text
GET http://localhost:8000/jobs?status=new&limit=25
```

### `POST /jobs/{id}/score`

Stores scoring output for a single job identified by internal numeric `id`. This is now the legacy/manual writeback route; the preferred scoring path is the service-side `/jobs/{id}/score/run` or `/jobs/score/run` endpoints.

Example payload:

```json
{
  "score": 22,
  "recommendation": "apply",
  "justification": "Strong fit for the role",
  "strengths": ["B2B product experience", "roadmapping"],
  "gaps": ["No direct fintech background"],
  "missing_from_jd": ["SQL"],
  "role_type": "Product Manager",
  "screening_likelihood": 20,
  "dimension_scores": {
    "domain_fit": 4,
    "execution_ownership_fit": 5,
    "customer_discovery_fit": 3,
    "environment_fit": 4,
    "role_readiness": 4
  },
  "gating_flags": ["No major blockers"],
  "prompt_key": "product",
  "prompt_version": 3
}
```

If `scored_at` is omitted, the service uses the current UTC time. The response includes the current `status`, `score`, `scoring metadata`, `scored_at`, `notified_at`, and `error_at` values for that row.

Scoring writeback responses expose both legacy and new fields (`role_type`, `screening_likelihood`, `dimension_scores`, `gating_flags`) when present.

### `POST /jobs/scores`

Batch score writeback route. Each item must include numeric `id`.

### `POST /jobs/{id}/score/run`

Triggers scoring for a single job inside the service. The service resolves the active prompt, renders the prompt body, calls the configured LLM provider, validates the response, and persists either scored or error state.

Example payload:

```json
{
  "prompt_key": "product",
  "force": false
}
```

### `POST /jobs/score/run`

Queues a batch scoring run inside the service and returns immediately.

Example payload:

```json
{
  "limit": 25,
  "status": "new",
  "force": false,
  "callback_url": "https://example.com/scoring-complete"
}
```

The batch route is asynchronous. It creates a durable `score_run`, snapshots the selected job IDs into `score_run_items`, and returns a `run_id` plus current counts. A background worker processes those jobs independently of the HTTP connection.

Use `GET /score-runs/{run_id}` to poll progress and `GET /score-runs/{run_id}/items` to inspect per-job status.

If `callback_url` is supplied, the service will POST the final run payload to that URL after the run completes or fails.

Per-job scoring results are committed as each job finishes, so completed work survives later timeouts or client disconnects.

### `GET /score-runs/{run_id}`

Returns the current status and counters for a queued or completed batch scoring run.

### `GET /score-runs/{run_id}/items`

Returns one row per selected job with `queued`, `running`, `scored`, `error`, or `skipped` status.

### `POST /job/{id}/error`

Marks a job as error and sets `error_at`.

Example payload:

```json
{
  "status": "error"
}
```

If `error_at` is omitted, the service uses the current UTC time.

### `POST /jobs/{id}/notify`

Marks a job as notified and sets `notified_at`.

Example payload:

```json
{
  "status": "notified"
}
```

If `notified_at` is omitted, the service uses the current UTC time.

### `POST /jobs/notify`

Batch notification writeback route. Each item must include numeric `id`.

### Prompt library routes

Use the prompt-library endpoints to manage versioned prompt templates inside the service database rather than n8n Data Tables. The service-side scoring routes resolve active prompts from this table.

### `GET /jobs/hiringcafe`

This is a legacy route that launches Playwright, opens a Hiring Cafe search page, and captures `/api/search-jobs` responses while scrolling.

It is not the preferred ingest path. Browser-side capture through the Chrome extension is the current primary approach.
