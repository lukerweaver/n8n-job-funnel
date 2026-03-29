# Job Pipeline Service

FastAPI service for:

1. ingesting normalized jobs from the Chrome extension
2. classifying job postings into reusable role buckets
3. generating and scoring user-owned job applications from matching resumes
4. exposing routes that n8n can use to automate classification, scoring, tailoring-adjacent workflow, and notification state
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

Tables are created automatically on startup. The current data model centers on:

- `job_postings` for ingested source jobs plus classification state
- `users` for application ownership
- `resumes` for user resumes aligned to a `classification_key`
- `job_applications` for resume-specific scoring and workflow lifecycle
- `interview_rounds` for variable interview tracking

In addition to those tables, the service persists async legacy job scoring state in `score_runs` and `score_run_items`. Those tables still back the older `/jobs/score/run` flow.

## LLM configuration

The service can classify jobs and score applications directly using a configured LLM provider.

Supported environment variables:

- `SCORING_PROVIDER` default `ollama`
- `SCORING_MODEL` default `qwen2.5:14b-instruct`
- `OLLAMA_BASE_URL` default `http://localhost:11434`
- `OLLAMA_NUM_CTX` default `50000`
- `LLM_TIMEOUT_SECONDS` default `180`
- `DEFAULT_PROMPT_KEY` optional

The current implementation supports `ollama` as the provider.

There are now two orchestration styles:

- preferred application-native flow:
  - classify postings with `/jobs/classify/run`
  - generate applications with `/applications/generate`
  - score applications with `/applications/score/run`
- legacy job-native flow:
  - queue batch scoring with `/jobs/score/run`

## Workflow

The intended automated workflow is:

1. ingest `JobPosting`
2. classify `JobPosting`
3. generate `JobApplication` rows when `JobPosting.classification_key == Resume.classification_key`
4. score `JobApplication`
5. tailor and notify from application thresholds
6. let the user drive `applied`, `screening`, `interview`, `offer`, `rejected`, or `withdrawn`

## Prompt library

Prompt templates are stored in the `prompt_library` table and resolved by `prompt_key` plus `prompt_type`.

Supported prompt types:

- `classification`
- `scoring`
- `tailoring`

Prompt resolution uses:

- the explicit `prompt_key` passed to a classify or score route, or
- `DEFAULT_PROMPT_KEY` if the request does not pass one

The repo includes a sanitized example seed at `exports/data/prompt_library.seed.mock.json`. It demonstrates the scoring schema and customization points without exposing a production prompt.

### Load prompts

`POST /prompt-library` accepts one prompt object at a time, not an array.

If you want to load the example seed file, post each item in the array individually. One simple PowerShell option from the repo root is:

```powershell
$seed = Get-Content .\exports\data\prompt_library.seed.mock.json | ConvertFrom-Json
foreach ($prompt in $seed) {
  $prompt | ConvertTo-Json -Depth 10 | curl.exe -X POST http://localhost:8000/prompt-library `
    -H "Content-Type: application/json" `
    --data-binary @-
}
```

You can verify loaded prompts with:

```bash
curl http://localhost:8000/prompt-library
```

If you create multiple versions for the same `prompt_key` and `prompt_type`, keep only one version active unless you intentionally want callers to target a specific prompt version.

Prompt write payloads now use prompt-only fields. Resume source text belongs on `resumes`, not in `prompt_library`.

Example prompt payload:

```json
{
  "prompt_key": "Product Manager",
  "prompt_type": "scoring",
  "prompt_version": 1,
  "system_prompt": "You are a hiring assistant...",
  "user_prompt_template": "{{resume}}\n\n{{description}}",
  "context": "Optional shared instructions",
  "max_tokens": 1500,
  "temperature": 0.2,
  "is_active": true
}
```

### Scoring payload schema

The scoring parser accepts both legacy and updated LLM JSON outputs.

- Legacy supported fields: `total_score`, `recommendation`, `justification`, `strengths`, `gaps`, `missing_from_jd`.
- New optional fields:
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

## Testing and coverage

From `job-pipeline-service/`:

Run tests:

```bash
pytest
```

Run tests with coverage reports:

```bash
pytest \
  --cov=app \
  --cov=services.scoring_service \
  --cov=services.scoring_parser \
  --cov=services.llm_client \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=json
```

Coverage policy target:

- line coverage: at least 80%
- branch coverage: at least 80%

Current coverage enforcement scope is the core scoring/service modules plus `app.py`. Expand this scope as additional modules gain stable test coverage.

If you generated `coverage.json`, you can enforce the branch threshold locally:

```bash
python scripts/coverage_gate.py coverage.json 80
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
- `POST /jobs/{id}/classify/run`
- `POST /jobs/classify/run`
- `GET /applications`
- `GET /applications/{id}`
- `POST /applications`
- `POST /applications/generate`
- `POST /applications/{id}/score`
- `POST /applications/{id}/score/run`
- `POST /applications/score/run`
- `POST /applications/{id}/notify`
- `POST /applications/{id}/error`
- `POST /applications/{id}/status`
- `GET /applications/{id}/interview-rounds`
- `POST /applications/{id}/interview-rounds`
- `GET /users`
- `POST /users`
- `GET /resumes`
- `POST /resumes`
- `PUT /resumes/{id}`
- `GET /prompt-library`
- `GET /prompt-library/{prompt_id}`
- `POST /prompt-library`
- `PUT /prompt-library/{prompt_id}`
- `DELETE /prompt-library/{prompt_id}`
- `POST /jobs/{id}/score/run`
- `POST /jobs/score/run`
- `GET /score-runs/{run_id}`
- `GET /score-runs/{run_id}/items`
- `POST /jobs/{id}/score`
- `POST /job/{id}/error`
- `POST /jobs/scores`
- `POST /jobs/{id}/notify`
- `POST /jobs/notify`
- `GET /jobs/hiringcafe?search_url=<HIRING_CAFE_URL>`

### ID semantics

The service uses two job identifiers:

- `job_id` - external string identifier used for ingest dedupe
- `id` - internal numeric database primary key used by `GET /jobs/{id}`, score routes, and notify routes

That distinction matters for n8n integrations. Ingest works with external `job_id`, while classify, score, and notify routes work with internal numeric IDs.

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

### Preferred n8n sequence

The preferred automation chain is:

1. classify jobs:

```json
POST /jobs/classify/run
{
  "limit": 100,
  "force": false
}
```

2. generate applications for classified postings:

```json
POST /applications/generate
{
  "job_posting_id": 123
}
```

3. score applications in batch:

```json
POST /applications/score/run
{
  "limit": 100,
  "status": "new",
  "force": false
}
```

4. fetch high-scoring applications:

```text
GET /applications?status=scored&score=20
```

5. mark notified applications:

```json
POST /applications/{id}/notify
{
  "status": "notified"
}
```

### `POST /jobs/{id}/classify/run`

Classifies a single posting and writes the result to `job_postings.classification_key`.

Example payload:

```json
{
  "prompt_key": "Product Manager",
  "force": false
}
```

### `POST /jobs/classify/run`

Runs batch classification across postings.

Example payload:

```json
{
  "limit": 100,
  "source": "linkedin",
  "force": false
}
```

### `POST /applications/generate`

Creates `job_applications` for resumes whose `classification_key` matches the posting classification.

Example payload:

```json
{
  "job_posting_id": 123
}
```

### `GET /applications`

Supported query parameters:

- `user_id`
- `resume_id`
- `job_posting_id`
- `status`
- `score`
- `limit`
- `offset`

### `POST /applications/score/run`

Scores application rows in batch.

Example payload:

```json
{
  "limit": 100,
  "status": "new",
  "force": false
}
```

### `POST /applications/{id}/status`

Updates the application lifecycle status. Use this for `applied`, `screening`, `interview`, `offer`, `rejected`, and `withdrawn`.

Example payload:

```json
{
  "status": "applied"
}
```

### `POST /applications/{id}/interview-rounds`

Adds a numbered interview round for an application.

Example payload:

```json
{
  "round_number": 1,
  "stage_name": "Hiring Manager",
  "status": "scheduled"
}
```

### `POST /jobs/{id}/score`

Stores scoring output for a single job identified by internal numeric `id`. This is a legacy/manual writeback route retained for compatibility.

Example payload:

```json
{
  "score": 22,
  "recommendation": "apply",
  "justification": "Strong fit for the role",
  "strengths": ["B2B product experience", "roadmapping"],
  "gaps": ["No direct fintech background"],
  "missing_from_jd": ["SQL"],
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

Scoring writeback responses expose legacy fields such as `role_type`, `screening_likelihood`, `dimension_scores`, and `gating_flags` when present.

### `POST /jobs/scores`

Batch score writeback route. Each item must include numeric `id`.

### Legacy scoring routes

`POST /jobs/{id}/score/run`, `POST /jobs/score/run`, `GET /score-runs/{run_id}`, and `GET /score-runs/{run_id}/items` are still available for backward compatibility while older n8n flows are being retired.

### Legacy notify/error routes

`POST /job/{id}/error`, `POST /jobs/{id}/notify`, and `POST /jobs/notify` are also retained for backward compatibility with older job-based automation.

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
