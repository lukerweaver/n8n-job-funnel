# Job Funnel MCP Server

Job Funnel can be exposed to agent clients through a small Model Context Protocol
server that wraps the existing FastAPI service. The MCP server is intentionally
API-first: it calls HTTP routes and never edits the database directly.

## Scope

Phase 1 read-only tools:

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

Phase 2 guarded write tools:

- `ingest_job`
- `paste_job`
- `queue_classification_run`
- `queue_application_generation_run`
- `queue_scoring_run`
- `mark_application_status`
- `mark_application_rejected_from_email`
- `add_interview_round`

Phase 3 workflow affordances:

- Resources:
  - `job-funnel://settings`
  - `job-funnel://target-roles`
  - `job-funnel://scoring-preferences`
  - `job-funnel://agent-playbook`
  - `job-funnel://applications/{application_id}`
  - `job-funnel://runs/{run_id}`
- Prompts:
  - `review_strong_applications`
  - `investigate_rejection_email`
  - `prepare_application_review`
- Tools:
  - `prepare_application_assist`

`find_applications_for_email_signal` is designed for workflows where another
agent tool, such as Gmail, finds an application-related email and needs candidate
Job Funnel records. It searches multiple hints, scores candidates, and returns
confidence reasons.

`mark_application_rejected_from_email` is the paired status update helper for
that workflow. It requires an explicit `application_id`, email evidence fields,
and `confirm_write=true`.

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
- Write tools require `confirm_write=true`.
- Tools that accept `force=true` also require `confirm_force=true`.
- Agent-owned processing tools check `automation_settings.auto_process_jobs`.
  If service-managed automation is enabled, they return a blocked response
  unless `acknowledge_service_automation=true` is supplied.
- `paste_job` defaults to `process_now=false`.
- Status update tools require notes. `mark_application_rejected_from_email`
  stores a concise evidence note with sender, subject, and received timestamp.
- Provider settings, prompt-library writes, notification sends, and database
  access are intentionally not exposed by this MCP server.
- Browser/application-assist workflows must keep final submission as a human
  action. `prepare_application_assist` returns explicit human-gate rules for
  sponsorship, salary, demographic, legal, disability, veteran, relocation, and
  final-submit fields.

## Rejection Email Workflow

When an agent with Gmail access sees a rejection email:

1. Call `find_applications_for_email_signal` with company/title/email-derived
   search terms and email metadata.
2. If multiple candidates are returned, ask the user to choose the application.
3. Call `mark_application_rejected_from_email` with the chosen `application_id`,
   `email_from`, `email_subject`, `email_received_at`, optional notes, and
   `confirm_write=true`.

Do not store full email bodies unless the user explicitly asks for that in a
future workflow.

## Application Assist Workflow

When an agent has access to a browser connector such as Playwright:

1. Call `prepare_application_assist(application_id)`.
2. Open the returned `apply_url` in the approved browser context.
3. Fill only low-risk factual fields from user-provided profile or resume
   context.
4. Ask the user before answering human-gated fields or uploading documents.
5. Stop before final submission and let the user submit.
6. After the user confirms submission, call `mark_application_status` with
   `status="applied"`, an evidence note, and `confirm_write=true`.
