# Automated Job Funnel

This repository combines a Chrome extension, a FastAPI service, and exported n8n workflows for collecting, scoring, and tracking job postings.

The current operational source of truth is `job-pipeline-service`, which stores jobs and prompt templates in a relational database. The Chrome extension is the primary ingestion path. The exported n8n workflows are sanitized templates that need environment-specific credentials and endpoints filled back in after import.

## Repo layout

- `job-pipeline-service/` - FastAPI API for job ingest, scoring writeback, notification writeback, and prompt library CRUD.
- `job-scraper-chrome/` - Chrome extension that scrapes LinkedIn job pages and captures Hiring Cafe search responses, then posts normalized jobs to the API.
- `exports/workflows/` - n8n workflow exports.
- `exports/data/` - example prompt-library seed data.
- `docs/` - architecture diagram and supporting docs.

## Current architecture

```text
LinkedIn job page or Hiring Cafe search page
    -> job-scraper-chrome
        -> POST /jobs/ingest
            -> job-pipeline-service
                -> SQLite by default, Postgres when DATABASE_URL is set
                    -> service-side scoring
                        -> active prompt from prompt_library
                        -> configured LLM provider
                        -> async score runs + optional callback
                        -> score/error persistence
                    -> n8n scoring workflow
                        -> POST /jobs/score/run
                    -> n8n notification workflow
                        -> tracker + email + notify writeback to API
```

## API overview

### Jobs

- `POST /jobs/ingest` - insert new jobs by external `job_id`; duplicate `job_id` values are skipped
- `GET /jobs` - list jobs with optional `status`, `source`, `score`, `scored_since`, `limit`, and `offset`
- `GET /jobs/{id}` - fetch a single job by internal numeric database ID
- `POST /jobs/{id}/score/run` - trigger service-side scoring for a single job
- `POST /jobs/score/run` - enqueue a batch service-side scoring run
- `GET /score-runs/{run_id}` - inspect async batch scoring progress
- `GET /score-runs/{run_id}/items` - inspect per-job scoring status for a run
- `POST /jobs/{id}/score` - write score fields by internal numeric database ID
- `POST /job/{id}/error` - mark a job as error and set `error_at`
- `POST /jobs/scores` - batch score writeback; each item must include numeric `id`
- `POST /jobs/{id}/notify` - mark a job as notified by internal numeric database ID
- `POST /jobs/notify` - batch notification writeback; each item must include numeric `id`
- `GET /jobs/hiringcafe` - legacy Playwright capture route for Hiring Cafe search responses

Scoring accepts both legacy and expanded JSON output shapes from the LLM. Old prompt fields continue to work unchanged, while optional new fields (`role_type`, `screening_likelihood`, `dimension_scores`, `gating_flags`) are persisted when present.

### Prompt library

- `GET /prompt-library`
- `GET /prompt-library/{prompt_id}`
- `POST /prompt-library`
- `PUT /prompt-library/{prompt_id}`
- `DELETE /prompt-library/{prompt_id}`

Prompts now live in the service database and are resolved at scoring time by `prompt_key` or `DEFAULT_PROMPT_KEY`.

## Data model

### `job_postings`

- `id` - internal integer primary key
- `job_id` - external unique identifier used for ingest dedupe
- `source`
- `status`
- `company_name`
- `title`
- `yearly_min_compensation`
- `yearly_max_compensation`
- `apply_url`
- `description`
- `raw_payload`
- `score`
- `recommendation`
- `justification`
- `strengths`
- `gaps`
- `missing_from_jd`
- `role_type`
- `screening_likelihood`
- `dimension_scores`
- `gating_flags`
- `prompt_key`
- `prompt_version`
- `score_provider`
- `score_model`
- `score_error`
- `score_raw_response`
- `score_attempts`
- `scored_at`
- `notified_at`
- `error_at`
- `created_at`
- `updated_at`

### `prompt_library`

- `id` - integer primary key
- `prompt_key`
- `prompt_version`
- `system_prompt`
- `user_prompt_template`
- `base_resume_template`
- `is_active`

`prompt_key` + `prompt_version` is unique.

## Local setup

### Option 1: Run the API directly

From `job-pipeline-service/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app:app --host 0.0.0.0 --port 8000
```

By default the service uses SQLite:

- `sqlite:///./jobs.db` if no `./data/jobs.db` exists
- `sqlite:///./data/jobs.db` if `job-pipeline-service/data/jobs.db` already exists

Set `DATABASE_URL` to use Postgres or another supported SQLAlchemy database.

Service-side scoring is configured with environment variables such as:

- `SCORING_PROVIDER` default `ollama`
- `SCORING_MODEL`
- `OLLAMA_BASE_URL`
- `OLLAMA_NUM_CTX`
- `LLM_TIMEOUT_SECONDS`
- `DEFAULT_PROMPT_KEY`

### Option 2: Run the API with the included compose example

There is no root `docker-compose.yml` in this repository. The included compose file lives at `job-pipeline-service/docker-compose-example.yml`.

From `job-pipeline-service/`:

```bash
docker compose -f docker-compose-example.yml up --build -d
```

This starts:

- `job-pipeline-service` on `http://localhost:8000`
- `postgres` on `localhost:5432`

The compose file sets `DATABASE_URL` to Postgres, so this path uses Postgres instead of SQLite.

### Verify the API

```bash
curl http://localhost:8000/health
```

## Chrome extension setup

The Chrome extension lives in `job-scraper-chrome/`.

1. Edit `POST_ENDPOINT` in `job-scraper-chrome/background.js` if your API is not `http://localhost:8000/jobs/ingest`.
2. Open `chrome://extensions`.
3. Enable Developer mode.
4. Load the `job-scraper-chrome/` folder as an unpacked extension.

Current behavior:

- On LinkedIn job pages, the extension auto-detects job detail pages, observes route and DOM changes, and posts normalized payloads in the background. The popup still supports a manual scrape/send trigger.
- On Hiring Cafe search pages, `page-hook.js` intercepts search API responses in the page context and `content.js` normalizes them into one or more ingest payloads, including company names from `v5_processed_job_data.company_name` when present.
- `background.js` always posts an array payload to `POST /jobs/ingest`.

## n8n workflow status

The repo includes these exports:

- `exports/workflows/Job Scoring.json`
- `exports/workflows/Job Notification.json`

These exports target the current API-backed flow, but they are checked in with placeholder hosts, credential IDs, recipient addresses, and external document IDs. Reconfigure those values in n8n after import.

If you import the workflows, review them before use and align their read/write steps with the current API behavior, especially the distinction between external `job_id` and internal numeric `id`. `Job Scoring.json` now acts as a thin trigger that calls `/jobs/score/run`, then polls `GET /score-runs/{run_id}` or receives a callback when scoring is complete. Prompt rendering, LLM calls, parsing, and score/error persistence happen inside the service. `Job Notification.json` reads recently scored jobs above a threshold, appends them to a tracker, emails a digest, and calls `/jobs/{id}/notify`.

## Prompt setup

Prompt templates are stored in the `prompt_library` table. The service uses the active prompt version for the requested `prompt_key`, or `DEFAULT_PROMPT_KEY` if a scoring call does not pass one.

The example seed file is `exports/data/prompt_library.seed.mock.json`. It is intentionally sanitized to show the prompt structure and customization points without exposing a production prompt.

### Load a prompt with the API

`POST /prompt-library` accepts one prompt object at a time, not an array.

To load the example seed file from the repo root in PowerShell:

```powershell
$seed = Get-Content .\exports\data\prompt_library.seed.mock.json | ConvertFrom-Json
foreach ($prompt in $seed) {
  $prompt | ConvertTo-Json -Depth 10 | curl.exe -X POST http://localhost:8000/prompt-library `
    -H "Content-Type: application/json" `
    --data-binary @-
}
```

Then verify:

```bash
curl http://localhost:8000/prompt-library
```

Example single prompt payload:

```json
{
  "prompt_key": "product",
  "prompt_version": 1,
  "system_prompt": "ROLE: ...",
  "user_prompt_template": "RESUME:\n<<<\n{{resume}}\n>>>\n\nJOB DESCRIPTION:\n<<<\n{{description}}\n>>>\n\nOUTPUT:\nReturn ONLY the JSON object matching the schema.",
  "base_resume_template": "FIRST LAST\n...",
  "is_active": true
}
```

### Use the prompt during scoring

- Set `DEFAULT_PROMPT_KEY=product` in the API environment, or
- pass `"prompt_key": "product"` in `POST /jobs/{id}/score/run` or `POST /jobs/score/run`

If you create a new prompt version for the same `prompt_key`, mark only one version `is_active=true` for predictable scoring behavior.

## Notes

- The legacy `GET /jobs/hiringcafe` Playwright route still exists in the service, but the preferred ingest path is the Chrome extension posting to `POST /jobs/ingest`.
- Prompt-library seeding is optional. Example seed data is in `exports/data/prompt_library.seed.mock.json`.
- The Docker image includes Playwright because the legacy Hiring Cafe endpoint is still present.

## License

MIT
