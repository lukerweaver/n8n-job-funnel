import json
import logging
import os
import sys
from typing import Any
from urllib.parse import urljoin

import httpx

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only before dependencies are installed
    FastMCP = None


DEFAULT_API_BASE = "http://localhost:8000"
API_BASE_ENV = "JOB_FUNNEL_API_BASE"
DESCRIPTION_PREVIEW_CHARS = 500
ACTIVE_STATUSES = {"applied", "ghosted", "screening", "interview"}
TERMINAL_STATUSES = {"offer", "rejected", "withdrawn", "pass"}
HUMAN_GATED_APPLICATION_FIELDS = [
    "sponsorship",
    "work authorization",
    "salary expectations",
    "relocation",
    "demographic questions",
    "disability status",
    "veteran status",
    "legal attestations",
    "final submission",
]

logger = logging.getLogger("job_funnel_mcp")
logging.getLogger("httpx").setLevel(logging.WARNING)
mcp = FastMCP("job-funnel") if FastMCP is not None else None


class JobFunnelApiError(RuntimeError):
    pass


class JobFunnelSafetyError(RuntimeError):
    pass


def _tool(*args: Any, **kwargs: Any):
    if mcp is None:
        def decorator(func):
            return func

        return decorator
    return mcp.tool(*args, **kwargs)


def _resource(*args: Any, **kwargs: Any):
    if mcp is None:
        def decorator(func):
            return func

        return decorator
    return mcp.resource(*args, **kwargs)


def _prompt(*args: Any, **kwargs: Any):
    if mcp is None:
        def decorator(func):
            return func

        return decorator
    return mcp.prompt(*args, **kwargs)


def api_base_url() -> str:
    return os.environ.get(API_BASE_ENV, DEFAULT_API_BASE).rstrip("/")


def api_url(path: str) -> str:
    return urljoin(f"{api_base_url()}/", path.lstrip("/"))


def compact_application(application: dict[str, Any], include_description: bool = False) -> dict[str, Any]:
    result = {
        "id": application.get("id"),
        "user_id": application.get("user_id"),
        "job_posting_id": application.get("job_posting_id"),
        "resume_id": application.get("resume_id"),
        "job_id": application.get("job_id"),
        "source": application.get("source"),
        "company_name": application.get("company_name"),
        "title": application.get("title"),
        "apply_url": application.get("apply_url"),
        "classification_key": application.get("classification_key"),
        "resume_name": application.get("resume_name"),
        "status": application.get("status"),
        "score": application.get("score"),
        "recommendation": application.get("recommendation"),
        "justification": application.get("justification"),
        "screening_likelihood": application.get("screening_likelihood"),
        "gating_flags": application.get("gating_flags"),
        "strengths": application.get("strengths"),
        "gaps": application.get("gaps"),
        "missing_from_jd": application.get("missing_from_jd"),
        "score_error": application.get("score_error"),
        "scored_at": application.get("scored_at"),
        "notified_at": application.get("notified_at"),
        "applied_at": application.get("applied_at"),
        "screening_at": application.get("screening_at"),
        "offer_at": application.get("offer_at"),
        "rejected_at": application.get("rejected_at"),
        "ghosted_at": application.get("ghosted_at"),
        "withdrawn_at": application.get("withdrawn_at"),
        "passed_at": application.get("passed_at"),
        "next_interview_at": application.get("next_interview_at"),
        "next_interview_stage": application.get("next_interview_stage"),
        "interview_rounds_total": application.get("interview_rounds_total"),
        "created_at": application.get("created_at"),
        "updated_at": application.get("updated_at"),
    }
    description = application.get("description")
    if include_description:
        result["description"] = description
    elif description:
        result["description_preview"] = description[:DESCRIPTION_PREVIEW_CHARS]
        result["description_truncated"] = len(description) > DESCRIPTION_PREVIEW_CHARS
    return result


def compact_application_list(response: dict[str, Any], include_descriptions: bool = False) -> dict[str, Any]:
    return {
        "total": response.get("total", 0),
        "items": [
            compact_application(item, include_description=include_descriptions)
            for item in response.get("items", [])
        ],
    }


def build_query(**kwargs: Any) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if value is not None}


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").lower().replace("-", " ").replace("_", " ").split())


def extract_email_domain(email_or_sender: str | None) -> str | None:
    if not email_or_sender or "@" not in email_or_sender:
        return None
    domain = email_or_sender.split("@", 1)[1].split(">", 1)[0].strip().lower()
    return domain or None


def public_domain_name(domain: str | None) -> str | None:
    if not domain:
        return None
    parts = [part for part in domain.lower().split(".") if part]
    if len(parts) < 2:
        return domain
    return parts[-2]


def json_resource(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


async def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(api_url(path), params=params)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise JobFunnelApiError(
            f"Job Funnel API GET {path} failed with status {response.status_code}: {response.text}"
        ) from exc
    return response.json()


async def api_post(path: str, payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(api_url(path), json=payload)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise JobFunnelApiError(
            f"Job Funnel API POST {path} failed with status {response.status_code}: {response.text}"
        ) from exc
    return response.json()


def require_write_confirmation(action: str, confirm_write: bool) -> None:
    if not confirm_write:
        raise JobFunnelSafetyError(f"{action} changes Job Funnel data. Pass confirm_write=true to proceed.")


def require_force_confirmation(force: bool, confirm_force: bool) -> None:
    if force and not confirm_force:
        raise JobFunnelSafetyError("force=true can reprocess existing work. Pass confirm_force=true to proceed.")


async def check_agent_processing_guard(acknowledge_service_automation: bool) -> dict[str, Any] | None:
    settings = await get_settings()
    automation_settings = settings.get("automation_settings") or {}
    auto_process_jobs = automation_settings.get("auto_process_jobs")
    if auto_process_jobs is True and not acknowledge_service_automation:
        return {
            "blocked": True,
            "reason": "automation_settings.auto_process_jobs is true; service-managed automation may compete with an agent-owned run sequence.",
            "required_action": "Set auto_process_jobs=false through the Job Funnel UI/API, or pass acknowledge_service_automation=true if this run is intentional.",
            "automation_settings": automation_settings,
        }
    return None


def compact_run_response(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": response.get("run_id"),
        "type": response.get("type"),
        "status": response.get("status"),
        "selected": response.get("selected"),
        "processed": response.get("processed"),
        "created": response.get("created"),
        "classified": response.get("classified"),
        "scored": response.get("scored"),
        "errored": response.get("errored"),
        "skipped": response.get("skipped"),
        "jobs": response.get("jobs"),
        "applications": response.get("applications"),
        "callback_url": response.get("callback_url"),
        "created_at": response.get("created_at"),
        "started_at": response.get("started_at"),
        "finished_at": response.get("finished_at"),
        "last_error": response.get("last_error"),
    }


def score_email_candidate(
    application: dict[str, Any],
    company_name: str | None = None,
    title: str | None = None,
    email_from: str | None = None,
    email_subject: str | None = None,
    email_received_at: str | None = None,
) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    company = normalize_text(application.get("company_name"))
    app_title = normalize_text(application.get("title"))
    company_hint = normalize_text(company_name)
    title_hint = normalize_text(title)
    subject = normalize_text(email_subject)
    sender_domain = extract_email_domain(email_from)
    sender_org = normalize_text(public_domain_name(sender_domain))
    status = application.get("status")

    if company_hint and company_hint in company:
        score += 0.35
        reasons.append("company hint matched company name")
    if sender_org and sender_org in company:
        score += 0.25
        reasons.append("email sender domain appears to match company name")
    if title_hint and title_hint in app_title:
        score += 0.25
        reasons.append("title hint matched application title")
    if subject and app_title and any(token for token in app_title.split() if len(token) >= 5 and token in subject):
        score += 0.15
        reasons.append("email subject overlaps application title")
    if status in ACTIVE_STATUSES:
        score += 0.15
        reasons.append("application is active")
    elif status in TERMINAL_STATUSES:
        score -= 0.2
        reasons.append("application is already terminal")
    if email_received_at and application.get("applied_at"):
        if str(application["applied_at"]) <= email_received_at:
            score += 0.1
            reasons.append("application applied timestamp is before email timestamp")
    if application.get("rejected_at") is None:
        score += 0.05
        reasons.append("application is not already marked rejected")

    confidence = max(0.0, min(0.99, round(score, 2)))
    return {
        "application": application,
        "confidence": confidence,
        "reasons": reasons,
    }


async def collect_email_signal_candidates(
    company_name: str | None = None,
    title: str | None = None,
    q: str | None = None,
    email_from: str | None = None,
    email_subject: str | None = None,
    email_received_at: str | None = None,
    status_group: str | None = None,
    created_since: str | None = None,
    updated_since: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    search_values = [
        " ".join(term for term in (q, company_name, title) if term),
        company_name,
        title,
        public_domain_name(extract_email_domain(email_from)),
    ]
    seen: dict[int, dict[str, Any]] = {}
    for search_value in search_values:
        if not search_value:
            continue
        response = await list_applications(
            q=search_value,
            status_group=status_group,
            created_since=created_since,
            updated_since=updated_since,
            sort_by="updated_at",
            sort_order="desc",
            limit=limit,
            include_descriptions=False,
        )
        for item in response.get("items", []):
            application_id = item.get("id")
            if application_id is not None:
                seen[application_id] = item

    candidates = [
        score_email_candidate(
            application,
            company_name=company_name,
            title=title,
            email_from=email_from,
            email_subject=email_subject,
            email_received_at=email_received_at,
        )
        for application in seen.values()
    ]
    candidates.sort(key=lambda item: (item["confidence"], item["application"].get("updated_at") or ""), reverse=True)
    candidates = candidates[:limit]
    strong_matches = [item for item in candidates if item["confidence"] >= 0.75]
    return {
        "matched_by": {
            "company_name": company_name,
            "title": title,
            "q": q,
            "email_from": email_from,
            "email_subject": email_subject,
            "email_received_at": email_received_at,
            "status_group": status_group,
            "created_since": created_since,
            "updated_since": updated_since,
        },
        "requires_human_selection": len(strong_matches) != 1,
        "total": len(candidates),
        "candidates": candidates,
        "items": [item["application"] for item in candidates],
    }


@_tool()
async def health_check() -> dict[str, Any]:
    """Check whether the Job Funnel API is reachable."""
    return await api_get("/health")


@_tool()
async def get_settings() -> dict[str, Any]:
    """Read Job Funnel settings. Secrets are not returned by the API."""
    return await api_get("/settings")


@_tool()
async def list_applications(
    user_id: int | None = None,
    resume_id: int | None = None,
    job_posting_id: int | None = None,
    q: str | None = None,
    classification_key: str | None = None,
    recommendation: str | None = None,
    status: str | None = None,
    status_group: str | None = None,
    score_min: float | None = None,
    score_max: float | None = None,
    created_since: str | None = None,
    updated_since: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    limit: int = 25,
    offset: int = 0,
    include_descriptions: bool = False,
) -> dict[str, Any]:
    """List Job Funnel applications with optional filters and compact application fields."""
    params = build_query(
        user_id=user_id,
        resume_id=resume_id,
        job_posting_id=job_posting_id,
        q=q,
        classification_key=classification_key,
        recommendation=recommendation,
        status=status,
        status_group=status_group,
        score_min=score_min,
        score_max=score_max,
        created_since=created_since,
        updated_since=updated_since,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    response = await api_get("/applications", params=params)
    return compact_application_list(response, include_descriptions=include_descriptions)


@_tool()
async def get_application(application_id: int, include_description: bool = True) -> dict[str, Any]:
    """Fetch one Job Funnel application by internal application id."""
    response = await api_get(f"/applications/{application_id}")
    return compact_application(response, include_description=include_description)


@_tool()
async def get_application_apply_url(application_id: int) -> dict[str, Any]:
    """Fetch the apply URL and identifying fields for one application."""
    application = await api_get(f"/applications/{application_id}")
    return {
        "id": application.get("id"),
        "company_name": application.get("company_name"),
        "title": application.get("title"),
        "status": application.get("status"),
        "score": application.get("score"),
        "recommendation": application.get("recommendation"),
        "apply_url": application.get("apply_url"),
    }


@_tool()
async def find_applications_for_email_signal(
    company_name: str | None = None,
    title: str | None = None,
    q: str | None = None,
    email_from: str | None = None,
    email_subject: str | None = None,
    email_received_at: str | None = None,
    status_group: str | None = None,
    created_since: str | None = None,
    updated_since: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find candidate applications that may match an external email signal such as a rejection."""
    return await collect_email_signal_candidates(
        company_name=company_name,
        title=title,
        q=q,
        email_from=email_from,
        email_subject=email_subject,
        email_received_at=email_received_at,
        status_group=status_group,
        created_since=created_since,
        updated_since=updated_since,
        limit=limit,
    )


@_tool()
async def list_runs(
    type: str | None = None,
    status: str | None = None,
    requested_status: str | None = None,
    callback_status: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List async Job Funnel runs."""
    params = build_query(
        type=type,
        status=status,
        requested_status=requested_status,
        callback_status=callback_status,
        limit=limit,
        offset=offset,
    )
    return await api_get("/runs", params=params)


@_tool()
async def get_run(run_id: int) -> dict[str, Any]:
    """Fetch one async Job Funnel run by id."""
    return await api_get(f"/runs/{run_id}")


@_tool()
async def list_run_items(run_id: int, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """List items for one async Job Funnel run with client-side pagination."""
    response = await api_get(f"/runs/{run_id}/items")
    items = response.get("items", [])
    return {
        "total": response.get("total", len(items)),
        "limit": limit,
        "offset": offset,
        "items": items[offset:offset + limit],
    }


@_tool()
async def list_run_applications(
    run_id: int,
    run_item_status: str | None = None,
    score_min: float | None = None,
    sort_by: str = "score",
    sort_order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """List applications associated with one async Job Funnel run."""
    params = build_query(
        run_item_status=run_item_status,
        score_min=score_min,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return await api_get(f"/runs/{run_id}/applications", params=params)


@_tool()
async def ingest_job(
    job_id: str,
    company_name: str | None = None,
    title: str | None = None,
    yearly_min_compensation: float | None = None,
    yearly_max_compensation: float | None = None,
    apply_url: str | None = None,
    description: str | None = None,
    source: str = "agent_mcp",
    confirm_write: bool = False,
) -> dict[str, Any]:
    """Ingest one normalized job posting. This writes data and requires confirm_write=true."""
    require_write_confirmation("ingest_job", confirm_write)
    payload = build_query(
        job_id=job_id,
        company_name=company_name,
        title=title,
        yearly_min_compensation=yearly_min_compensation,
        yearly_max_compensation=yearly_max_compensation,
        apply_url=apply_url,
        description=description,
        source=source,
    )
    return await api_post("/jobs/ingest", payload)


@_tool()
async def paste_job(
    description: str,
    url: str | None = None,
    company_name: str | None = None,
    title: str | None = None,
    user_id: int | None = None,
    process_now: bool = False,
    mode: str = "async",
    confirm_write: bool = False,
) -> dict[str, Any]:
    """Paste a job description into Job Funnel. Defaults to process_now=false and requires confirm_write=true."""
    require_write_confirmation("paste_job", confirm_write)
    payload = build_query(
        input_type="description",
        url=url,
        description=description,
        title=title,
        company_name=company_name,
        user_id=user_id,
        process_now=process_now,
        mode=mode,
    )
    return await api_post("/jobs/paste", payload)


@_tool()
async def queue_classification_run(
    limit: int = 25,
    source: str | None = None,
    classification_key: str | None = None,
    prompt_key: str | None = None,
    force: bool = False,
    callback_url: str | None = None,
    confirm_write: bool = False,
    confirm_force: bool = False,
    acknowledge_service_automation: bool = False,
) -> dict[str, Any]:
    """Queue an async classification run. This writes run data and may compete with service automation."""
    require_write_confirmation("queue_classification_run", confirm_write)
    require_force_confirmation(force, confirm_force)
    blocked = await check_agent_processing_guard(acknowledge_service_automation)
    if blocked is not None:
        return blocked
    payload = build_query(
        limit=limit,
        source=source,
        classification_key=classification_key,
        prompt_key=prompt_key,
        force=force,
        callback_url=callback_url,
    )
    return compact_run_response(await api_post("/jobs/classify/run", payload))


@_tool()
async def queue_application_generation_run(
    user_id: int,
    limit: int = 100,
    resume_strategy: str = "default_fallback",
    confirm_write: bool = False,
    acknowledge_service_automation: bool = False,
) -> dict[str, Any]:
    """Generate missing applications across classified jobs. This writes application data."""
    require_write_confirmation("queue_application_generation_run", confirm_write)
    blocked = await check_agent_processing_guard(acknowledge_service_automation)
    if blocked is not None:
        return blocked
    payload = {
        "user_id": user_id,
        "limit": limit,
        "resume_strategy": resume_strategy,
    }
    return compact_run_response(await api_post("/applications/generate/run", payload))


@_tool()
async def queue_scoring_run(
    limit: int = 25,
    status: str = "new",
    user_id: int | None = None,
    resume_id: int | None = None,
    job_posting_id: int | None = None,
    classification_key: str | None = None,
    prompt_key: str | None = None,
    force: bool = False,
    callback_url: str | None = None,
    confirm_write: bool = False,
    confirm_force: bool = False,
    acknowledge_service_automation: bool = False,
) -> dict[str, Any]:
    """Queue an async scoring run. This writes run data and may compete with service automation."""
    require_write_confirmation("queue_scoring_run", confirm_write)
    require_force_confirmation(force, confirm_force)
    blocked = await check_agent_processing_guard(acknowledge_service_automation)
    if blocked is not None:
        return blocked
    payload = build_query(
        limit=limit,
        status=status,
        user_id=user_id,
        resume_id=resume_id,
        job_posting_id=job_posting_id,
        classification_key=classification_key,
        prompt_key=prompt_key,
        force=force,
        callback_url=callback_url,
    )
    return compact_run_response(await api_post("/applications/score/run", payload))


@_tool()
async def mark_application_status(
    application_id: int,
    status: str,
    notes: str,
    effective_at: str | None = None,
    confirm_write: bool = False,
) -> dict[str, Any]:
    """Update an application status with notes. Terminal statuses require evidence-style notes."""
    require_write_confirmation("mark_application_status", confirm_write)
    if not notes.strip():
        raise JobFunnelSafetyError("notes are required when changing application status.")
    timestamp_field_by_status = {
        "applied": "applied_at",
        "screening": "screening_at",
        "offer": "offer_at",
        "rejected": "rejected_at",
        "ghosted": "ghosted_at",
        "withdrawn": "withdrawn_at",
        "pass": "passed_at",
    }
    notes_field_by_status = {
        "applied": "applied_notes",
        "screening": "screening_notes",
        "offer": "offer_notes",
        "rejected": "rejected_notes",
        "ghosted": "ghosted_notes",
        "withdrawn": "withdrawn_notes",
        "pass": "passed_notes",
    }
    if status not in notes_field_by_status:
        raise JobFunnelSafetyError(f"Unsupported status '{status}' for MCP status updates.")
    current_application = await get_application(application_id, include_description=False)
    payload: dict[str, Any] = {
        "status": status,
        notes_field_by_status[status]: notes,
    }
    if effective_at is not None:
        payload[timestamp_field_by_status[status]] = effective_at
    updated = await api_post(f"/applications/{application_id}/status", payload)
    return {
        "previous_status": current_application.get("status"),
        "application": compact_application(updated, include_description=False),
    }


@_tool()
async def mark_application_rejected_from_email(
    application_id: int,
    email_from: str,
    email_subject: str,
    email_received_at: str,
    notes: str | None = None,
    confirm_write: bool = False,
) -> dict[str, Any]:
    """Mark an application rejected using concise Gmail or email evidence."""
    require_write_confirmation("mark_application_rejected_from_email", confirm_write)
    evidence_note = (
        f"Rejected via email signal. From: {email_from}. "
        f"Subject: {email_subject}. Received: {email_received_at}."
    )
    if notes:
        evidence_note = f"{evidence_note} Notes: {notes}"
    return await mark_application_status(
        application_id=application_id,
        status="rejected",
        notes=evidence_note,
        effective_at=email_received_at,
        confirm_write=True,
    )


@_tool()
async def add_interview_round(
    application_id: int,
    round_number: int,
    stage_name: str | None = None,
    status: str = "scheduled",
    notes: str | None = None,
    scheduled_at: str | None = None,
    completed_at: str | None = None,
    confirm_write: bool = False,
) -> dict[str, Any]:
    """Add an interview round to an application. This writes data and requires confirm_write=true."""
    require_write_confirmation("add_interview_round", confirm_write)
    payload = build_query(
        round_number=round_number,
        stage_name=stage_name,
        status=status,
        notes=notes,
        scheduled_at=scheduled_at,
        completed_at=completed_at,
    )
    return await api_post(f"/applications/{application_id}/interview-rounds", payload)


@_tool()
async def prepare_application_assist(application_id: int) -> dict[str, Any]:
    """Prepare context for a human-gated browser-assisted job application workflow."""
    application = await get_application(application_id, include_description=False)
    settings = await get_settings()
    return {
        "application": {
            "id": application.get("id"),
            "company_name": application.get("company_name"),
            "title": application.get("title"),
            "apply_url": application.get("apply_url"),
            "status": application.get("status"),
            "score": application.get("score"),
            "recommendation": application.get("recommendation"),
            "classification_key": application.get("classification_key"),
            "resume_name": application.get("resume_name"),
            "scored_at": application.get("scored_at"),
            "applied_at": application.get("applied_at"),
        },
        "profile_context": {
            "profile_name": settings.get("profile_name"),
            "default_user_id": settings.get("default_user_id"),
            "target_roles": settings.get("target_roles"),
            "scoring_preferences": settings.get("scoring_preferences"),
        },
        "human_gate": {
            "final_submission_must_be_human": True,
            "agent_may_open_apply_url": True,
            "agent_may_fill_low_risk_profile_fields": True,
            "do_not_answer_without_user": HUMAN_GATED_APPLICATION_FIELDS,
            "status_update_requires_confirmation": True,
        },
        "next_steps": [
            "Open the apply_url in a browser controlled by the user or an approved browser connector.",
            "Fill only low-risk factual fields from user-provided profile/resume context.",
            "Ask the user before answering human-gated fields or uploading documents.",
            "Stop before final submission and let the user submit.",
            "After user confirmation, call mark_application_status with status='applied' and confirm_write=true.",
        ],
    }


@_resource("job-funnel://settings", mime_type="application/json")
async def settings_resource() -> str:
    """Current Job Funnel settings with API-key secrets omitted by the API."""
    return json_resource(await get_settings())


@_resource("job-funnel://target-roles", mime_type="application/json")
async def target_roles_resource() -> str:
    """Configured target roles from Job Funnel settings."""
    settings = await get_settings()
    return json_resource({"target_roles": settings.get("target_roles") or []})


@_resource("job-funnel://scoring-preferences", mime_type="application/json")
async def scoring_preferences_resource() -> str:
    """Configured scoring preferences from Job Funnel settings."""
    settings = await get_settings()
    return json_resource({"scoring_preferences": settings.get("scoring_preferences") or {}})


@_resource("job-funnel://agent-playbook", mime_type="text/plain")
async def agent_playbook_resource() -> str:
    """Agent operating rules for Job Funnel."""
    return "\n".join(
        [
            "Use Job Funnel through MCP tools or FastAPI routes only; do not edit the database directly.",
            "Start operational sessions with health_check and get_settings.",
            "Prefer read-only review unless the user explicitly asks for writes.",
            "Write tools require confirm_write=true; force=true requires confirm_force=true.",
            "Ask before changing statuses, lifecycle dates, interview rounds, notifications, prompts, provider settings, or automation settings.",
            "Do not auto-submit job applications; final submission must remain a human action.",
            "For email-derived updates, identify candidate records first and store concise evidence notes only.",
        ]
    )


@_resource("job-funnel://applications/{application_id}", mime_type="application/json")
async def application_resource(application_id: int) -> str:
    """Application detail by internal application id."""
    return json_resource(await get_application(application_id, include_description=True))


@_resource("job-funnel://runs/{run_id}", mime_type="application/json")
async def run_resource(run_id: int) -> str:
    """Run detail by internal run id."""
    return json_resource(await get_run(run_id))


@_prompt()
def review_strong_applications(score_min: float = 20.0, limit: int = 25) -> str:
    """Prompt for reviewing high-scoring applications."""
    return (
        "Review Job Funnel applications with status='scored' and scores above the requested threshold. "
        f"Call list_applications(status='scored', score_min={score_min}, sort_by='score', sort_order='desc', limit={limit}). "
        "Summarize the strongest opportunities, include application ids, companies, titles, scores, recommendations, and scored_at timestamps. "
        "Do not change statuses or queue processing."
    )


@_prompt()
def investigate_rejection_email(
    email_from: str,
    email_subject: str,
    email_received_at: str,
    company_hint: str | None = None,
    title_hint: str | None = None,
) -> str:
    """Prompt for matching a rejection email to Job Funnel records."""
    return (
        "Investigate a possible rejection email for a Job Funnel application. "
        "First call find_applications_for_email_signal with the provided email metadata and hints. "
        "If multiple candidates are returned, ask the user to choose the application. "
        "If exactly one strong candidate is returned, summarize the evidence and ask before calling mark_application_rejected_from_email. "
        "Do not store the full email body unless the user explicitly asks. "
        f"email_from={email_from!r}; email_subject={email_subject!r}; email_received_at={email_received_at!r}; "
        f"company_hint={company_hint!r}; title_hint={title_hint!r}."
    )


@_prompt()
def prepare_application_review(application_id: int) -> str:
    """Prompt for preparing a human-gated application workflow."""
    return (
        f"Prepare application id {application_id} for human-gated application assistance. "
        "Call prepare_application_assist(application_id) and use the returned apply_url and human_gate rules. "
        "You may help fill low-risk factual fields, but do not answer sponsorship, salary, demographic, legal, disability, veteran, or relocation questions without user input. "
        "Stop before final submission and let the user submit. "
        "Only mark the application applied after explicit user confirmation."
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if mcp is None:
        raise RuntimeError("The 'mcp' package is not installed. Install dependencies with 'pip install -r requirements.txt'.")
    logger.info("Starting Job Funnel MCP server for API base %s", api_base_url())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
