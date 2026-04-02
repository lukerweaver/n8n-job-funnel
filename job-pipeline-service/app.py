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
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from config import settings
from database import Base, engine, get_session
from models import InterviewRound, JobApplication, JobPosting, PromptLibrary, Resume, Run, RunItem, User
from schemas import (
    ApplicationCreate,
    ApplicationGenerateRequest,
    ApplicationsGenerateRunRequest,
    ApplicationsGenerateRunResponse,
    ApplicationGenerateResponse,
    ApplicationsScoreRunRequest,
    ApplicationsScoreRunResponse,
    ApplicationStatusWrite,
    InterviewRoundCreate,
    InterviewRoundListResponse,
    InterviewRoundRead,
    JobIngestItem,
    JobIngestResponse,
    JobApplicationListResponse,
    JobApplicationRead,
    JobApplicationScoreResponse,
    JobClassificationResponse,
    JobClassificationRunRequest,
    JobErrorResponse,
    JobErrorWrite,
    JobListResponse,
    JobNotifyBatchItem,
    JobNotifyResponse,
    JobNotifyWrite,
    JobRead,
    JobScoreRunRequest,
    JobScoreBatchItem,
    JobScoreResponse,
    JobScoreWrite,
    JobsScoreRunRequest,
    JobsScoreRunResponse,
    PromptLibraryCreate,
    PromptLibraryListResponse,
    PromptLibraryRead,
    PromptLibraryUpdate,
    ResumeCreate,
    ResumeListResponse,
    ResumeRead,
    ResumeUpdate,
    RunItemsResponse,
    RunItemRead,
    RunRead,
    UserCreate,
    UserListResponse,
    UserRead,
    JobsBatchNotifyResponse,
    JobsBatchScoreResponse,
    JobsClassificationRunRequest,
    JobsClassificationRunResponse,
    ScoreRunRead,
    ScoreRunItemsResponse,
)
from services.classification_service import classify_job
from services.legacy_sync_service import (
    LEGACY_MIGRATION_USER_EMAIL,
    LEGACY_MIGRATION_USER_NAME,
    _get_or_create_legacy_resume,
    _get_or_create_legacy_user,
    _legacy_resume_content,
    _map_legacy_job_status_to_application_status,
    sync_job_to_applications,
)
from services.llm_client import LlmRequestError
from services.prompt_service import PromptResolutionError
from services.score_run_service import (
    ScoreRunWorker,
    enqueue_application_score_run,
    enqueue_classification_run,
    enqueue_score_run,
    serialize_application_score_run,
    serialize_classification_run,
    serialize_run,
    serialize_score_run,
)
from services.scoring_service import JobScoringSkipped, score_application, score_job


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


score_run_worker = ScoreRunWorker()
ALLOWED_APPLICATION_STATUSES = {
    "new",
    "scored",
    "tailored",
    "notified",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
}

OPENAPI_TAGS = [
    {"name": "system", "description": "Health and operational utility endpoints."},
    {"name": "jobs", "description": "Job ingest, listing, classification, scoring, notification, and legacy compatibility routes."},
    {"name": "applications", "description": "Application generation, scoring, notification, status, and interview lifecycle routes."},
    {"name": "runs", "description": "Async run inspection for classification, application scoring, and legacy job scoring."},
    {"name": "users", "description": "User records that own resumes and applications."},
    {"name": "resumes", "description": "Resume inventory keyed to classification domains."},
    {"name": "prompt-library", "description": "Versioned prompt templates resolved by prompt key and prompt type."},
]


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
    job.role_type = score_payload.role_type
    job.screening_likelihood = score_payload.screening_likelihood
    job.dimension_scores = score_payload.dimension_scores
    job.gating_flags = score_payload.gating_flags
    job.strengths = score_payload.strengths
    job.gaps = score_payload.gaps
    job.missing_from_jd = score_payload.missing_from_jd
    job.prompt_key = score_payload.prompt_key
    job.prompt_version = score_payload.prompt_version
    job.scored_at = score_payload.scored_at or utcnow()
    job.score_error = None
    job.error_at = None
    job.status = score_payload.status


def apply_notification(job: JobPosting, notify_payload: JobNotifyWrite) -> None:
    job.notified_at = notify_payload.notified_at or utcnow()
    job.status = notify_payload.status


def apply_error(job: JobPosting, error_payload: JobErrorWrite) -> None:
    job.error_at = error_payload.error_at or utcnow()
    job.score_error = None
    job.status = error_payload.status


def _get_job_by_id(session: Session, job_pk: int) -> JobPosting | None:
    return session.get(JobPosting, job_pk)


def _get_user_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def _get_resume_by_id(session: Session, resume_id: int) -> Resume | None:
    return session.get(Resume, resume_id)


def _get_application_by_id(session: Session, application_id: int) -> JobApplication | None:
    return session.get(JobApplication, application_id)


def _normalize_user_default_resume(
    session: Session,
    user_id: int,
    *,
    selected_resume: Resume | None = None,
) -> None:
    resumes = session.scalars(select(Resume).where(Resume.user_id == user_id).order_by(Resume.id.asc())).all()
    if not resumes:
        return

    default_resume_id = selected_resume.id if selected_resume is not None else None
    if default_resume_id is None:
        existing_default = next((resume for resume in resumes if resume.is_default), None)
        default_resume_id = existing_default.id if existing_default is not None else None

    if default_resume_id is None:
        fallback = next((resume for resume in resumes if resume.is_active), resumes[0])
        default_resume_id = fallback.id

    for resume in resumes:
        resume.is_default = resume.id == default_resume_id


def _select_resumes_for_job_generation(
    session: Session,
    *,
    job: JobPosting,
    user_id: int | None,
    resume_strategy: str,
) -> list[Resume]:
    if not job.classification_key:
        return []

    base_query = select(Resume).where(Resume.is_active.is_(True))
    if user_id is not None:
        base_query = base_query.where(Resume.user_id == user_id)

    classification_resumes = session.scalars(
        base_query.where(Resume.classification_key == job.classification_key).order_by(Resume.id.asc())
    ).all()
    default_resumes = session.scalars(
        base_query.where(Resume.is_default.is_(True)).order_by(Resume.id.asc())
    ).all()

    if resume_strategy == "default_only":
        return default_resumes
    if resume_strategy == "default_fallback":
        return classification_resumes or default_resumes
    return classification_resumes


def _serialize_application(application: JobApplication) -> JobApplicationRead:
    job = application.job_posting
    resume = application.resume
    return JobApplicationRead(
        id=application.id,
        user_id=application.user_id,
        job_posting_id=application.job_posting_id,
        resume_id=application.resume_id,
        job_id=job.job_id if job is not None else None,
        source=job.source if job is not None else None,
        company_name=job.company_name if job is not None else None,
        title=job.title if job is not None else None,
        yearly_min_compensation=job.yearly_min_compensation if job is not None else None,
        yearly_max_compensation=job.yearly_max_compensation if job is not None else None,
        apply_url=job.apply_url if job is not None else None,
        role_type=job.role_type if job is not None else None,
        resume_name=resume.name if resume is not None else None,
        status=application.status,
        score=application.score,
        recommendation=application.recommendation,
        justification=application.justification,
        screening_likelihood=application.screening_likelihood,
        dimension_scores=application.dimension_scores,
        gating_flags=application.gating_flags,
        strengths=application.strengths,
        gaps=application.gaps,
        missing_from_jd=application.missing_from_jd,
        scoring_prompt_key=application.scoring_prompt_key,
        scoring_prompt_version=application.scoring_prompt_version,
        score_error=application.score_error,
        scored_at=application.scored_at,
        tailored_resume_content=application.tailored_resume_content,
        tailoring_prompt_key=application.tailoring_prompt_key,
        tailoring_prompt_version=application.tailoring_prompt_version,
        tailoring_error=application.tailoring_error,
        tailored_at=application.tailored_at,
        notified_at=application.notified_at,
        applied_at=application.applied_at,
        offer_at=application.offer_at,
        rejected_at=application.rejected_at,
        withdrawn_at=application.withdrawn_at,
        last_error_at=application.last_error_at,
        created_at=application.created_at,
        updated_at=application.updated_at,
    )


def _serialize_application_score(application: JobApplication) -> JobApplicationScoreResponse:
    return JobApplicationScoreResponse(
        id=application.id,
        job_posting_id=application.job_posting_id,
        resume_id=application.resume_id,
        status=application.status,
        score=application.score,
        recommendation=application.recommendation,
        screening_likelihood=application.screening_likelihood,
        dimension_scores=application.dimension_scores,
        gating_flags=application.gating_flags,
        scored_at=application.scored_at,
        notified_at=application.notified_at,
        last_error_at=application.last_error_at,
        score_error=application.score_error,
    )


def _serialize_job_classification(job: JobPosting) -> JobClassificationResponse:
    return JobClassificationResponse(
        id=job.id,
        job_id=job.job_id,
        classification_key=job.classification_key,
        classification_prompt_version=job.classification_prompt_version,
        classified_at=job.classified_at,
        classification_error=job.classification_error,
    )


def _validate_application_entities(
    session: Session,
    *,
    user_id: int,
    resume_id: int,
    job_posting_id: int,
) -> tuple[User, Resume, JobPosting]:
    user = _get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' was not found")

    resume = _get_resume_by_id(session, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail=f"Resume '{resume_id}' was not found")
    if resume.user_id != user_id:
        raise HTTPException(status_code=409, detail="Resume does not belong to the selected user")

    job_posting = _get_job_by_id(session, job_posting_id)
    if job_posting is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_posting_id}' was not found")

    return user, resume, job_posting


def apply_application_score(application: JobApplication, score_payload: JobScoreWrite) -> None:
    application.score = score_payload.score
    application.recommendation = score_payload.recommendation
    application.justification = score_payload.justification
    application.screening_likelihood = score_payload.screening_likelihood
    application.dimension_scores = score_payload.dimension_scores
    application.gating_flags = score_payload.gating_flags
    application.strengths = score_payload.strengths
    application.gaps = score_payload.gaps
    application.missing_from_jd = score_payload.missing_from_jd
    application.scoring_prompt_key = score_payload.prompt_key
    application.scoring_prompt_version = score_payload.prompt_version
    application.scored_at = score_payload.scored_at or utcnow()
    application.score_error = None
    application.last_error_at = None
    application.status = score_payload.status


def apply_application_notification(application: JobApplication, notify_payload: JobNotifyWrite) -> None:
    application.notified_at = notify_payload.notified_at or utcnow()
    application.status = notify_payload.status


def apply_application_error(application: JobApplication, error_payload: JobErrorWrite) -> None:
    application.last_error_at = error_payload.error_at or utcnow()
    application.status = "new" if error_payload.status == "error" else error_payload.status


def apply_application_status(application: JobApplication, payload: ApplicationStatusWrite) -> None:
    application.status = payload.status
    if payload.status == "applied":
        application.applied_at = payload.applied_at or utcnow()
    elif payload.status == "offer":
        application.offer_at = payload.offer_at or utcnow()
    elif payload.status == "rejected":
        application.rejected_at = payload.rejected_at or utcnow()
    elif payload.status == "withdrawn":
        application.withdrawn_at = payload.withdrawn_at or utcnow()


def _get_run_by_id(session: Session, run_id: int) -> Run | None:
    return session.get(Run, run_id)


def _get_score_run_by_id(session: Session, run_id: int) -> Run | None:
    return _get_run_by_id(session, run_id)


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


def ensure_job_postings_schema() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("job_postings")}

    json_type = "JSONB" if engine.dialect.name == "postgresql" else "JSON"
    float_type = "DOUBLE PRECISION" if engine.dialect.name == "postgresql" else "REAL"
    type_map = {
        "error_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
        "role_type": "VARCHAR(100)",
        "screening_likelihood": float_type,
        "dimension_scores": json_type,
        "gating_flags": json_type,
        "score_provider": "VARCHAR(100)",
        "score_model": "VARCHAR(255)",
        "score_error": "TEXT",
        "score_raw_response": "TEXT",
        "score_attempts": "INTEGER",
        "classification_key": "VARCHAR(100)",
        "classification_prompt_version": "INTEGER",
        "classification_provider": "VARCHAR(100)",
        "classification_model": "VARCHAR(255)",
        "classification_error": "TEXT",
        "classification_raw_response": "TEXT",
        "classified_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
    }

    statements = [
        f"ALTER TABLE job_postings ADD COLUMN {column_name} {column_type}"
        for column_name, column_type in type_map.items()
        if column_name not in columns
    ]

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_prompt_library_schema() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("prompt_library")}

    float_type = "DOUBLE PRECISION" if engine.dialect.name == "postgresql" else "REAL"
    type_map = {
        "prompt_type": "VARCHAR(50)",
        "context": "TEXT",
        "max_tokens": "INTEGER",
        "temperature": float_type,
        "created_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
        "updated_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
    }

    statements = [
        f"ALTER TABLE prompt_library ADD COLUMN {column_name} {column_type}"
        for column_name, column_type in type_map.items()
        if column_name not in columns
    ]

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        if "prompt_type" not in columns:
            connection.execute(text("UPDATE prompt_library SET prompt_type = 'scoring' WHERE prompt_type IS NULL"))
        if "created_at" not in columns:
            connection.execute(
                text(
                    "UPDATE prompt_library SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                )
            )
        if "updated_at" not in columns:
            connection.execute(
                text(
                    "UPDATE prompt_library SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
                )
            )


def ensure_resumes_schema() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("resumes")}

    statements: list[str] = []
    if "classification_key" not in columns:
        statements.append("ALTER TABLE resumes ADD COLUMN classification_key VARCHAR(100)")
    if "is_default" not in columns:
        statements.append("ALTER TABLE resumes ADD COLUMN is_default BOOLEAN DEFAULT FALSE")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        if "classification_key" not in columns:
            connection.execute(
                text(
                    """
                    UPDATE resumes
                    SET classification_key = prompt_key
                    WHERE classification_key IS NULL AND prompt_key IS NOT NULL
                    """
                )
            )
        if "is_default" not in columns:
            connection.execute(text("UPDATE resumes SET is_default = FALSE WHERE is_default IS NULL"))


def ensure_run_schema() -> None:
    inspector = inspect(engine)

    run_columns = {column["name"] for column in inspector.get_columns("score_runs")}
    run_type = "VARCHAR(50)"
    run_statements = []
    if "type" not in run_columns:
        run_statements.append(f"ALTER TABLE score_runs ADD COLUMN type {run_type}")
    if "classification_key" not in run_columns:
        run_statements.append("ALTER TABLE score_runs ADD COLUMN classification_key VARCHAR(255)")

    item_columns = {column["name"] for column in inspector.get_columns("score_run_items")}
    item_statements = []
    if "type" not in item_columns:
        item_statements.append(f"ALTER TABLE score_run_items ADD COLUMN type {run_type}")
    if "job_application_id" not in item_columns:
        item_statements.append("ALTER TABLE score_run_items ADD COLUMN job_application_id INTEGER")

    if not run_statements and not item_statements:
        return

    with engine.begin() as connection:
        for statement in run_statements:
            connection.execute(text(statement))
        for statement in item_statements:
            connection.execute(text(statement))
        if "type" not in run_columns:
            connection.execute(text("UPDATE score_runs SET type = 'scoring' WHERE type IS NULL"))
        if "classification_key" not in run_columns:
            connection.execute(
                text(
                    """
                    UPDATE score_runs
                    SET classification_key = prompt_key
                    WHERE classification_key IS NULL AND prompt_key IS NOT NULL
                    """
                )
            )
        if "type" not in item_columns:
            connection.execute(text("UPDATE score_run_items SET type = 'scoring' WHERE type IS NULL"))


def _backfill_prompt_context_from_legacy_column(session: Session) -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("prompt_library")}
    if "base_resume_template" not in columns:
        return

    session.execute(
        text(
            """
            UPDATE prompt_library
            SET context = base_resume_template
            WHERE (context IS NULL OR TRIM(context) = '')
              AND base_resume_template IS NOT NULL
              AND TRIM(base_resume_template) <> ''
            """
        )
    )


def _backfill_job_posting_classification(session: Session) -> None:
    jobs = session.scalars(
        select(JobPosting).where(
            JobPosting.classification_key.is_(None),
            JobPosting.role_type.is_not(None),
        )
    ).all()
    for job in jobs:
        role_type = (job.role_type or "").strip()
        if not role_type:
            continue
        job.classification_key = role_type
        if job.classified_at is None:
            job.classified_at = job.scored_at or job.updated_at or job.created_at


def _backfill_resume_classification_keys(session: Session) -> None:
    resumes = session.scalars(
        select(Resume).where(Resume.classification_key.is_(None), Resume.prompt_key.is_not(None))
    ).all()
    for resume in resumes:
        resume.classification_key = resume.prompt_key


def _backfill_resume_defaults(session: Session) -> None:
    user_ids = session.scalars(select(Resume.user_id).distinct()).all()
    for user_id in user_ids:
        _normalize_user_default_resume(session, user_id)


def _job_requires_application_backfill(job: JobPosting) -> bool:
    if job.status and job.status != "new":
        return True
    return any(
        value is not None
        for value in (
            job.score,
            job.recommendation,
            job.justification,
            job.screening_likelihood,
            job.dimension_scores,
            job.gating_flags,
            job.strengths,
            job.gaps,
            job.missing_from_jd,
            job.prompt_key,
            job.prompt_version,
            job.score_provider,
            job.score_model,
            job.score_error,
            job.score_raw_response,
            job.scored_at,
            job.notified_at,
            job.error_at,
        )
    ) or (job.score_attempts or 0) > 0


def _backfill_job_applications(session: Session) -> None:
    jobs = session.scalars(select(JobPosting).order_by(JobPosting.id.asc())).all()
    for job in jobs:
        if not _job_requires_application_backfill(job):
            continue
        sync_job_to_applications(session, job)


def run_phase_two_backfill(session: Session) -> None:
    _backfill_prompt_context_from_legacy_column(session)
    _backfill_job_posting_classification(session)
    _backfill_resume_classification_keys(session)
    _backfill_resume_defaults(session)
    _backfill_job_applications(session)
    session.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_job_postings_schema()
    ensure_prompt_library_schema()
    ensure_resumes_schema()
    ensure_run_schema()
    with Session(engine) as session:
        run_phase_two_backfill(session)
    score_run_worker.start()
    yield
    score_run_worker.stop()


app = FastAPI(title="Job Pipeline Service", lifespan=lifespan, openapi_tags=OPENAPI_TAGS)
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


@app.exception_handler(PromptResolutionError)
async def prompt_resolution_error_handler(_: Request, exc: PromptResolutionError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(LlmRequestError)
async def llm_request_error_handler(_: Request, exc: LlmRequestError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health", tags=["system"])
async def health():
    return {"ok": True}


@app.post("/jobs/ingest", response_model=JobIngestResponse, tags=["jobs"])
def ingest_jobs(
    payload: Annotated[JobIngestItem | list[JobIngestItem], Body(...)],
    session: Session = Depends(get_session),
):
    items = payload if isinstance(payload, list) else [payload]

    created = 0
    updated = 0
    skipped = 0
    job_ids: list[str] = []

    for item in items:
        job = session.scalar(select(JobPosting).where(JobPosting.job_id == item.job_id))
        if job is None:
            job = JobPosting(job_id=item.job_id)
            apply_job_updates(job, item)
            session.add(job)
            created += 1
            job_ids.append(item.job_id)
            continue

        skipped += 1

    _commit_or_fail(session)

    return JobIngestResponse(
        received=len(items),
        created=created,
        updated=updated,
        skipped=skipped,
        jobs=job_ids,
    )


@app.get("/jobs", response_model=JobListResponse, tags=["jobs"])
def list_jobs(
    session: Session = Depends(get_session),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    score: float | None = Query(default=None),
    role_type: str | None = Query(default=None),
    screening_likelihood: float | None = Query(default=None),
    scored_since: datetime | None = Query(default=None),
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

    if score is not None:
        query = query.where(JobPosting.score.is_not(None), JobPosting.score >= score)
        count_query = count_query.where(JobPosting.score.is_not(None), JobPosting.score >= score)

    if role_type:
        query = query.where(JobPosting.role_type == role_type)
        count_query = count_query.where(JobPosting.role_type == role_type)

    if screening_likelihood is not None:
        query = query.where(
            JobPosting.screening_likelihood.is_not(None),
            JobPosting.screening_likelihood >= screening_likelihood,
        )
        count_query = count_query.where(
            JobPosting.screening_likelihood.is_not(None),
            JobPosting.screening_likelihood >= screening_likelihood,
        )

    if scored_since is not None:
        query = query.where(JobPosting.scored_at.is_not(None), JobPosting.scored_at > scored_since)
        count_query = count_query.where(JobPosting.scored_at.is_not(None), JobPosting.scored_at > scored_since)

    items = session.scalars(query.offset(offset).limit(limit)).all()
    total = len(session.scalars(count_query).all())

    return JobListResponse(total=total, items=[JobRead.model_validate(item) for item in items])


@app.get("/jobs/{job_id}", response_model=JobRead, tags=["jobs"])
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    return JobRead.model_validate(job)


@app.post("/jobs/{job_id}/classify/run", response_model=JobClassificationResponse, tags=["jobs"])
def run_job_classification(job_id: int, payload: JobClassificationRunRequest, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    try:
        result = classify_job(
            session,
            job,
            classification_key=payload.classification_key,
            prompt_key=payload.prompt_key,
            force=payload.force,
        )
    except JobScoringSkipped as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _commit_or_fail(session)
    return _serialize_job_classification(result.job)


@app.post("/jobs/classify/run", response_model=JobsClassificationRunResponse, status_code=202, tags=["jobs"])
def run_jobs_classification(payload: JobsClassificationRunRequest, session: Session = Depends(get_session)):
    run = enqueue_classification_run(
        session,
        limit=payload.limit,
        source=payload.source,
        classification_key=payload.classification_key,
        prompt_key=payload.prompt_key,
        force=payload.force,
        callback_url=payload.callback_url,
    )
    _commit_or_fail(session)
    session.refresh(run)
    return JobsClassificationRunResponse(**serialize_classification_run(session, run))


@app.post("/jobs/{job_id}/score", response_model=JobScoreResponse, tags=["jobs"])
def store_job_score(job_id: int, score_payload: JobScoreWrite, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    apply_score(job, score_payload)
    sync_job_to_applications(session, job)
    _commit_or_fail(session)

    return JobScoreResponse(
        id=job.id,
        job_id=job.job_id,
        status=job.status,
        score=job.score,
        recommendation=job.recommendation,
        role_type=job.role_type,
        screening_likelihood=job.screening_likelihood,
        dimension_scores=job.dimension_scores,
        gating_flags=job.gating_flags,
        scored_at=job.scored_at,
        notified_at=job.notified_at,
        error_at=job.error_at,
        score_error=job.score_error,
    )


@app.post("/jobs/{job_id}/score/run", response_model=JobScoreResponse, tags=["jobs"])
def run_job_score(job_id: int, payload: JobScoreRunRequest, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    try:
        result = score_job(
            session,
            job,
            classification_key=payload.classification_key,
            prompt_key=payload.prompt_key,
            force=payload.force,
        )
    except JobScoringSkipped as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _commit_or_fail(session)

    return JobScoreResponse(
        id=result.job.id,
        job_id=result.job.job_id,
        status=result.job.status,
        score=result.job.score,
        recommendation=result.job.recommendation,
        role_type=result.job.role_type,
        screening_likelihood=result.job.screening_likelihood,
        dimension_scores=result.job.dimension_scores,
        gating_flags=result.job.gating_flags,
        scored_at=result.job.scored_at,
        notified_at=result.job.notified_at,
        error_at=result.job.error_at,
        score_error=result.job.score_error,
    )


@app.post("/jobs/score/run", response_model=JobsScoreRunResponse, status_code=202, tags=["jobs"])
def run_jobs_score(payload: JobsScoreRunRequest, session: Session = Depends(get_session)):
    run = enqueue_score_run(
        session,
        limit=payload.limit,
        status=payload.status,
        source=payload.source,
        classification_key=payload.classification_key,
        prompt_key=payload.prompt_key,
        force=payload.force,
        callback_url=payload.callback_url,
    )
    _commit_or_fail(session)
    session.refresh(run)
    return JobsScoreRunResponse(**serialize_score_run(session, run))

@app.get("/runs/{run_id}", response_model=RunRead, tags=["runs"])
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = _get_run_by_id(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' was not found")

    return RunRead(**serialize_run(session, run))


@app.get("/runs/{run_id}/items", response_model=RunItemsResponse, tags=["runs"])
def list_run_items(run_id: int, session: Session = Depends(get_session)):
    run = _get_run_by_id(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' was not found")

    items = session.scalars(
        select(RunItem)
        .where(RunItem.score_run_id == run_id)
        .order_by(RunItem.id.asc())
    ).all()
    return RunItemsResponse(
        total=len(items),
        items=[
            RunItemRead(
                id=item.id,
                type=item.type,
                job_posting_id=item.job_posting_id,
                job_application_id=item.job_application_id,
                status=item.status,
                error_message=item.error_message,
                started_at=item.started_at,
                finished_at=item.finished_at,
            )
            for item in items
        ],
    )


@app.get("/score-runs/{run_id}", response_model=ScoreRunRead, tags=["runs"])
def get_score_run(run_id: int, session: Session = Depends(get_session)):
    run = _get_score_run_by_id(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Score run '{run_id}' was not found")
    if run.type != "scoring":
        raise HTTPException(status_code=404, detail=f"Score run '{run_id}' was not found")

    return ScoreRunRead(**serialize_score_run(session, run))


@app.get("/score-runs/{run_id}/items", response_model=ScoreRunItemsResponse, tags=["runs"])
def list_score_run_items(run_id: int, session: Session = Depends(get_session)):
    run = _get_score_run_by_id(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Score run '{run_id}' was not found")
    if run.type != "scoring":
        raise HTTPException(status_code=404, detail=f"Score run '{run_id}' was not found")

    items = list_run_items(run_id, session)
    return ScoreRunItemsResponse(total=items.total, items=items.items)


@app.post("/jobs/scores", response_model=JobsBatchScoreResponse, tags=["jobs"])
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
        sync_job_to_applications(session, job)
        updated_job_ids.append(job.id)

    _commit_or_fail(session)

    return JobsBatchScoreResponse(updated=len(updated_job_ids), jobs=updated_job_ids)


@app.post("/jobs/{job_id}/notify", response_model=JobNotifyResponse, tags=["jobs"])
def mark_job_notified(job_id: int, notify_payload: JobNotifyWrite, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    apply_notification(job, notify_payload)
    sync_job_to_applications(session, job)
    _commit_or_fail(session)

    return JobNotifyResponse(
        id=job.id,
        job_id=job.job_id,
        status=job.status,
        notified_at=job.notified_at,
    )


@app.post("/jobs/{job_id}/error", response_model=JobErrorResponse, tags=["jobs"])
def mark_job_error(job_id: int, error_payload: JobErrorWrite, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' was not found")

    apply_error(job, error_payload)
    sync_job_to_applications(session, job)
    _commit_or_fail(session)

    return JobErrorResponse(
        id=job.id,
        job_id=job.job_id,
        status=job.status,
        error_at=job.error_at,
        score_error=job.score_error,
    )


@app.post("/jobs/notify", response_model=JobsBatchNotifyResponse, tags=["jobs"])
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
        sync_job_to_applications(session, job)
        updated_job_ids.append(job.id)

    _commit_or_fail(session)

    return JobsBatchNotifyResponse(updated=len(updated_job_ids), jobs=updated_job_ids)


@app.get("/users", response_model=UserListResponse, tags=["users"])
def list_users(
    session: Session = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    items = session.scalars(select(User).order_by(User.id.asc()).offset(offset).limit(limit)).all()
    total = len(session.scalars(select(User)).all())
    return UserListResponse(total=total, items=[UserRead.model_validate(item) for item in items])


@app.post("/users", response_model=UserRead, tags=["users"])
def create_user(payload: UserCreate, session: Session = Depends(get_session)):
    user = User(name=payload.name, email=payload.email)
    session.add(user)
    try:
        _commit_or_fail(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="User email already exists") from exc
    return UserRead.model_validate(user)


@app.get("/resumes", response_model=ResumeListResponse, tags=["resumes"])
def list_resumes(
    session: Session = Depends(get_session),
    user_id: int | None = Query(default=None),
    classification_key: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = select(Resume).order_by(Resume.id.asc())
    count_query = select(Resume)
    if user_id is not None:
        query = query.where(Resume.user_id == user_id)
        count_query = count_query.where(Resume.user_id == user_id)
    if classification_key:
        query = query.where(Resume.classification_key == classification_key)
        count_query = count_query.where(Resume.classification_key == classification_key)
    if is_active is not None:
        query = query.where(Resume.is_active == is_active)
        count_query = count_query.where(Resume.is_active == is_active)
    items = session.scalars(query.offset(offset).limit(limit)).all()
    total = len(session.scalars(count_query).all())
    return ResumeListResponse(total=total, items=[ResumeRead.model_validate(item) for item in items])


@app.post("/resumes", response_model=ResumeRead, tags=["resumes"])
def create_resume(payload: ResumeCreate, session: Session = Depends(get_session)):
    user = _get_user_by_id(session, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User '{payload.user_id}' was not found")
    prompt_key = payload.prompt_key if payload.prompt_key is not None else payload.classification_key
    if prompt_key is None:
        raise HTTPException(status_code=422, detail="Resume prompt_key is required when classification_key is omitted")
    resume = Resume(
        user_id=payload.user_id,
        name=payload.name,
        prompt_key=prompt_key,
        classification_key=payload.classification_key,
        content=payload.content,
        is_active=payload.is_active,
        is_default=payload.is_default,
    )
    session.add(resume)
    session.flush()
    if resume.is_default:
        _normalize_user_default_resume(session, resume.user_id, selected_resume=resume)
    else:
        has_other_default = session.scalar(
            select(Resume.id)
            .where(Resume.user_id == resume.user_id, Resume.is_default.is_(True), Resume.id != resume.id)
            .limit(1)
        )
        if has_other_default is None:
            _normalize_user_default_resume(session, resume.user_id, selected_resume=resume)
    _commit_or_fail(session)
    return ResumeRead.model_validate(resume)


@app.put("/resumes/{resume_id}", response_model=ResumeRead, tags=["resumes"])
def update_resume(resume_id: int, payload: ResumeUpdate, session: Session = Depends(get_session)):
    resume = _get_resume_by_id(session, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail=f"Resume '{resume_id}' was not found")
    if payload.name is not None:
        resume.name = payload.name
    if payload.prompt_key is not None:
        resume.prompt_key = payload.prompt_key
    if payload.classification_key is not None:
        resume.classification_key = payload.classification_key
    if payload.content is not None:
        resume.content = payload.content
    if payload.is_active is not None:
        resume.is_active = payload.is_active
    if payload.is_default is not None:
        resume.is_default = payload.is_default
    if resume.is_default:
        _normalize_user_default_resume(session, resume.user_id, selected_resume=resume)
    else:
        _normalize_user_default_resume(session, resume.user_id)
    _commit_or_fail(session)
    return ResumeRead.model_validate(resume)


@app.get("/applications", response_model=JobApplicationListResponse, tags=["applications"])
def list_applications(
    session: Session = Depends(get_session),
    user_id: int | None = Query(default=None),
    resume_id: int | None = Query(default=None),
    job_posting_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    score: float | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = (
        select(JobApplication)
        .options(selectinload(JobApplication.job_posting), selectinload(JobApplication.resume))
        .order_by(JobApplication.created_at.desc())
    )
    count_query = select(JobApplication)
    if user_id is not None:
        query = query.where(JobApplication.user_id == user_id)
        count_query = count_query.where(JobApplication.user_id == user_id)
    if resume_id is not None:
        query = query.where(JobApplication.resume_id == resume_id)
        count_query = count_query.where(JobApplication.resume_id == resume_id)
    if job_posting_id is not None:
        query = query.where(JobApplication.job_posting_id == job_posting_id)
        count_query = count_query.where(JobApplication.job_posting_id == job_posting_id)
    if status:
        query = query.where(JobApplication.status == status)
        count_query = count_query.where(JobApplication.status == status)
    if score is not None:
        query = query.where(JobApplication.score.is_not(None), JobApplication.score >= score)
        count_query = count_query.where(JobApplication.score.is_not(None), JobApplication.score >= score)
    items = session.scalars(query.offset(offset).limit(limit)).all()
    total = len(session.scalars(count_query).all())
    return JobApplicationListResponse(total=total, items=[_serialize_application(item) for item in items])


@app.get("/applications/{application_id}", response_model=JobApplicationRead, tags=["applications"])
def get_application(application_id: int, session: Session = Depends(get_session)):
    application = session.scalar(
        select(JobApplication)
        .options(selectinload(JobApplication.job_posting), selectinload(JobApplication.resume))
        .where(JobApplication.id == application_id)
    )
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    return _serialize_application(application)


@app.post("/applications", response_model=JobApplicationRead, tags=["applications"])
def create_application(payload: ApplicationCreate, session: Session = Depends(get_session)):
    _, resume, _ = _validate_application_entities(
        session,
        user_id=payload.user_id,
        resume_id=payload.resume_id,
        job_posting_id=payload.job_posting_id,
    )
    application = JobApplication(
        user_id=payload.user_id,
        job_posting_id=payload.job_posting_id,
        resume_id=payload.resume_id,
        status=payload.status,
    )
    session.add(application)
    try:
        _commit_or_fail(session)
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(JobApplication).where(
                JobApplication.job_posting_id == payload.job_posting_id,
                JobApplication.resume_id == payload.resume_id,
            )
        )
        if existing is None:
            raise
        # Regeneration semantics overwrite the existing application for the
        # posting/resume pair instead of creating a second row.
        existing.user_id = payload.user_id
        existing.status = payload.status
        existing.score = None
        existing.recommendation = None
        existing.justification = None
        existing.screening_likelihood = None
        existing.dimension_scores = None
        existing.gating_flags = None
        existing.strengths = None
        existing.gaps = None
        existing.missing_from_jd = None
        existing.scoring_prompt_key = None
        existing.scoring_prompt_version = None
        existing.score_provider = None
        existing.score_model = None
        existing.score_raw_response = None
        existing.score_error = None
        existing.score_attempts = 0
        existing.scored_at = None
        existing.tailored_resume_content = None
        existing.tailoring_prompt_key = None
        existing.tailoring_prompt_version = None
        existing.tailoring_provider = None
        existing.tailoring_model = None
        existing.tailoring_raw_response = None
        existing.tailoring_error = None
        existing.tailored_at = None
        existing.notified_at = None
        existing.applied_at = None
        existing.offer_at = None
        existing.rejected_at = None
        existing.withdrawn_at = None
        existing.last_error_at = None
        existing.resume_id = resume.id
        _commit_or_fail(session)
        return _serialize_application(existing)
    return _serialize_application(application)


@app.post("/applications/generate", response_model=ApplicationGenerateResponse, tags=["applications"])
def generate_applications(payload: ApplicationGenerateRequest, session: Session = Depends(get_session)):
    job = _get_job_by_id(session, payload.job_posting_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{payload.job_posting_id}' was not found")
    if not job.classification_key:
        raise HTTPException(status_code=409, detail="Job posting is missing classification_key")
    resumes = _select_resumes_for_job_generation(
        session,
        job=job,
        user_id=payload.user_id,
        resume_strategy=payload.resume_strategy,
    )
    created = 0
    skipped = 0
    application_ids: list[int] = []

    for resume in resumes:
        existing = session.scalar(
            select(JobApplication).where(
                JobApplication.job_posting_id == job.id,
                JobApplication.resume_id == resume.id,
            )
        )
        if existing is not None:
            skipped += 1
            application_ids.append(existing.id)
            continue

        application = JobApplication(
            user_id=resume.user_id,
            job_posting_id=job.id,
            resume_id=resume.id,
            status="new",
        )
        session.add(application)
        session.flush()
        created += 1
        application_ids.append(application.id)

    _commit_or_fail(session)
    return ApplicationGenerateResponse(created=created, skipped=skipped, applications=application_ids)


@app.post("/applications/generate/run", response_model=ApplicationsGenerateRunResponse, tags=["applications"])
def run_applications_generate(payload: ApplicationsGenerateRunRequest, session: Session = Depends(get_session)):
    user = _get_user_by_id(session, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User '{payload.user_id}' was not found")

    candidate_jobs = session.scalars(
        select(JobPosting)
        .where(JobPosting.classification_key.is_not(None))
        .order_by(JobPosting.created_at.asc())
    ).all()

    jobs: list[JobPosting] = []
    for job in candidate_jobs:
        existing_application_exists = session.scalar(
            select(JobApplication.id)
            .where(
                JobApplication.user_id == payload.user_id,
                JobApplication.job_posting_id == job.id,
            )
            .limit(1)
        )
        if existing_application_exists is not None:
            continue

        resumes = _select_resumes_for_job_generation(
            session,
            job=job,
            user_id=payload.user_id,
            resume_strategy=payload.resume_strategy,
        )
        if not resumes:
            continue

        jobs.append(job)
        if len(jobs) >= payload.limit:
            break

    if not jobs:
        return ApplicationsGenerateRunResponse(
            selected=0,
            processed=0,
            created=0,
            skipped=0,
            jobs=[],
            applications=[],
        )

    created = 0
    skipped = 0
    processed_jobs: list[int] = []
    application_ids: list[int] = []

    for job in jobs:
        result = generate_applications(
            ApplicationGenerateRequest(
                job_posting_id=job.id,
                user_id=payload.user_id,
                resume_strategy=payload.resume_strategy,
            ),
            session,
        )
        processed_jobs.append(job.id)
        created += result.created
        skipped += result.skipped
        application_ids.extend(result.applications)

    return ApplicationsGenerateRunResponse(
        selected=len(jobs),
        processed=len(processed_jobs),
        created=created,
        skipped=skipped,
        jobs=processed_jobs,
        applications=application_ids,
    )


@app.post("/applications/{application_id}/score", response_model=JobApplicationScoreResponse, tags=["applications"])
def store_application_score(
    application_id: int,
    score_payload: JobScoreWrite,
    session: Session = Depends(get_session),
):
    application = _get_application_by_id(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    apply_application_score(application, score_payload)
    _commit_or_fail(session)
    return _serialize_application_score(application)


@app.post("/applications/{application_id}/score/run", response_model=JobApplicationScoreResponse, tags=["applications"])
def run_application_score(
    application_id: int,
    payload: JobScoreRunRequest,
    session: Session = Depends(get_session),
):
    application = _get_application_by_id(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    try:
        result = score_application(
            session,
            application,
            classification_key=payload.classification_key,
            prompt_key=payload.prompt_key,
            force=payload.force,
        )
    except JobScoringSkipped as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _commit_or_fail(session)
    return _serialize_application_score(result.application)


@app.post("/applications/score/run", response_model=ApplicationsScoreRunResponse, status_code=202, tags=["applications"])
def run_applications_score(payload: ApplicationsScoreRunRequest, session: Session = Depends(get_session)):
    run = enqueue_application_score_run(
        session,
        limit=payload.limit,
        status=payload.status,
        user_id=payload.user_id,
        resume_id=payload.resume_id,
        job_posting_id=payload.job_posting_id,
        classification_key=payload.classification_key,
        prompt_key=payload.prompt_key,
        force=payload.force,
        callback_url=payload.callback_url,
    )
    _commit_or_fail(session)
    session.refresh(run)
    return ApplicationsScoreRunResponse(**serialize_application_score_run(session, run))


@app.post("/applications/{application_id}/notify", response_model=JobApplicationRead, tags=["applications"])
def mark_application_notified(
    application_id: int,
    notify_payload: JobNotifyWrite,
    session: Session = Depends(get_session),
):
    application = _get_application_by_id(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    apply_application_notification(application, notify_payload)
    _commit_or_fail(session)
    return _serialize_application(application)


@app.post("/applications/{application_id}/error", response_model=JobApplicationRead, tags=["applications"])
def mark_application_error(
    application_id: int,
    error_payload: JobErrorWrite,
    session: Session = Depends(get_session),
):
    application = _get_application_by_id(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    apply_application_error(application, error_payload)
    _commit_or_fail(session)
    return _serialize_application(application)


@app.post("/applications/{application_id}/status", response_model=JobApplicationRead, tags=["applications"])
def update_application_status(
    application_id: int,
    payload: ApplicationStatusWrite,
    session: Session = Depends(get_session),
):
    application = _get_application_by_id(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    apply_application_status(application, payload)
    _commit_or_fail(session)
    return _serialize_application(application)


@app.get("/applications/{application_id}/interview-rounds", response_model=InterviewRoundListResponse, tags=["applications"])
def list_interview_rounds(application_id: int, session: Session = Depends(get_session)):
    application = _get_application_by_id(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    items = session.scalars(
        select(InterviewRound)
        .where(InterviewRound.job_application_id == application_id)
        .order_by(InterviewRound.round_number.asc(), InterviewRound.id.asc())
    ).all()
    return InterviewRoundListResponse(total=len(items), items=[InterviewRoundRead.model_validate(item) for item in items])


@app.post("/applications/{application_id}/interview-rounds", response_model=InterviewRoundRead, tags=["applications"])
def create_interview_round(
    application_id: int,
    payload: InterviewRoundCreate,
    session: Session = Depends(get_session),
):
    application = _get_application_by_id(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    interview_round = InterviewRound(
        job_application_id=application_id,
        round_number=payload.round_number,
        stage_name=payload.stage_name,
        status=payload.status,
        notes=payload.notes,
        scheduled_at=payload.scheduled_at,
        completed_at=payload.completed_at,
    )
    session.add(interview_round)
    try:
        _commit_or_fail(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Interview round already exists for that application") from exc
    if application.status not in {"offer", "rejected", "withdrawn"}:
        application.status = "interview"
        _commit_or_fail(session)
    return InterviewRoundRead.model_validate(interview_round)


@app.get("/prompt-library", response_model=PromptLibraryListResponse, tags=["prompt-library"])
def list_prompt_library(
    session: Session = Depends(get_session),
    prompt_key: str | None = Query(default=None),
    prompt_type: str | None = None,
    prompt_version: int | None = Query(default=None, ge=1),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = select(PromptLibrary).order_by(PromptLibrary.id.desc())

    if prompt_key:
        query = query.where(PromptLibrary.prompt_key == prompt_key)
    if prompt_type:
        query = query.where(PromptLibrary.prompt_type == prompt_type)
    if prompt_version:
        query = query.where(PromptLibrary.prompt_version == prompt_version)
    if is_active is not None:
        query = query.where(PromptLibrary.is_active == is_active)

    items = session.scalars(query.offset(offset).limit(limit)).all()

    return PromptLibraryListResponse(total=len(items), items=[PromptLibraryRead.model_validate(item) for item in items])


@app.get("/prompt-library/{prompt_id}", response_model=PromptLibraryRead, tags=["prompt-library"])
def get_prompt_library(prompt_id: int, session: Session = Depends(get_session)):
    prompt = session.get(PromptLibrary, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' was not found")

    return PromptLibraryRead.model_validate(prompt)


@app.post("/prompt-library", response_model=PromptLibraryRead, tags=["prompt-library"])
def create_prompt_library(
    payload: PromptLibraryCreate,
    session: Session = Depends(get_session),
):
    prompt = PromptLibrary(
        prompt_key=payload.prompt_key,
        prompt_type=payload.prompt_type,
        prompt_version=payload.prompt_version,
        system_prompt=payload.system_prompt,
        user_prompt_template=payload.user_prompt_template,
        context=payload.context,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
        is_active=payload.is_active,
    )
    session.add(prompt)
    try:
        _commit_or_fail(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Prompt key/version/type combination already exists",
        ) from exc

    return PromptLibraryRead.model_validate(prompt)


@app.put("/prompt-library/{prompt_id}", response_model=PromptLibraryRead, tags=["prompt-library"])
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
    if payload.prompt_type is not None:
        prompt.prompt_type = payload.prompt_type
    if payload.prompt_version is not None:
        prompt.prompt_version = payload.prompt_version
    if payload.system_prompt is not None:
        prompt.system_prompt = payload.system_prompt
    if payload.user_prompt_template is not None:
        prompt.user_prompt_template = payload.user_prompt_template
    if payload.context is not None:
        prompt.context = payload.context
    if payload.max_tokens is not None:
        prompt.max_tokens = payload.max_tokens
    if payload.temperature is not None:
        prompt.temperature = payload.temperature
    if payload.is_active is not None:
        prompt.is_active = payload.is_active

    try:
        _commit_or_fail(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Prompt key/version/type combination already exists",
        ) from exc

    return PromptLibraryRead.model_validate(prompt)


@app.delete("/prompt-library/{prompt_id}", tags=["prompt-library"])
def delete_prompt_library(prompt_id: int, session: Session = Depends(get_session)):
    prompt = session.get(PromptLibrary, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' was not found")

    session.delete(prompt)
    _commit_or_fail(session)

    return {"deleted": True, "id": prompt_id}


@app.get("/jobs/hiringcafe", tags=["jobs"])
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
