# Job Pipeline Service

FastAPI service for:

1. ingesting scraped jobs
2. storing jobs and scoring results in SQLite
3. exposing routes that n8n can use to fetch jobs to score and write scores back
4. keeping the legacy Hiring Cafe scrape route available

The Hiring Cafe route is still present, but Hiring Cafe bot detection currently makes it unreliable. The primary ingestion path should now be `POST /jobs/ingest` from `job-scraper-chrome`.

## Requirements

- Python 3.11+
- Docker Desktop (optional, recommended for deployment)

## Local Run

The service can run without Docker. By default it uses a local SQLite database file, so no separate database server is required.

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

Windows PowerShell:

```powershell
pip install -r requirements.txt
playwright install chromium
```

macOS / Linux:

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Start the API

Windows PowerShell:

```powershell
uvicorn app:app --host 0.0.0.0 --port 8000
```

macOS / Linux:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

### 4. Verify it is running

Windows PowerShell:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health"
```

macOS / Linux:

```bash
curl http://localhost:8000/health
```

### Notes

- The SQLite database will be created automatically as `jobs.db` in `job-pipeline-service/`.
- If you want the DB somewhere else, set `DATABASE_URL` before starting the server.
- If `playwright install chromium` fails, make sure Playwright is installed in the active virtual environment first.

## Docker Run

Build image:

```powershell
docker build -t jobscraper:latest .
```

Run container:

```powershell
docker run -d --name jobscraper -p 8000:8000 `
  jobscraper:latest
```

Persist the SQLite database:

```powershell
docker run -d --name jobscraper -p 8000:8000 `
  -v ${PWD}/data:/app `
  jobscraper:latest
```

View logs:

```powershell
docker logs -f jobscraper
```

Stop/remove:

```powershell
docker stop jobscraper
docker rm jobscraper
```

## Docker Compose

An example compose file is included at [docker-compose.example.yml](/home/lrw5016/projects/n8n-job-funnel/job-pipeline-service/docker-compose.example.yml).

Run it from `job-pipeline-service/`:

```powershell
docker compose -f docker-compose.example.yml up --build -d
```

Stop it:

```powershell
docker compose -f docker-compose.example.yml down
```

The compose example:

- builds the local `Dockerfile`
- exposes the API on `localhost:8000`
- persists SQLite data in `./data/jobs.db`
- sets `restart: unless-stopped`

## Database

- Default database: `sqlite:///./jobs.db`
- Override with `DATABASE_URL`
- Tables are created automatically on startup

## API

- `GET /health`
- `POST /jobs/ingest`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/score`
- `POST /jobs/scores`
- `POST /jobs/{job_id}/notify`
- `POST /jobs/notify`
- `GET /jobs/hiringcafe?search_url=<HIRING_CAFE_URL>`

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
  "source": "job-scraper-chrome"
}
```

Each ingest upserts by `job_id` and sets the job status to `new`.

### `GET /jobs`

Supported query parameters:

- `status`
- `source`
- `limit`
- `offset`

Example:

```text
GET http://localhost:8000/jobs?status=new&limit=25
```

### `POST /jobs/{job_id}/score`

Stores scoring output for a single job and updates the job's latest score fields.

Example payload:

```json
{
  "score": 22,
  "recommendation": "apply",
  "justification": "Strong fit for the role",
  "strengths": ["B2B product experience", "roadmapping"],
  "gaps": ["No direct fintech background"],
  "missing_from_jd": ["SQL"],
  "prompt_key": "product",
  "prompt_version": 3
}
```

### `POST /jobs/scores`

Batch version of the score writeback route. Each item must include `job_id`.

### `POST /jobs/{job_id}/notify`

Marks a job as notified and sets `notified_at`.

Example payload:

```json
{
  "status": "notified"
}
```

If `notified_at` is omitted, the service uses the current UTC time.

### `POST /jobs/notify`

Batch version of the notification writeback route. Each item must include `job_id`.

### Hiring Cafe query parameter

- `search_url` (required): URL opened by Playwright before capturing `/api/search-jobs`.

### Build the `search_url` from Hiring Cafe

1. Open `https://hiring.cafe/` in your browser.
2. Set your filters (role, location, compensation, remote, date range, etc.).
3. Copy the full URL from the browser address bar after filters are applied.
4. URL-encode that copied URL.
5. Pass the encoded value as `search_url` to this service.

Example:

```text
GET http://localhost:8000/jobs/hiringcafe?search_url=https%3A%2F%2Fhiring.cafe%2F%3FsearchState%3D...
```

Quick test:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health"
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/jobs/ingest" -ContentType "application/json" -Body '{"job_id":"linkedin_123","company_name":"Example Co","title":"PM","source":"job-scraper-chrome"}'
Invoke-RestMethod -Uri "http://localhost:8000/jobs?status=new"
```

## Response

- `POST /jobs/ingest`: returns counts of received, created, and updated jobs
- `GET /jobs`: returns stored jobs and the total count for the applied filters
- score routes: return the updated job IDs and current score state
- notify routes: mark jobs as notified and set `notified_at`
- Hiring Cafe route: returns raw JSON from `/api/search-jobs` when Playwright capture still works

## Troubleshooting

- If endpoint behavior seems old after code changes, rebuild the image and recreate the container:

```powershell
docker stop jobscraper
docker rm jobscraper
docker build -t jobscraper:latest .
docker run -d --name jobscraper -p 8000:8000 jobscraper:latest
```
