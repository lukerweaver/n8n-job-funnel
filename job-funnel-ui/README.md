# Job Funnel UI

Internal React/Vite UI for the job funnel backend.

Current operator pages:

- `/paste-job` - manual job description entry with optional job URL, recommendation polling, and detail modal
- `/applications` - All Applications table with detail modal
- `/active-applications` - active lifecycle states, including ghosted follow-ups, with interview visibility
- `/historical-applications` - applied, active, and terminal-state review
- `/runs` - run history table plus launch actions for classification and scoring runs
- `/runs/:runId` - run results view backed by joined run/application rows
- `/statistics` - ingest trend table/chart and scored-job distribution
- `/resumes` - resume inventory with modal-based create/edit flows
- `/prompts` - prompt library table with modal-based create/edit flows
- `/settings` - provider, prompt, automation, resume strategy, and n8n handoff settings

## Requirements

- Node 18+
- a running FastAPI backend from [`job-pipeline-service/`](../job-pipeline-service/)

## Local Run

From `job-funnel-ui/`:

```bash
npm install
npm run dev
```

Default API target:

- `http://localhost:8000`

Override it with:

```bash
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

The value used by the UI must be browser-visible. For example:

- local API: `http://localhost:8000`
- deployed API: `https://api.example.com`

## Production Build

```bash
npm run build
```

## Standalone Container Deploy

Build the image:

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

Container behavior:

- serves the SPA with Nginx on port `80`
- injects `API_BASE_URL` at container startup into `/runtime-config.js`
- supports client-side routing fallback to `index.html`
- exposes a simple health endpoint at `/healthz`

If your API is public HTTPS, set:

```bash
-e API_BASE_URL=https://api.example.com
```

If your API is on the same machine for local testing, use:

```bash
-e API_BASE_URL=http://localhost:8000
```

## Full Stack Compose

From the repository root:

```bash
docker compose -f docker-compose-example.yml up --build -d
```

That starts:

- the UI on `http://localhost:8080`
- the API on `http://localhost:8000`
- Postgres on `localhost:5432`

In the compose template, the UI container uses:

```bash
API_BASE_URL=http://localhost:8000
```

That is correct for local browser access to the published API port. If you deploy behind a hostname or reverse proxy, change `API_BASE_URL` to the browser-visible API URL.

## Current UX Patterns

- The UI is intentionally server-driven and reads directly from FastAPI list and action endpoints.
- Filter state is stored in the URL query string so refresh and navigation preserve the current view.
- Primary list pages follow the pattern `filters -> dense table -> modal detail`.
- Paste Job is the manual job-entry path. It asks for a job description, with job URL, company, and role as optional context.
- The Runs page can queue classification and scoring runs directly from the UI.
- The Statistics page combines lightweight charts with tables rather than a dashboard-card layout.

## Workflow Settings

Settings exposes the automatic processing controls:

- `Auto-process saved jobs`: when on, the backend worker can queue classification, generate applications with the configured resume strategy, and queue scoring.
- When `Auto-process saved jobs` is off, the backend still exposes the same run endpoints, but n8n or another orchestrator owns the sequence.

The resume strategy options are:

- `Default fallback`
- `Classification first`
- `Default only`

## What the UX Service Does

The `job-funnel-ui` container:

- serves static frontend assets with Nginx
- injects runtime config through `/runtime-config.js`
- supports SPA route fallback to `index.html`
- exposes `GET /healthz` for container-level health checks

The UX service does not proxy the API. It talks directly to the backend URL configured in `API_BASE_URL`.

## Notes

- The UX service does not proxy the API; it talks directly to the configured backend URL.
- `API_BASE_URL` must be reachable from the browser, not just from inside Docker.
