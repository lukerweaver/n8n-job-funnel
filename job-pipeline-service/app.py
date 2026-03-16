from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import Base, engine, get_session
from models import JobPosting
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Job Pipeline Service", lifespan=lifespan)


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

    session.commit()

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
        query = query.where(JobPosting.status == status)
        count_query = count_query.where(JobPosting.status == status)

    if source:
        query = query.where(JobPosting.source == source)
        count_query = count_query.where(JobPosting.source == source)

    items = session.scalars(query.offset(offset).limit(limit)).all()
    total = len(session.scalars(count_query).all())

    return JobListResponse(total=total, items=[JobRead.model_validate(item) for item in items])


@app.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, session: Session = Depends(get_session)):
    job = session.scalar(select(JobPosting).where(JobPosting.job_id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    return JobRead.model_validate(job)


@app.post("/jobs/{job_id}/score", response_model=JobScoreResponse)
def store_job_score(job_id: str, score_payload: JobScoreWrite, session: Session = Depends(get_session)):
    job = session.scalar(select(JobPosting).where(JobPosting.job_id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    apply_score(job, score_payload)
    session.commit()

    return JobScoreResponse(
        job_id=job.job_id,
        status=job.status,
        score=job.score,
        scored_at=job.scored_at,
        notified_at=job.notified_at,
    )


@app.post("/jobs/scores", response_model=JobsBatchScoreResponse)
def store_job_scores(score_payloads: list[JobScoreBatchItem], session: Session = Depends(get_session)):
    updated_job_ids: list[str] = []

    for score_payload in score_payloads:
        job = session.scalar(select(JobPosting).where(JobPosting.job_id == score_payload.job_id))
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"Job '{score_payload.job_id}' was not found",
            )

        apply_score(job, score_payload)
        updated_job_ids.append(job.job_id)

    session.commit()

    return JobsBatchScoreResponse(updated=len(updated_job_ids), jobs=updated_job_ids)


@app.post("/jobs/{job_id}/notify", response_model=JobNotifyResponse)
def mark_job_notified(job_id: str, notify_payload: JobNotifyWrite, session: Session = Depends(get_session)):
    job = session.scalar(select(JobPosting).where(JobPosting.job_id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    apply_notification(job, notify_payload)
    session.commit()

    return JobNotifyResponse(
        job_id=job.job_id,
        status=job.status,
        notified_at=job.notified_at,
    )


@app.post("/jobs/notify", response_model=JobsBatchNotifyResponse)
def mark_jobs_notified(notify_payloads: list[JobNotifyBatchItem], session: Session = Depends(get_session)):
    updated_job_ids: list[str] = []

    for notify_payload in notify_payloads:
        job = session.scalar(select(JobPosting).where(JobPosting.job_id == notify_payload.job_id))
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"Job '{notify_payload.job_id}' was not found",
            )

        apply_notification(job, notify_payload)
        updated_job_ids.append(job.job_id)

    session.commit()

    return JobsBatchNotifyResponse(updated=len(updated_job_ids), jobs=updated_job_ids)


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
