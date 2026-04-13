# Agent CLI Playbook

Use this guide when operating Job Funnel from an agent CLI such as Codex, Claude Code, or another terminal-based assistant.

The safest pattern is API-first: call the FastAPI service on `http://localhost:8000`, avoid direct database edits, and ask before bulk actions that change application state or send notifications.

## Tool Entry Points

Codex:

- Read `AGENTS.md` for repo-wide operating rules.
- Use this playbook for HTTP API workflows.
- Prefer the read-only review flow unless the user explicitly asks for writes.
- A portable Codex skill is included at `.codex/skills/job-funnel-operator/SKILL.md`. If your Codex install does not auto-discover repo-local skills, copy or symlink that folder into your personal Codex skills directory.

Claude Code:

- Project skills live under `.claude/skills/`.
- Invoke `/job-funnel-review` for read-only application summaries.
- Invoke `/job-funnel-ingest` to add pasted or normalized jobs.
- Invoke `/job-funnel-process` to run classification, application generation, and scoring.
- Invoke `/job-funnel-status` to update application status, lifecycle notes, or interview rounds.
- The write-oriented skills are intentionally manual-invocation workflows.

## Operator Rules

- Start with `GET /health`.
- Prefer read-only requests until the user explicitly asks to ingest, classify, score, or update records.
- Use API routes instead of editing the database.
- Ask before changing application status, lifecycle dates, notification state, prompts, provider settings, or automation settings.
- For external orchestration, set `automation_settings.auto_process_jobs` to `false` so the service worker and the agent do not both own the same run sequence.
- Poll `/runs/{run_id}` before launching the next dependent step.

## Agent Prompt Templates

Read-only review:

```text
You are operating my local Job Funnel at http://localhost:8000.
Use the API only. Start with GET /health.
List recent applications and summarize the strongest opportunities.
Do not change statuses, score jobs, notify anyone, or edit settings unless I explicitly approve that action.
```

Process new jobs:

```text
You are operating my local Job Funnel at http://localhost:8000.
Use the API only. Start with GET /health and GET /settings.
If auto_process_jobs is false, you may queue classification, wait for it to complete, generate applications, and queue scoring.
Ask before changing application statuses or notification state.
```

Ingest a job:

```text
You are operating my local Job Funnel at http://localhost:8000.
Use POST /jobs/ingest for normalized jobs or POST /jobs/paste for pasted descriptions.
After ingest, report the created/skipped count and do not queue processing unless I ask.
```

## PowerShell Setup

Use a single API base variable:

```powershell
$Api = "http://localhost:8000"
```

Check health:

```powershell
Invoke-RestMethod "$Api/health"
```

Read settings:

```powershell
Invoke-RestMethod "$Api/settings"
```

Disable service-managed automation for an agent-owned run sequence:

```powershell
$body = @{
  automation_settings = @{
    auto_process_jobs = $false
    opportunistic_trigger_enabled = $true
    resume_strategy = "default_fallback"
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod "$Api/settings" -Method Put -ContentType "application/json" -Body $body
```

Use `auto_process_jobs = $true` when the backend service should own automatic classification and scoring.

## Read-Only Review Workflow

List recent applications:

```powershell
Invoke-RestMethod "$Api/applications?limit=25&offset=0"
```

List active applications:

```powershell
Invoke-RestMethod "$Api/applications?status_group=active&limit=25&offset=0"
```

Filter by target role:

```powershell
$role = [uri]::EscapeDataString("Product Manager")
Invoke-RestMethod "$Api/applications?classification_key=$role&limit=25&offset=0"
```

Fetch one application:

```powershell
Invoke-RestMethod "$Api/applications/123"
```

## Ingest Workflow

Send one normalized job:

```powershell
$job = @{
  job_id = "manual_2026_04_13_example"
  company_name = "Example Co"
  title = "Product Manager"
  yearly_min_compensation = 150000
  yearly_max_compensation = 180000
  apply_url = "https://example.com/jobs/123"
  description = "Full job description"
  source = "agent_cli"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod "$Api/jobs/ingest" -Method Post -ContentType "application/json" -Body $job
```

Send multiple normalized jobs:

```powershell
$jobs = @(
  @{
    job_id = "agent_cli_1"
    company_name = "Example Co"
    title = "Product Manager"
    description = "Full job description"
    source = "agent_cli"
  },
  @{
    job_id = "agent_cli_2"
    company_name = "Example Labs"
    title = "Product Owner"
    description = "Full job description"
    source = "agent_cli"
  }
) | ConvertTo-Json -Depth 5

Invoke-RestMethod "$Api/jobs/ingest" -Method Post -ContentType "application/json" -Body $jobs
```

Paste a job and queue processing immediately:

```powershell
$paste = @{
  description = "Full job description"
  url = "https://example.com/jobs/123"
  company_name = "Example Co"
  title = "Product Manager"
  process_now = $true
  mode = "async"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod "$Api/jobs/paste" -Method Post -ContentType "application/json" -Body $paste
```

## Agent-Owned Processing Workflow

Queue classification:

```powershell
$classification = @{
  limit = 100
  source = $null
  classification_key = $null
  force = $false
} | ConvertTo-Json -Depth 5

$classificationRun = Invoke-RestMethod "$Api/jobs/classify/run" -Method Post -ContentType "application/json" -Body $classification
$classificationRun
```

Poll the run:

```powershell
$runId = $classificationRun.run_id
Invoke-RestMethod "$Api/runs/$runId"
Invoke-RestMethod "$Api/runs/$runId/items?limit=100&offset=0"
```

Generate missing applications after classification completes:

```powershell
$generate = @{
  user_id = 1
  limit = 100
  resume_strategy = "default_fallback"
} | ConvertTo-Json -Depth 5

$generateRun = Invoke-RestMethod "$Api/applications/generate/run" -Method Post -ContentType "application/json" -Body $generate
$generateRun
```

Queue scoring:

```powershell
$score = @{
  limit = 100
  status = "new"
  force = $false
  refresh_resume_match = $true
} | ConvertTo-Json -Depth 5

$scoreRun = Invoke-RestMethod "$Api/applications/score/run" -Method Post -ContentType "application/json" -Body $score
$scoreRun
```

Poll scoring results:

```powershell
$scoreRunId = $scoreRun.run_id
Invoke-RestMethod "$Api/runs/$scoreRunId"
Invoke-RestMethod "$Api/runs/$scoreRunId/applications?limit=100&offset=0"
```

## Status Updates

Ask before using these routes. They change the operator record.

Update application status:

```powershell
$status = @{
  status = "applied"
  applied_at = "2026-04-13T09:00:00"
  applied_notes = "Applied from agent-assisted review."
} | ConvertTo-Json -Depth 5

Invoke-RestMethod "$Api/applications/123/status" -Method Post -ContentType "application/json" -Body $status
```

Add an interview round:

```powershell
$round = @{
  round_number = 1
  stage_name = "Recruiter screen"
  status = "scheduled"
  scheduled_at = "2026-04-15T13:00:00"
  notes = "Scheduled after application review."
} | ConvertTo-Json -Depth 5

Invoke-RestMethod "$Api/applications/123/interview-rounds" -Method Post -ContentType "application/json" -Body $round
```

## Failure Handling

- If `/health` fails, stop and ask the user to start the API.
- If a run returns `errored` items, fetch `/runs/{run_id}/items` and summarize the errors before retrying.
- If scoring fails with provider configuration errors, fetch `/settings` and report the provider mode/model fields without exposing API keys.
- If no jobs are selected for a run, report that there was no eligible work instead of forcing reprocessing.
