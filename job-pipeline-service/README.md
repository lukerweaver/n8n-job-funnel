# Job Scraper Service

Lightweight FastAPI service that uses Playwright to fetch job-search JSON from Hiring Cafe.

Current flow:
1. Client (for example n8n) calls a GET endpoint.
2. Service opens Hiring Cafe with Playwright.
3. Service captures the `/api/search-jobs` response.
4. Service returns that JSON payload.

## Requirements

- Python 3.11+
- Docker Desktop (optional, recommended for deployment)

## Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
uvicorn app:app --host 0.0.0.0 --port 8000
```

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

View logs:

```powershell
docker logs -f jobscraper
```

Stop/remove:

```powershell
docker stop jobscraper
docker rm jobscraper
```

## API

- `GET /health`
- `GET /jobs/hiringcafe?search_url=<HIRING_CAFE_URL>`

### Query Parameter

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
Invoke-RestMethod -Uri "http://localhost:8000/jobs/hiringcafe?search_url=https%3A%2F%2Fhiring.cafe%2F%3FsearchState%3D..."
```

## Response

- Success: raw JSON from Hiring Cafe `/api/search-jobs`
- Failure: `504` with error details if the expected API response is not captured in time

## Troubleshooting

- If endpoint behavior seems old after code changes, rebuild the image and recreate the container:

```powershell
docker stop jobscraper
docker rm jobscraper
docker build -t jobscraper:latest .
docker run -d --name jobscraper -p 8000:8000 jobscraper:latest
```
