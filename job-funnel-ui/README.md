# Job Funnel UI

Internal React/Vite UI for the job funnel backend.

Current MVP pages:

- `/applications` - scored application review table plus detail drawer
- `/runs` - run history table
- `/runs/:runId` - run results view backed by joined run/application rows

## Requirements

- Node 18+
- running FastAPI backend from `job-pipeline-service/`

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

## Production Build

```bash
npm run build
```

## Container Deploy

Build the image:

```bash
docker build -t job-funnel-ui:latest .
```

Run it:

```bash
docker run -d \
  --name job-funnel-ui \
  -p 8080:80 \
  -e API_BASE_URL=http://your-api-host:8000 \
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

## Notes

- The UI is intentionally server-driven and reads directly from the list endpoints.
- Filtering and sorting are expressed through URL query params so page state survives refresh and navigation.
