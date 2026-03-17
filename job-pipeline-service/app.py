from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated
import time
from urllib.parse import urlparse

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from database import Base, engine, get_session
from models import JobPosting, PromptLibrary
from schemas import (
    JobIngestItem,
    JobIngestResponse,
    JobListResponse,
    JobNotifyBatchItem,
    JobNotifyResponse,
    JobNotifyWrite,
    JobRead,
    JobScoreBatchItem,
    JobScoreResponse,
    JobScoreWrite,
    PromptLibraryCreate,
    PromptLibraryListResponse,
    PromptLibraryRead,
    PromptLibraryUpdate,
    JobsBatchNotifyResponse,
    JobsBatchScoreResponse,
)


def merge_responses(existing, incoming):
    if isinstance(existing, list) and isinstance(incoming, list):
        return existing + incoming

    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            if key in merged:
                merged[key] = merge_responses(merged[key], value)
            else:
                merged[key] = value
        return merged

    return incoming


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def apply_job_updates(job: JobPosting, payload: JobIngestItem) -> None:
    job.source = payload.source
    job.company_name = payload.company_name
    job.title = payload.title
    job.yearly_min_compensation = payload.yearly_min_compensation
    job.yearly_max_compensation = payload.yearly_max_compensation
    job.apply_url = payload.apply_url
    job.description = payload.description
    job.raw_payload = payload.raw_payload
    job.status = "new"


def apply_score(job: JobPosting, score_payload: JobScoreWrite) -> None:
    job.score = score_payload.score
    job.recommendation = score_payload.recommendation
    job.justification = score_payload.justification
    job.strengths = score_payload.strengths
    job.gaps = score_payload.gaps
    job.missing_from_jd = score_payload.missing_from_jd
    job.prompt_key = score_payload.prompt_key
    job.prompt_version = score_payload.prompt_version
    job.scored_at = score_payload.scored_at or utcnow()
    job.status = score_payload.status


def apply_notification(job: JobPosting, notify_payload: JobNotifyWrite) -> None:
    job.notified_at = notify_payload.notified_at or utcnow()
    job.status = notify_payload.status


def _get_job_by_id(session: Session, job_pk: int) -> JobPosting | None:
    return session.get(JobPosting, job_pk)


def _commit_or_fail(session: Session) -> None:
    for attempt in range(3):
        try:
            session.commit()
            return
        except OperationalError as exc:
            session.rollback()
            message = str(exc).lower()
            retryable = "database is locked" in message or "disk i/o error" in message or "sqlite3.OperationalError" in message
            if not retryable or attempt == 2:
                if "disk i/o error" in message:
                    raise HTTPException(status_code=503, detail="Database write failed due to SQLite I/O error") from exc
                raise
            time.sleep(0.2 * (attempt + 1))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Job Pipeline Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
async def operational_error_handler(_: Request, exc: OperationalError) -> JSONResponse:
    message = str(exc).lower()
    if "disk i/o error" in message or "database is locked" in message:
        return JSONResponse(status_code=503, content={"detail": "Database is temporarily unavailable"})
    return JSONResponse(status_code=500, content={"detail": "Database error"})


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/jobs/ingest", response_model=JobIngestResponse)
def ingest_jobs(
    payload: Annotated[JobIngestItem | list[JobIngestItem], Body(...)],
    session: Session = Depends(get_session),
):
    items = payload if isinstance(payload, list) else [payload]

    created = 0
    updated = 0
    job_ids: list[str] = []

    for item in items:
        job = session.scalar(select(JobPosting).where(JobPosting.job_id == item.job_id))
        if job is None:
            job = JobPosting(job_id=item.job_id)
            apply_job_updates(job, item)
            session.add(job)
            created += 1
        else:
            apply_job_updates(job, item)
            updated += 1

        job_ids.append(item.job_id)

    _commit_or_fail(session)

    return JobIngestResponse(
        received=len(items),
        created=created,
        updated=updated,
        jobs=job_ids,
    )


@app.get("/jobs", response_model=JobListResponse)
def list_jobs(
    session: Session = Depends(get_session),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = select(JobPosting).order_by(JobPosting.created_at.desc())
    count_query = select(JobPosting)

    if status:
        normalized_status = status.strip().lower()
        query = query.where(func.lower(func.trim(JobPosting.status)) == normalized_status)
        count_query = count_query.where(func.lower(func.trim(JobPosting.status)) == normalized_status)

    if source:
        query = query.where(JobPosting.source == source)
        count_query = count_query.where(JobPosting.source == source)

    items = session.scalars(query.offset(offset).limit(limit)).all()
    total = len(session.scalars(count_query).all())

    return JobListResponse(total=total, items=[JobRead.model_validate(item) for item in items])


@app.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    return JobRead.model_validate(job)


@app.post("/jobs/{job_id}/score", response_model=JobScoreResponse)
def store_job_score(job_id: int, score_payload: JobScoreWrite, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    apply_score(job, score_payload)
    _commit_or_fail(session)

    return JobScoreResponse(
        id=job.id,
        job_id=job.job_id,
        status=job.status,
        score=job.score,
        scored_at=job.scored_at,
        notified_at=job.notified_at,
    )


@app.post("/jobs/scores", response_model=JobsBatchScoreResponse)
def store_job_scores(score_payloads: list[JobScoreBatchItem], session: Session = Depends(get_session)):
    updated_job_ids: list[int] = []

    for score_payload in score_payloads:
        job = _get_job_by_id(session, score_payload.id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"Job '{score_payload.id}' was not found",
            )

        apply_score(job, score_payload)
        updated_job_ids.append(job.id)

    _commit_or_fail(session)

    return JobsBatchScoreResponse(updated=len(updated_job_ids), jobs=updated_job_ids)


@app.post("/jobs/{job_id}/notify", response_model=JobNotifyResponse)
def mark_job_notified(job_id: int, notify_payload: JobNotifyWrite, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    apply_notification(job, notify_payload)
    _commit_or_fail(session)

    return JobNotifyResponse(
        id=job.id,
        job_id=job.job_id,
        status=job.status,
        notified_at=job.notified_at,
    )


@app.post("/jobs/notify", response_model=JobsBatchNotifyResponse)
def mark_jobs_notified(notify_payloads: list[JobNotifyBatchItem], session: Session = Depends(get_session)):
    updated_job_ids: list[int] = []

    for notify_payload in notify_payloads:
        job = _get_job_by_id(session, notify_payload.id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"Job '{notify_payload.id}' was not found",
            )

        apply_notification(job, notify_payload)
        updated_job_ids.append(job.id)

    _commit_or_fail(session)

    return JobsBatchNotifyResponse(updated=len(updated_job_ids), jobs=updated_job_ids)


@app.get("/prompt-library", response_model=PromptLibraryListResponse)
def list_prompt_library(
    session: Session = Depends(get_session),
    prompt_key: str | None = Query(default=None),
    prompt_version: int | None = Query(default=None, ge=1),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = select(PromptLibrary).order_by(PromptLibrary.id.desc())

    if prompt_key:
        query = query.where(PromptLibrary.prompt_key == prompt_key)
    if prompt_version:
        query = query.where(PromptLibrary.prompt_version == prompt_version)
    if is_active is not None:
        query = query.where(PromptLibrary.is_active == is_active)

    items = session.scalars(query.offset(offset).limit(limit)).all()

    return PromptLibraryListResponse(total=len(items), items=[PromptLibraryRead.model_validate(item) for item in items])


@app.get("/prompt-library/{prompt_id}", response_model=PromptLibraryRead)
def get_prompt_library(prompt_id: int, session: Session = Depends(get_session)):
    prompt = session.get(PromptLibrary, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' was not found")

    return PromptLibraryRead.model_validate(prompt)


@app.post("/prompt-library", response_model=PromptLibraryRead)
def create_prompt_library(
    payload: PromptLibraryCreate,
    session: Session = Depends(get_session),
):
    prompt = PromptLibrary(
        prompt_key=payload.prompt_key,
        prompt_version=payload.prompt_version,
        system_prompt=payload.system_prompt,
        user_prompt_template=payload.user_prompt_template,
        base_resume_template=payload.base_resume_template,
        is_active=payload.is_active,
    )
    session.add(prompt)
    try:
        _commit_or_fail(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Prompt key/version combination already exists",
        ) from exc

    return PromptLibraryRead.model_validate(prompt)


@app.put("/prompt-library/{prompt_id}", response_model=PromptLibraryRead)
def update_prompt_library(
    prompt_id: int,
    payload: PromptLibraryUpdate,
    session: Session = Depends(get_session),
):
    prompt = session.get(PromptLibrary, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' was not found")

    if payload.prompt_key is not None:
        prompt.prompt_key = payload.prompt_key
    if payload.prompt_version is not None:
        prompt.prompt_version = payload.prompt_version
    if payload.system_prompt is not None:
        prompt.system_prompt = payload.system_prompt
    if payload.user_prompt_template is not None:
        prompt.user_prompt_template = payload.user_prompt_template
    if payload.base_resume_template is not None:
        prompt.base_resume_template = payload.base_resume_template
    if payload.is_active is not None:
        prompt.is_active = payload.is_active

    try:
        _commit_or_fail(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Prompt key/version combination already exists",
        ) from exc

    return PromptLibraryRead.model_validate(prompt)


@app.delete("/prompt-library/{prompt_id}")
def delete_prompt_library(prompt_id: int, session: Session = Depends(get_session)):
    prompt = session.get(PromptLibrary, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' was not found")

    session.delete(prompt)
    _commit_or_fail(session)

    return {"deleted": True, "id": prompt_id}


@app.get("/jobs/hiringcafe")
async def jobs(search_url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            async with page.expect_response(
                lambda response: urlparse(response.url).path == "/api/search-jobs",
                timeout=30000,
            ) as response_info:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            api_response = await response_info.value
            merged_response = await api_response.json()

            while True:
                try:
                    async with page.expect_response(
                        lambda response: urlparse(response.url).path == "/api/search-jobs",
                        timeout=4000,
                    ) as next_response_info:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                    next_response = await next_response_info.value
                    next_payload = await next_response.json()
                    merged_response = merge_responses(merged_response, next_payload)
                except PlaywrightTimeoutError:
                    break

            return merged_response
        except Exception as exc:
            raise HTTPException(
                status_code=504,
                detail=f"Failed to capture Hiring Cafe jobs response: {exc}",
            ) from exc
        finally:
            await context.close()
            await browser.close()
