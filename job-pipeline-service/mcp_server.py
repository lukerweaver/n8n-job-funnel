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

logger = logging.getLogger("job_funnel_mcp")
logging.getLogger("httpx").setLevel(logging.WARNING)
mcp = FastMCP("job-funnel") if FastMCP is not None else None


class JobFunnelApiError(RuntimeError):
    pass


def _tool(*args: Any, **kwargs: Any):
    if mcp is None:
        def decorator(func):
            return func

        return decorator
    return mcp.tool(*args, **kwargs)


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
    status_group: str | None = None,
    created_since: str | None = None,
    updated_since: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find candidate applications that may match an external email signal such as a rejection."""
    search_terms = [term for term in (q, company_name, title) if term]
    search_query = " ".join(search_terms) if search_terms else None
    response = await list_applications(
        q=search_query,
        status_group=status_group,
        created_since=created_since,
        updated_since=updated_since,
        sort_by="updated_at",
        sort_order="desc",
        limit=limit,
        include_descriptions=False,
    )
    return {
        "matched_by": {
            "company_name": company_name,
            "title": title,
            "q": q,
            "status_group": status_group,
            "created_since": created_since,
            "updated_since": updated_since,
            "searched_q": search_query,
        },
        "requires_human_selection": response["total"] != 1,
        "total": response["total"],
        "items": response["items"],
    }


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
    """List items for one async Job Funnel run."""
    return await api_get(f"/runs/{run_id}/items", params={"limit": limit, "offset": offset})


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


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if mcp is None:
        raise RuntimeError("The 'mcp' package is not installed. Install dependencies with 'pip install -r requirements.txt'.")
    logger.info("Starting Job Funnel MCP server for API base %s", api_base_url())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
