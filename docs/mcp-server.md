# Job Funnel MCP Server

Job Funnel can be exposed to agent clients through a small Model Context Protocol
server that wraps the existing FastAPI service. The MCP server is intentionally
API-first: it calls HTTP routes and never edits the database directly.

## Scope

Phase 1 is read-only. It supports:

- `health_check`
- `get_settings`
- `list_applications`
- `get_application`
- `get_application_apply_url`
- `find_applications_for_email_signal`
- `list_runs`
- `get_run`
- `list_run_items`
- `list_run_applications`

`find_applications_for_email_signal` is designed for workflows where another
agent tool, such as Gmail, finds an application-related email and needs candidate
Job Funnel records. It does not update statuses.

## Setup

From `job-pipeline-service/`:

```powershell
pip install -r requirements.txt
$env:JOB_FUNNEL_API_BASE = "http://localhost:8000"
python mcp_server.py
```

The API base defaults to `http://localhost:8000` when `JOB_FUNNEL_API_BASE` is
not set. If your API is running on another host, set `JOB_FUNNEL_API_BASE` to
that URL in your local MCP client configuration.

## Claude Desktop Example

Use an absolute path and keep logs off stdout because stdio MCP uses stdout for
JSON-RPC messages.

```json
{
  "mcpServers": {
    "job-funnel": {
      "command": "python",
      "args": [
        "C:/path/to/n8n-job-funnel/job-pipeline-service/mcp_server.py"
      ],
      "env": {
        "JOB_FUNNEL_API_BASE": "http://localhost:8000"
      }
    }
  }
}
```

## Guardrails

- Use MCP tools or FastAPI routes only; do not edit the database directly.
- Keep list responses compact by default. Full job descriptions are available
  through `get_application` or by explicitly requesting descriptions.
- Treat email-derived matches as candidates unless exactly one record is found.
- Add write tools separately, with explicit approval semantics, after the
  read-only MCP server has been validated.
