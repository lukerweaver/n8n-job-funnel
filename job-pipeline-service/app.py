from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Annotated
import hashlib
import time
from urllib.parse import urlparse

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from sqlalchemy import Float, Integer, asc, case, cast, desc, exists, func, inspect, or_, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from config import settings
from database import Base, engine, get_session
from models import AppSettings, InterviewRound, JobApplication, JobPosting, PromptLibrary, Resume, Run, RunItem, User
from schemas import (
    AppSettingsRead,
    AppSettingsUpdate,
    ApplicationCreate,
    ApplicationGenerateRequest,
    ApplicationErrorWrite,
    ApplicationCountRead,
    ApplicationDurationMetricRead,
    ApplicationFunnelStageRead,
    ApplicationsGenerateRunRequest,
    ApplicationsGenerateRunResponse,
    ApplicationGenerateResponse,
    ApplicationNotificationWrite,
    ApplicationStatisticsResponse,
    DailyApplicationActivityRead,
    ApplicationScoreRunRequest,
    ApplicationScoreWrite,
    ApplicationsScoreRunRequest,
    ApplicationsScoreRunResponse,
    ApplicationLifecycleDatesUpdate,
    ApplicationStatusWrite,
    DailyIngestStatisticsRead,
    IngestStatisticsResponse,
    InterviewRoundCreate,
    InterviewRoundListResponse,
    InterviewRoundRead,
    InterviewRoundUpdate,
    JobIngestItem,
    JobIngestResponse,
    JobApplicationListResponse,
    JobApplicationRead,
    JobApplicationScoreResponse,
    JobClassificationResponse,
    JobClassificationRunRequest,
    JobListResponse,
    JobRead,
    OnboardingCompleteRequest,
    OnboardingStatusResponse,
    PasteJobRequest,
    PasteJobResponse,
    PromptLibraryCreate,
    PromptLibraryListResponse,
    PromptLibraryRead,
    PromptLibraryUpdate,
    ResumeCreate,
    ResumeListResponse,
    ResumeRead,
    ResumeUpdate,
    ScoreDistributionBucketRead,
    ScoreDistributionResponse,
    StatisticsResponse,
    RunApplicationsResponse,
    RunApplicationRead,
    RunItemsResponse,
    RunItemRead,
    RunListResponse,
    RunRead,
    UserCreate,
    UserListResponse,
    UserRead,
    JobsClassificationRunRequest,
    JobsClassificationRunResponse,
)
from services.classification_service import classify_job
from services.llm_client import LlmRequestError
from services.prompt_service import PromptResolutionError
from services.run_service import (
    EmptyRunSelectionError,
    RunWorker,
    enqueue_application_score_run,
    enqueue_classification_run,
    process_run,
    serialize_application_score_run,
    serialize_classification_run,
    serialize_run,
    serialize_runs,
)
from services.scoring_service import JobScoringSkipped, score_application
from services.settings_service import (
    DEFAULT_AUTOMATION_SETTINGS,
    DEFAULT_PROMPT_KEY,
    apply_provider_settings,
    apply_settings_update,
    get_or_create_app_settings,
    is_provider_configured,
    resolve_default_resume,
    seed_default_prompts,
    serialize_settings,
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


run_worker = RunWorker()
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
    "ghosted",
    "withdrawn",
    "pass",
}
ACTIVE_APPLICATION_STATUSES = {"applied", "screening", "interview"}
TERMINAL_APPLICATION_STATUSES = {"offer", "rejected", "ghosted", "withdrawn", "pass"}
HISTORICAL_APPLICATION_STATUSES = ACTIVE_APPLICATION_STATUSES | TERMINAL_APPLICATION_STATUSES
HIDDEN_APPLICATION_STATUSES = {"error"}
APPLICATION_TRANSITIONS = {
    "new": {"applied", "pass"},
    "scored": {"applied", "pass"},
    "tailored": {"applied", "pass"},
    "notified": {"applied", "pass"},
    "applied": {"screening", "interview", "offer", "rejected", "ghosted", "withdrawn", "pass"},
    "screening": {"interview", "offer", "rejected", "ghosted", "withdrawn", "pass"},
    "interview": {"offer", "rejected", "ghosted", "withdrawn", "pass"},
}

OPENAPI_TAGS = [
    {"name": "system", "description": "Health and operational utility endpoints."},
    {"name": "jobs", "description": "Job ingest, listing, and classification routes."},
    {"name": "applications", "description": "Application generation, scoring, notification, status, and interview lifecycle routes."},
    {"name": "runs", "description": "Async run inspection for classification and application scoring."},
    {"name": "statistics", "description": "Operational statistics and score distributions for the operator console."},
    {"name": "onboarding", "description": "First-run setup and simplified app configuration."},
    {"name": "settings", "description": "Simple and advanced product settings."},
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
    job.posted_at = payload.posted_at
    job.posted_at_raw = payload.posted_at_raw
    job.raw_payload = payload.raw_payload


def backfill_job_posted_metadata(job: JobPosting, payload: JobIngestItem) -> bool:
    changed = False
    if job.posted_at is None and payload.posted_at is not None:
        job.posted_at = payload.posted_at
        changed = True
    if job.posted_at_raw is None and payload.posted_at_raw:
        job.posted_at_raw = payload.posted_at_raw
        changed = True
    return changed


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


def _normalize_string_list(value: list[str] | None) -> list[str] | None:
    if not value:
        return None
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return normalized or None


def _serialize_onboarding_status(session: Session, settings: AppSettings) -> OnboardingStatusResponse:
    user = session.get(User, settings.default_user_id) if settings.default_user_id is not None else None
    resume = resolve_default_resume(session, settings)
    missing_steps: list[str] = []
    if user is None:
        missing_steps.append("profile")
    if resume is None:
        missing_steps.append("resume")
    if not is_provider_configured(settings):
        missing_steps.append("ai_provider")

    return OnboardingStatusResponse(
        completed=settings.onboarding_completed,
        settings=AppSettingsRead(**serialize_settings(settings)),
        default_user=UserRead.model_validate(user) if user is not None else None,
        default_resume=ResumeRead.model_validate(resume) if resume is not None else None,
        missing_steps=missing_steps,
    )


def _manual_job_id(payload: PasteJobRequest) -> str:
    base = payload.url or payload.description or ""
    if base.strip():
        digest = hashlib.sha256(base.strip().encode("utf-8")).hexdigest()[:16]
        return f"manual-{digest}"
    return f"manual-{int(time.time() * 1000)}"


def _enqueue_single_classification_run(
    session: Session,
    *,
    job: JobPosting,
    prompt_key: str | None,
) -> Run:
    run = Run(
        type="classification",
        status="queued",
        requested_status="",
        requested_source=job.source,
        classification_key=None,
        prompt_key=prompt_key,
        force=False,
        selected_count=1,
    )
    session.add(run)
    session.flush()
    session.add(
        RunItem(
            run_id=run.id,
            type="classification",
            job_posting_id=job.id,
            status="queued",
        )
    )
    return run


def _enqueue_single_scoring_run(
    session: Session,
    *,
    application: JobApplication,
    prompt_key: str | None,
) -> Run:
    run = Run(
        type="application_scoring",
        status="queued",
        requested_status=application.status,
        requested_source=None,
        classification_key=None,
        prompt_key=prompt_key,
        force=False,
        selected_count=1,
    )
    session.add(run)
    session.flush()
    session.add(
        RunItem(
            run_id=run.id,
            type="application_scoring",
            job_posting_id=application.job_posting_id,
            job_application_id=application.id,
            status="queued",
        )
    )
    return run


def _clear_job_classification(job: JobPosting) -> None:
    job.classification_key = None
    job.classification_prompt_version = None
    job.classification_provider = None
    job.classification_model = None
    job.classification_error = None
    job.classification_raw_response = None
    job.classified_at = None


def _clear_application_ai_outputs(application: JobApplication) -> None:
    application.status = "new"
    application.score = None
    application.recommendation = None
    application.justification = None
    application.screening_likelihood = None
    application.dimension_scores = None
    application.gating_flags = None
    application.strengths = None
    application.gaps = None
    application.missing_from_jd = None
    application.scoring_prompt_key = None
    application.scoring_prompt_version = None
    application.score_provider = None
    application.score_model = None
    application.score_raw_response = None
    application.score_error = None
    application.score_attempts = 0
    application.scored_at = None
    application.tailored_resume_content = None
    application.tailoring_prompt_key = None
    application.tailoring_prompt_version = None
    application.tailoring_provider = None
    application.tailoring_model = None
    application.tailoring_raw_response = None
    application.tailoring_error = None
    application.tailored_at = None
    application.last_error_at = None


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


class ApplicationResumeMatchConflictError(ValueError):
    pass


def _refresh_application_resume_match(session: Session, application: JobApplication) -> None:
    job = application.job_posting
    resumes = _select_resumes_for_job_generation(
        session,
        job=job,
        user_id=application.user_id,
        resume_strategy="classification_first",
    )
    if not resumes:
        return

    matched_resume = resumes[0]
    if matched_resume.id == application.resume_id:
        return

    existing = session.scalar(
        select(JobApplication).where(
            JobApplication.job_posting_id == application.job_posting_id,
            JobApplication.resume_id == matched_resume.id,
            JobApplication.id != application.id,
        )
    )
    if existing is not None:
        raise ApplicationResumeMatchConflictError(
            f"Application '{existing.id}' already exists for resume '{matched_resume.id}'"
        )

    application.resume_id = matched_resume.id
    application.resume = matched_resume
    session.flush()


def _normalize_list_or_dict_json(value: object) -> list | dict | None:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else None
    return None


def _normalize_string_list_json(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)] or None
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else None
    return None


def _normalize_float_dict_json(value: object) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None

    normalized: dict[str, float] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, (int, float)):
            normalized[key] = float(item)
    return normalized or None


def _serialize_application(application: JobApplication) -> JobApplicationRead:
    job = application.job_posting
    resume = application.resume
    scheduled_rounds = sorted(
        (
            interview_round
            for interview_round in application.interview_rounds
            if interview_round.status == "scheduled" and interview_round.scheduled_at is not None
        ),
        key=lambda interview_round: interview_round.scheduled_at,
    )
    next_interview = scheduled_rounds[0] if scheduled_rounds else None
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
        description=job.description if job is not None else None,
        posted_at=job.posted_at if job is not None else None,
        posted_at_raw=job.posted_at_raw if job is not None else None,
        classification_key=job.classification_key if job is not None else None,
        resume_name=resume.name if resume is not None else None,
        status=application.status,
        score=application.score,
        recommendation=application.recommendation,
        justification=application.justification,
        screening_likelihood=application.screening_likelihood,
        dimension_scores=_normalize_float_dict_json(application.dimension_scores),
        gating_flags=_normalize_string_list_json(application.gating_flags),
        strengths=_normalize_list_or_dict_json(application.strengths),
        gaps=_normalize_list_or_dict_json(application.gaps),
        missing_from_jd=_normalize_list_or_dict_json(application.missing_from_jd),
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
        applied_notes=application.applied_notes,
        screening_at=application.screening_at,
        screening_notes=application.screening_notes,
        offer_at=application.offer_at,
        offer_notes=application.offer_notes,
        rejected_at=application.rejected_at,
        rejected_notes=application.rejected_notes,
        ghosted_at=application.ghosted_at,
        ghosted_notes=application.ghosted_notes,
        withdrawn_at=application.withdrawn_at,
        withdrawn_notes=application.withdrawn_notes,
        passed_at=application.passed_at,
        passed_notes=application.passed_notes,
        last_error_at=application.last_error_at,
        next_interview_at=next_interview.scheduled_at if next_interview is not None else None,
        next_interview_stage=next_interview.stage_name if next_interview is not None else None,
        interview_rounds_total=len(application.interview_rounds),
        created_at=application.created_at,
        updated_at=application.updated_at,
    )


def _serialize_application_score(application: JobApplication) -> JobApplicationScoreResponse:
    return JobApplicationScoreResponse(
        id=application.id,
        job_posting_id=application.job_posting_id,
        resume_id=application.resume_id,
        resume_name=application.resume.name if application.resume is not None else None,
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


def apply_application_score(application: JobApplication, score_payload: ApplicationScoreWrite) -> None:
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


def apply_application_notification(
    application: JobApplication, notify_payload: ApplicationNotificationWrite
) -> None:
    application.notified_at = notify_payload.notified_at or utcnow()
    application.status = notify_payload.status


def apply_application_error(application: JobApplication, error_payload: ApplicationErrorWrite) -> None:
    application.last_error_at = error_payload.error_at or utcnow()
    application.status = "new" if error_payload.status == "error" else error_payload.status


def _validate_application_transition(current_status: str, next_status: str) -> None:
    if next_status not in ALLOWED_APPLICATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unsupported application status '{next_status}'")
    if current_status == next_status:
        return
    allowed_transitions = APPLICATION_TRANSITIONS.get(current_status)
    if allowed_transitions is None or next_status not in allowed_transitions:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition application from '{current_status}' to '{next_status}'",
        )


def apply_application_status(application: JobApplication, payload: ApplicationStatusWrite) -> None:
    _validate_application_transition(application.status, payload.status)
    application.status = payload.status
    if payload.status == "applied":
        application.applied_at = payload.applied_at or utcnow()
        application.applied_notes = payload.applied_notes
    elif payload.status == "screening":
        application.screening_at = payload.screening_at or utcnow()
        application.screening_notes = payload.screening_notes
    elif payload.status == "offer":
        application.offer_at = payload.offer_at or utcnow()
        application.offer_notes = payload.offer_notes
    elif payload.status == "rejected":
        application.rejected_at = payload.rejected_at or utcnow()
        application.rejected_notes = payload.rejected_notes
    elif payload.status == "ghosted":
        application.ghosted_at = payload.ghosted_at or utcnow()
        application.ghosted_notes = payload.ghosted_notes
    elif payload.status == "withdrawn":
        application.withdrawn_at = payload.withdrawn_at or utcnow()
        application.withdrawn_notes = payload.withdrawn_notes
    elif payload.status == "pass":
        application.passed_at = payload.passed_at or utcnow()
        application.passed_notes = payload.passed_notes


def apply_application_lifecycle_dates(application: JobApplication, payload: ApplicationLifecycleDatesUpdate) -> None:
    if "applied_at" in payload.model_fields_set:
        application.applied_at = payload.applied_at
    if "applied_notes" in payload.model_fields_set:
        application.applied_notes = payload.applied_notes
    if "screening_at" in payload.model_fields_set:
        application.screening_at = payload.screening_at
    if "screening_notes" in payload.model_fields_set:
        application.screening_notes = payload.screening_notes
    if "offer_at" in payload.model_fields_set:
        application.offer_at = payload.offer_at
    if "offer_notes" in payload.model_fields_set:
        application.offer_notes = payload.offer_notes
    if "rejected_at" in payload.model_fields_set:
        application.rejected_at = payload.rejected_at
    if "rejected_notes" in payload.model_fields_set:
        application.rejected_notes = payload.rejected_notes
    if "ghosted_at" in payload.model_fields_set:
        application.ghosted_at = payload.ghosted_at
    if "ghosted_notes" in payload.model_fields_set:
        application.ghosted_notes = payload.ghosted_notes
    if "withdrawn_at" in payload.model_fields_set:
        application.withdrawn_at = payload.withdrawn_at
    if "withdrawn_notes" in payload.model_fields_set:
        application.withdrawn_notes = payload.withdrawn_notes
    if "passed_at" in payload.model_fields_set:
        application.passed_at = payload.passed_at
    if "passed_notes" in payload.model_fields_set:
        application.passed_notes = payload.passed_notes


def apply_interview_round_updates(interview_round: InterviewRound, payload: InterviewRoundUpdate) -> None:
    if "round_number" in payload.model_fields_set:
        interview_round.round_number = payload.round_number
    if "stage_name" in payload.model_fields_set:
        interview_round.stage_name = payload.stage_name
    if "status" in payload.model_fields_set:
        interview_round.status = payload.status
    if "notes" in payload.model_fields_set:
        interview_round.notes = payload.notes
    if "scheduled_at" in payload.model_fields_set:
        interview_round.scheduled_at = payload.scheduled_at
    if "completed_at" in payload.model_fields_set:
        interview_round.completed_at = payload.completed_at


def _get_run_by_id(session: Session, run_id: int) -> Run | None:
    return session.get(Run, run_id)


def _normalize_text_search(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _resolve_application_sort(
    sort_by: str,
    sort_order: str,
):
    normalized_order = sort_order.lower()
    allowed_fields = {
        "created_at": JobApplication.created_at,
        "updated_at": JobApplication.updated_at,
        "score": JobApplication.score,
        "status": JobApplication.status,
        "scored_at": JobApplication.scored_at,
        "posted_at": JobPosting.posted_at,
    }
    column = allowed_fields.get(sort_by)
    if column is None:
        raise HTTPException(status_code=400, detail=f"Unsupported application sort field '{sort_by}'")
    if normalized_order not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail=f"Unsupported application sort order '{sort_order}'")
    return asc(column) if normalized_order == "asc" else desc(column)


def _active_application_ordering():
    max_round = (
        select(func.coalesce(func.max(InterviewRound.round_number), 0))
        .where(InterviewRound.job_application_id == JobApplication.id)
        .scalar_subquery()
    )
    first_interview_at = (
        select(func.min(func.coalesce(InterviewRound.scheduled_at, InterviewRound.completed_at, InterviewRound.created_at)))
        .where(InterviewRound.job_application_id == JobApplication.id)
        .scalar_subquery()
    )
    has_interview = or_(JobApplication.status == "interview", max_round > 0)
    stage_rank = case(
        (has_interview, 0),
        (JobApplication.status == "screening", 1),
        (JobApplication.status == "applied", 2),
        else_=3,
    )
    stage_date = case(
        (has_interview, first_interview_at),
        (JobApplication.status == "screening", JobApplication.screening_at),
        (JobApplication.status == "applied", JobApplication.applied_at),
        else_=JobApplication.updated_at,
    )
    return (
        asc(stage_rank),
        desc(max_round),
        asc(func.coalesce(stage_date, JobApplication.updated_at, JobApplication.created_at)),
        asc(JobApplication.id),
    )


def _resolve_run_application_sort(
    sort_by: str,
    sort_order: str,
):
    normalized_order = sort_order.lower()
    allowed_fields = {
        "score": JobApplication.score,
        "screening_likelihood": JobApplication.screening_likelihood,
        "company_name": JobPosting.company_name,
        "title": JobPosting.title,
        "classification_key": JobPosting.classification_key,
        "classified_at": JobPosting.classified_at,
        "scored_at": JobApplication.scored_at,
        "created_at": RunItem.created_at,
    }
    column = allowed_fields.get(sort_by)
    if column is None:
        raise HTTPException(status_code=400, detail=f"Unsupported run application sort field '{sort_by}'")
    if normalized_order not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail=f"Unsupported run application sort order '{sort_order}'")
    return asc(column) if normalized_order == "asc" else desc(column)


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

    type_map = {
        "classification_key": "VARCHAR(100)",
        "classification_prompt_version": "INTEGER",
        "classification_provider": "VARCHAR(100)",
        "classification_model": "VARCHAR(255)",
        "classification_error": "TEXT",
        "classification_raw_response": "TEXT",
        "classified_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
        "posted_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
        "posted_at_raw": "TEXT",
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
    try:
        unique_constraints = inspector.get_unique_constraints("prompt_library")
    except (AttributeError, NotImplementedError):
        unique_constraints = []
    unique_constraint_names = {constraint["name"] for constraint in unique_constraints if constraint.get("name")}

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

    constraint_statements: list[str] = []
    if engine.dialect.name == "postgresql":
        if "uq_prompt_library_key_version" in unique_constraint_names:
            constraint_statements.append(
                "ALTER TABLE prompt_library DROP CONSTRAINT IF EXISTS uq_prompt_library_key_version"
            )
        if "uq_prompt_library_key_version_type" not in unique_constraint_names:
            constraint_statements.append(
                "ALTER TABLE prompt_library "
                "ADD CONSTRAINT uq_prompt_library_key_version_type "
                "UNIQUE (prompt_key, prompt_version, prompt_type)"
            )

    if not statements and not constraint_statements:
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
        for statement in constraint_statements:
            connection.execute(text(statement))


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


def ensure_application_schema() -> None:
    inspector = inspect(engine)

    application_columns = {column["name"] for column in inspector.get_columns("job_applications")}
    interview_round_columns = {column["name"] for column in inspector.get_columns("interview_rounds")}
    datetime_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"

    application_statements: list[str] = []
    if "ghosted_at" not in application_columns:
        application_statements.append(f"ALTER TABLE job_applications ADD COLUMN ghosted_at {datetime_type}")
    if "passed_at" not in application_columns:
        application_statements.append(f"ALTER TABLE job_applications ADD COLUMN passed_at {datetime_type}")
    if "screening_at" not in application_columns:
        application_statements.append(f"ALTER TABLE job_applications ADD COLUMN screening_at {datetime_type}")
    if "applied_notes" not in application_columns:
        application_statements.append("ALTER TABLE job_applications ADD COLUMN applied_notes TEXT")
    if "screening_notes" not in application_columns:
        application_statements.append("ALTER TABLE job_applications ADD COLUMN screening_notes TEXT")
    if "offer_notes" not in application_columns:
        application_statements.append("ALTER TABLE job_applications ADD COLUMN offer_notes TEXT")
    if "rejected_notes" not in application_columns:
        application_statements.append("ALTER TABLE job_applications ADD COLUMN rejected_notes TEXT")
    if "ghosted_notes" not in application_columns:
        application_statements.append("ALTER TABLE job_applications ADD COLUMN ghosted_notes TEXT")
    if "withdrawn_notes" not in application_columns:
        application_statements.append("ALTER TABLE job_applications ADD COLUMN withdrawn_notes TEXT")
    if "passed_notes" not in application_columns:
        application_statements.append("ALTER TABLE job_applications ADD COLUMN passed_notes TEXT")

    interview_round_statements: list[str] = []
    if "status" not in interview_round_columns:
        interview_round_statements.append(
            "ALTER TABLE interview_rounds ADD COLUMN status VARCHAR(50) DEFAULT 'scheduled'"
        )

    if not application_statements and not interview_round_statements:
        return

    with engine.begin() as connection:
        for statement in application_statements:
            connection.execute(text(statement))
        for statement in interview_round_statements:
            connection.execute(text(statement))
        if "status" not in interview_round_columns:
            connection.execute(
                text(
                    """
                    UPDATE interview_rounds
                    SET status = 'scheduled'
                    WHERE status IS NULL
                    """
                )
            )


def ensure_run_schema() -> None:
    inspector = inspect(engine)

    run_table = "runs"
    item_table = "run_items"
    try:
        run_columns = {column["name"] for column in inspector.get_columns(run_table)}
    except Exception:
        legacy_run_columns = {column["name"] for column in inspector.get_columns("score_runs")}
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE score_runs RENAME TO runs"))
        run_columns = legacy_run_columns
    run_type = "VARCHAR(50)"
    run_statements = []
    if "type" not in run_columns:
        run_statements.append(f"ALTER TABLE {run_table} ADD COLUMN type {run_type}")
    if "classification_key" not in run_columns:
        run_statements.append(f"ALTER TABLE {run_table} ADD COLUMN classification_key VARCHAR(255)")

    try:
        item_columns = {column["name"] for column in inspector.get_columns(item_table)}
    except Exception:
        legacy_item_columns = {column["name"] for column in inspector.get_columns("score_run_items")}
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE score_run_items RENAME TO run_items"))
        item_columns = legacy_item_columns
    item_statements = []
    if "type" not in item_columns:
        item_statements.append(f"ALTER TABLE {item_table} ADD COLUMN type {run_type}")
    if "run_id" not in item_columns:
        item_statements.append(f"ALTER TABLE {item_table} ADD COLUMN run_id INTEGER")
    if "job_application_id" not in item_columns:
        item_statements.append(f"ALTER TABLE {item_table} ADD COLUMN job_application_id INTEGER")

    if not run_statements and not item_statements:
        return

    with engine.begin() as connection:
        for statement in run_statements:
            connection.execute(text(statement))
        for statement in item_statements:
            connection.execute(text(statement))
        if "type" not in run_columns:
            connection.execute(text(f"UPDATE {run_table} SET type = 'scoring' WHERE type IS NULL"))
        if "classification_key" not in run_columns:
            connection.execute(
                text(
                    """
                    UPDATE runs
                    SET classification_key = prompt_key
                    WHERE classification_key IS NULL AND prompt_key IS NOT NULL
                    """
                )
            )
        if "run_id" not in item_columns:
            connection.execute(text(f"UPDATE {item_table} SET run_id = score_run_id WHERE run_id IS NULL"))
        if "type" not in item_columns:
            connection.execute(text(f"UPDATE {item_table} SET type = 'scoring' WHERE type IS NULL"))


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
def run_startup_backfill(session: Session) -> None:
    _backfill_resume_classification_keys(session)
    _backfill_resume_defaults(session)
    settings = get_or_create_app_settings(session)
    seed_default_prompts(session, settings=settings)
    if settings.default_user_id is None:
        settings.default_user_id = session.scalar(select(User.id).order_by(User.id.asc()).limit(1))
    session.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_job_postings_schema()
    ensure_prompt_library_schema()
    ensure_resumes_schema()
    ensure_application_schema()
    ensure_run_schema()
    with Session(engine) as session:
        run_startup_backfill(session)
    run_worker.start()
    yield
    run_worker.stop()


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


@app.get("/onboarding/status", response_model=OnboardingStatusResponse, tags=["onboarding"])
def get_onboarding_status(session: Session = Depends(get_session)):
    settings = get_or_create_app_settings(session)
    _commit_or_fail(session)
    return _serialize_onboarding_status(session, settings)


@app.post("/onboarding/complete", response_model=OnboardingStatusResponse, tags=["onboarding"])
def complete_onboarding(payload: OnboardingCompleteRequest, session: Session = Depends(get_session)):
    settings = get_or_create_app_settings(session)
    seed_default_prompts(session, settings=settings)

    user = session.get(User, settings.default_user_id) if settings.default_user_id is not None else None
    if user is None:
        user = User(
            name=payload.profile_name.strip(),
            email=f"default-{int(time.time())}@job-funnel.local",
        )
        session.add(user)
        session.flush()
        settings.default_user_id = user.id
    else:
        user.name = payload.profile_name.strip()

    resume = resolve_default_resume(session, settings)
    resume_name = (payload.resume_name or "Default Resume").strip()
    if resume is None:
        resume = Resume(
            user_id=user.id,
            name=resume_name,
            prompt_key=settings.default_prompt_key or DEFAULT_PROMPT_KEY,
            classification_key=None,
            content=payload.resume_content,
            is_active=True,
            is_default=True,
        )
        session.add(resume)
        session.flush()
    else:
        resume.name = resume_name
        resume.content = payload.resume_content
        resume.prompt_key = settings.default_prompt_key or DEFAULT_PROMPT_KEY
        resume.is_active = True
        resume.is_default = True

    _normalize_user_default_resume(session, user.id, selected_resume=resume)
    settings.profile_name = payload.profile_name.strip()
    settings.target_roles = _normalize_string_list(payload.target_roles)
    settings.default_prompt_key = settings.default_prompt_key or DEFAULT_PROMPT_KEY
    settings.scoring_preferences = settings.scoring_preferences or {}
    settings.automation_settings = settings.automation_settings or DEFAULT_AUTOMATION_SETTINGS
    settings.automation_state = settings.automation_state or {}
    apply_provider_settings(settings, payload.provider)
    settings.onboarding_completed = True

    _commit_or_fail(session)
    return _serialize_onboarding_status(session, settings)


@app.get("/settings", response_model=AppSettingsRead, tags=["settings"])
def get_settings(session: Session = Depends(get_session)):
    settings = get_or_create_app_settings(session)
    _commit_or_fail(session)
    return AppSettingsRead(**serialize_settings(settings))


@app.put("/settings", response_model=AppSettingsRead, tags=["settings"])
def update_settings(payload: AppSettingsUpdate, session: Session = Depends(get_session)):
    settings = get_or_create_app_settings(session)
    apply_settings_update(settings, payload)
    _commit_or_fail(session)
    return AppSettingsRead(**serialize_settings(settings))


@app.post("/jobs/paste", response_model=PasteJobResponse, tags=["jobs"])
def paste_job(payload: PasteJobRequest, session: Session = Depends(get_session)):
    settings = get_or_create_app_settings(session)
    seed_default_prompts(session, settings=settings)
    user_id = payload.user_id or settings.default_user_id
    if user_id is None:
        raise HTTPException(status_code=409, detail="Complete onboarding before pasting a job")

    user = _get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' was not found")

    resume = resolve_default_resume(session, settings)
    if resume is None or resume.user_id != user.id:
        resume = session.scalar(
            select(Resume)
            .where(Resume.user_id == user.id, Resume.is_active.is_(True))
            .order_by(Resume.is_default.desc(), Resume.id.asc())
            .limit(1)
        )
    if resume is None:
        raise HTTPException(status_code=409, detail="Add a resume before pasting a job")

    description = payload.description.strip() if payload.description else None
    if payload.input_type == "url" and (not payload.url or not payload.url.strip()):
        raise HTTPException(status_code=422, detail="Job URL is required")
    if not description:
        raise HTTPException(status_code=422, detail="Job description is required")

    job_id = _manual_job_id(payload)
    job = session.scalar(select(JobPosting).where(JobPosting.job_id == job_id))
    if job is None:
        job = JobPosting(job_id=job_id)
        session.add(job)
    description_changed = job.id is not None and (job.description or "") != description
    if description_changed:
        _clear_job_classification(job)
    job.source = "manual-entry"
    job.company_name = payload.company_name.strip() if payload.company_name else None
    job.title = payload.title.strip() if payload.title else None
    job.apply_url = payload.url.strip() if payload.url else None
    job.description = description
    job.raw_payload = {
        "input_type": payload.input_type,
        "url": payload.url,
    }
    session.flush()

    application = session.scalar(
        select(JobApplication).where(
            JobApplication.job_posting_id == job.id,
            JobApplication.resume_id == resume.id,
        )
    )
    if application is None:
        application = JobApplication(
            user_id=user.id,
            job_posting_id=job.id,
            resume_id=resume.id,
            status="new",
        )
        session.add(application)
        session.flush()
    else:
        application.user_id = user.id
        application.status = "new" if application.status in {"error"} else application.status
    if description_changed:
        _clear_application_ai_outputs(application)

    run_ids: list[int] = []
    provider_configured = is_provider_configured(settings)
    message: str | None = None
    if payload.process_now and provider_configured:
        if job.classification_key is None:
            classification_run = _enqueue_single_classification_run(
                session,
                job=job,
                prompt_key=settings.default_prompt_key or DEFAULT_PROMPT_KEY,
            )
            run_ids.append(classification_run.id)
        if application.status == "new":
            scoring_run = _enqueue_single_scoring_run(
                session,
                application=application,
                prompt_key=settings.default_prompt_key or DEFAULT_PROMPT_KEY,
            )
            run_ids.append(scoring_run.id)
        settings.automation_state = {
            **(settings.automation_state if isinstance(settings.automation_state, dict) else {}),
            "last_manual_trigger_at": utcnow().isoformat(),
        }
    elif payload.process_now:
        message = "AI provider is not configured yet. The job was saved and can be processed after setup."

    _commit_or_fail(session)

    if payload.mode == "sync" and run_ids:
        for run_id in run_ids:
            process_run(run_id)
        session.refresh(job)
        session.refresh(application)

    status = "scored" if application.scored_at is not None else ("queued" if run_ids else "saved")
    return PasteJobResponse(
        job=JobRead.model_validate(job),
        application=_serialize_application(application),
        status=status,
        run_ids=run_ids,
        provider_configured=provider_configured,
        message=message,
    )


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

        if backfill_job_posted_metadata(job, item):
            updated += 1
        else:
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
    source: str | None = None,
    classification_key: str | None = None,
    q: str | None = None,
    has_classification: bool | None = None,
    has_applications: bool | None = None,
    classified_since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = select(JobPosting).order_by(JobPosting.created_at.desc())
    count_query = select(JobPosting)
    search_term = _normalize_text_search(q)

    if source:
        query = query.where(JobPosting.source == source)
        count_query = count_query.where(JobPosting.source == source)

    if classification_key:
        query = query.where(JobPosting.classification_key == classification_key)
        count_query = count_query.where(JobPosting.classification_key == classification_key)

    if search_term is not None:
        pattern = f"%{search_term}%"
        search_filter = or_(
            JobPosting.job_id.ilike(pattern),
            JobPosting.company_name.ilike(pattern),
            JobPosting.title.ilike(pattern),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if has_classification is True:
        query = query.where(JobPosting.classification_key.is_not(None))
        count_query = count_query.where(JobPosting.classification_key.is_not(None))
    elif has_classification is False:
        query = query.where(JobPosting.classification_key.is_(None))
        count_query = count_query.where(JobPosting.classification_key.is_(None))

    if has_applications is not None:
        application_exists = exists(
            select(JobApplication.id).where(JobApplication.job_posting_id == JobPosting.id)
        )
        if has_applications:
            query = query.where(application_exists)
            count_query = count_query.where(application_exists)
        else:
            query = query.where(~application_exists)
            count_query = count_query.where(~application_exists)

    if classified_since is not None:
        query = query.where(JobPosting.classified_at.is_not(None), JobPosting.classified_at > classified_since)
        count_query = count_query.where(JobPosting.classified_at.is_not(None), JobPosting.classified_at > classified_since)

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
    try:
        run = enqueue_classification_run(
            session,
            limit=payload.limit,
            source=payload.source,
            classification_key=payload.classification_key,
            prompt_key=payload.prompt_key,
            force=payload.force,
            callback_url=payload.callback_url,
        )
    except EmptyRunSelectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _commit_or_fail(session)
    session.refresh(run)
    return JobsClassificationRunResponse(**serialize_classification_run(session, run))


@app.get("/runs", response_model=RunListResponse, tags=["runs"])
def list_runs(
    session: Session = Depends(get_session),
    type: str | None = None,
    status: str | None = None,
    requested_status: str | None = None,
    requested_source: str | None = None,
    classification_key: str | None = None,
    prompt_key: str | None = None,
    callback_status: str | None = None,
    created_since: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    query = select(Run).order_by(Run.created_at.desc())
    count_query = select(Run)

    if type:
        query = query.where(Run.type == type)
        count_query = count_query.where(Run.type == type)
    if status:
        query = query.where(Run.status == status)
        count_query = count_query.where(Run.status == status)
    if requested_status is not None:
        query = query.where(Run.requested_status == requested_status)
        count_query = count_query.where(Run.requested_status == requested_status)
    if requested_source:
        query = query.where(Run.requested_source == requested_source)
        count_query = count_query.where(Run.requested_source == requested_source)
    if classification_key:
        query = query.where(Run.classification_key == classification_key)
        count_query = count_query.where(Run.classification_key == classification_key)
    if prompt_key:
        query = query.where(Run.prompt_key == prompt_key)
        count_query = count_query.where(Run.prompt_key == prompt_key)
    if callback_status:
        query = query.where(Run.callback_status == callback_status)
        count_query = count_query.where(Run.callback_status == callback_status)
    if created_since is not None:
        query = query.where(Run.created_at > created_since)
        count_query = count_query.where(Run.created_at > created_since)

    items = session.scalars(query.offset(offset).limit(limit)).all()
    total = len(session.scalars(count_query).all())
    return RunListResponse(total=total, items=[RunRead(**payload) for payload in serialize_runs(session, items)])


@app.get("/runs/{run_id}", response_model=RunRead, tags=["runs"])
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = _get_run_by_id(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' was not found")

    return RunRead(**serialize_run(session, run))


@app.get("/runs/{run_id}/applications", response_model=RunApplicationsResponse, tags=["runs"])
def list_run_applications(
    run_id: int,
    session: Session = Depends(get_session),
    run_item_status: str | None = None,
    score_min: float | None = None,
    score_max: float | None = None,
    sort_by: str = "score",
    sort_order: str = "desc",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    run = _get_run_by_id(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' was not found")

    order_by = _resolve_run_application_sort(sort_by, sort_order)
    secondary_order = asc(RunItem.id) if sort_order.lower() == "asc" else desc(RunItem.id)
    query = (
        select(RunItem, JobApplication, JobPosting, Resume)
        .outerjoin(JobApplication, RunItem.job_application_id == JobApplication.id)
        .outerjoin(
            JobPosting,
            or_(RunItem.job_posting_id == JobPosting.id, JobApplication.job_posting_id == JobPosting.id),
        )
        .outerjoin(Resume, JobApplication.resume_id == Resume.id)
        .where(RunItem.run_id == run_id)
        .where(or_(JobApplication.id.is_(None), JobApplication.status.not_in(HIDDEN_APPLICATION_STATUSES)))
        .order_by(order_by, secondary_order)
    )
    count_query = (
        select(RunItem.id)
        .outerjoin(JobApplication, RunItem.job_application_id == JobApplication.id)
        .where(RunItem.run_id == run_id)
        .where(or_(JobApplication.id.is_(None), JobApplication.status.not_in(HIDDEN_APPLICATION_STATUSES)))
    )

    if run_item_status:
        query = query.where(RunItem.status == run_item_status)
        count_query = count_query.where(RunItem.status == run_item_status)
    if score_min is not None:
        query = query.where(JobApplication.score.is_not(None), JobApplication.score >= score_min)
        count_query = count_query.where(JobApplication.score.is_not(None), JobApplication.score >= score_min)
    if score_max is not None:
        query = query.where(JobApplication.score.is_not(None), JobApplication.score <= score_max)
        count_query = count_query.where(JobApplication.score.is_not(None), JobApplication.score <= score_max)

    rows = session.execute(query.offset(offset).limit(limit)).all()
    total = len(session.scalars(count_query).all())
    return RunApplicationsResponse(
        total=total,
        items=[
            RunApplicationRead(
                run_item_id=item.id,
                run_item_status=item.status,
                run_item_error_message=item.error_message,
                job_application_id=application.id if application is not None else None,
                job_posting_id=job.id if job is not None else None,
                resume_id=resume.id if resume is not None else None,
                job_id=job.job_id if job is not None else None,
                company_name=job.company_name if job is not None else None,
                title=job.title if job is not None else None,
                score=application.score if application is not None else None,
                screening_likelihood=application.screening_likelihood if application is not None else None,
                classification_key=job.classification_key if job is not None else None,
                classification_error=job.classification_error if job is not None else None,
                apply_url=job.apply_url if job is not None else None,
                yearly_min_compensation=job.yearly_min_compensation if job is not None else None,
                yearly_max_compensation=job.yearly_max_compensation if job is not None else None,
                posted_at=job.posted_at if job is not None else None,
                posted_at_raw=job.posted_at_raw if job is not None else None,
                recommendation=application.recommendation if application is not None else None,
                resume_name=resume.name if resume is not None else None,
                classified_at=job.classified_at if job is not None else None,
                scored_at=application.scored_at if application is not None else None,
            )
            for item, application, job, resume in rows
        ],
    )


@app.get("/runs/{run_id}/items", response_model=RunItemsResponse, tags=["runs"])
def list_run_items(run_id: int, session: Session = Depends(get_session)):
    run = _get_run_by_id(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' was not found")

    items = session.scalars(
        select(RunItem)
        .where(RunItem.run_id == run_id)
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


@app.get("/statistics", response_model=StatisticsResponse, tags=["statistics"])
def get_statistics(
    session: Session = Depends(get_session),
    days: Annotated[int | None, Query(ge=7, le=3650)] = 90,
    high_score_threshold: float = Query(default=18),
    bucket_size: float = Query(default=2, gt=0, le=20),
):
    cutoff_datetime: datetime | None = None
    if days is not None:
        cutoff_date = utcnow().date() - timedelta(days=days - 1)
        cutoff_datetime = datetime.combine(cutoff_date, datetime.min.time(), tzinfo=timezone.utc)

    created_date = func.date(JobPosting.created_at)
    application_created_date = func.date(JobApplication.created_at)

    daily_counts_query = select(
        created_date.label("created_date"),
        func.count(JobPosting.id).label("ingested_job_postings"),
    )
    if cutoff_datetime is not None:
        daily_counts_query = daily_counts_query.where(JobPosting.created_at >= cutoff_datetime)
    daily_counts = daily_counts_query.group_by(created_date).subquery()

    daily_high_counts_query = select(
        application_created_date.label("created_date"),
        func.count(func.distinct(JobApplication.job_posting_id)).label("high_job_postings"),
    ).where(JobApplication.score.is_not(None), JobApplication.score >= high_score_threshold)
    if cutoff_datetime is not None:
        daily_high_counts_query = daily_high_counts_query.where(JobApplication.created_at >= cutoff_datetime)
    daily_high_counts = daily_high_counts_query.group_by(application_created_date).subquery()

    high_job_postings = func.coalesce(daily_high_counts.c.high_job_postings, 0)
    percentage_high = (
        cast(high_job_postings, Float) * 100.0 / func.nullif(cast(daily_counts.c.ingested_job_postings, Float), 0.0)
    )

    daily_statistics_query = (
        select(
            daily_counts.c.created_date,
            daily_counts.c.ingested_job_postings,
            func.avg(daily_counts.c.ingested_job_postings).over(
                order_by=daily_counts.c.created_date,
                rows=(-6, 0),
            ).label("rolling_7_day_avg_ingested"),
            high_job_postings.label("high_job_postings"),
            func.avg(high_job_postings).over(
                order_by=daily_counts.c.created_date,
                rows=(-6, 0),
            ).label("rolling_7_day_avg_high"),
            percentage_high.label("percentage_high"),
            func.avg(percentage_high).over(
                order_by=daily_counts.c.created_date,
                rows=(-6, 0),
            ).label("rolling_7_day_percentage"),
        )
        .select_from(daily_counts.outerjoin(daily_high_counts, daily_counts.c.created_date == daily_high_counts.c.created_date))
        .order_by(daily_counts.c.created_date.desc())
    )

    daily_rows = session.execute(daily_statistics_query).all()
    daily_items = [
        DailyIngestStatisticsRead(
            created_date=datetime.strptime(str(row.created_date), "%Y-%m-%d").date(),
            ingested_job_postings=int(row.ingested_job_postings or 0),
            rolling_7_day_avg_ingested=float(row.rolling_7_day_avg_ingested or 0),
            high_job_postings=int(row.high_job_postings or 0),
            rolling_7_day_avg_high=float(row.rolling_7_day_avg_high or 0),
            percentage_high=float(row.percentage_high) if row.percentage_high is not None else None,
            rolling_7_day_percentage=float(row.rolling_7_day_percentage) if row.rolling_7_day_percentage is not None else None,
        )
        for row in daily_rows
    ]

    score_summary_query = select(
        func.count(JobApplication.id).label("total_scored_jobs"),
        func.avg(JobApplication.score).label("average_score"),
        func.min(JobApplication.score).label("minimum_score"),
        func.max(JobApplication.score).label("maximum_score"),
    ).where(JobApplication.score.is_not(None))
    if cutoff_datetime is not None:
        score_summary_query = score_summary_query.where(JobApplication.created_at >= cutoff_datetime)
    score_summary_row = session.execute(score_summary_query).one()

    bucket_start = (cast((JobApplication.score - 0.000000001) / bucket_size, Integer) * bucket_size).label("bucket_start")
    bucket_query = (
        select(
            bucket_start,
            func.count(JobApplication.id).label("count"),
        )
        .where(JobApplication.score.is_not(None))
    )
    if cutoff_datetime is not None:
        bucket_query = bucket_query.where(JobApplication.created_at >= cutoff_datetime)
    bucket_rows = session.execute(
        bucket_query.group_by(bucket_start).order_by(bucket_start.asc())
    ).all()

    score_distribution = ScoreDistributionResponse(
        total_scored_jobs=int(score_summary_row.total_scored_jobs or 0),
        average_score=float(score_summary_row.average_score) if score_summary_row.average_score is not None else None,
        minimum_score=float(score_summary_row.minimum_score) if score_summary_row.minimum_score is not None else None,
        maximum_score=float(score_summary_row.maximum_score) if score_summary_row.maximum_score is not None else None,
        bucket_size=bucket_size,
        buckets=[
            ScoreDistributionBucketRead(
                bucket_start=float(row.bucket_start),
                bucket_end=float(row.bucket_start + bucket_size),
                count=int(row.count),
            )
            for row in bucket_rows
        ],
    )

    return StatisticsResponse(
        ingested_jobs=IngestStatisticsResponse(
            total_days=len(daily_items),
            total_ingested_job_postings=sum(item.ingested_job_postings for item in daily_items),
            total_high_job_postings=sum(item.high_job_postings for item in daily_items),
            average_daily_ingested=(
                sum(item.ingested_job_postings for item in daily_items) / len(daily_items) if daily_items else 0.0
            ),
            average_daily_high=(
                sum(item.high_job_postings for item in daily_items) / len(daily_items) if daily_items else 0.0
            ),
            items=daily_items,
        ),
        score_distribution=score_distribution,
    )


@app.get("/statistics/job-postings", response_model=StatisticsResponse, tags=["statistics"])
def get_job_posting_statistics(
    session: Session = Depends(get_session),
    days: Annotated[int | None, Query(ge=7, le=3650)] = 90,
    high_score_threshold: float = Query(default=18),
    bucket_size: float = Query(default=2, gt=0, le=20),
):
    return get_statistics(session, days=days, high_score_threshold=high_score_threshold, bucket_size=bucket_size)


def _round_percentage(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 2)


def _round_days(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _application_status_label(status: str) -> str:
    return {
        "new": "Submitted",
        "scored": "Submitted",
        "tailored": "Submitted",
        "notified": "Submitted",
        "applied": "Submitted",
        "screening": "Screening",
        "interview": "Interview",
        "offer": "Offer",
        "rejected": "Not Selected",
        "ghosted": "Ghosted",
        "withdrawn": "Withdrawn",
        "pass": "Passed",
    }.get(status, status.replace("_", " ").title())


def _application_stage_label(application: JobApplication, max_round: int) -> str:
    if max_round >= 2:
        return f"Round {max_round}"
    if application.screening_at is not None or application.status in {"screening", "interview", "offer"}:
        return "Screening"
    return "Submitted"


def _date_range(start: date, end: date) -> list[date]:
    days = (end - start).days
    if days < 0:
        return []
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def _add_activity(activity_by_date: dict[date, dict[str, int]], key: str, value: datetime | None) -> None:
    if value is None:
        return
    activity_by_date.setdefault(
        value.date(),
        {"applications": 0, "screenings": 0, "interviews": 0, "rejections": 0, "offers": 0},
    )[key] += 1


def _duration_days(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds() / 86400


def _duration_metric(label: str, values: list[float]) -> ApplicationDurationMetricRead:
    if not values:
        return ApplicationDurationMetricRead(label=label, count=0)
    return ApplicationDurationMetricRead(
        label=label,
        count=len(values),
        average_days=_round_days(sum(values) / len(values)),
        minimum_days=_round_days(min(values)),
        maximum_days=_round_days(max(values)),
    )


@app.get("/statistics/applications", response_model=ApplicationStatisticsResponse, tags=["statistics"])
def get_application_statistics(
    session: Session = Depends(get_session),
    days: Annotated[int | None, Query(ge=7, le=3650)] = 90,
):
    cutoff_datetime: datetime | None = None
    start_date: date | None = None
    if days is not None:
        start_date = utcnow().date() - timedelta(days=days - 1)
        cutoff_datetime = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)

    application_query = (
        select(JobApplication)
        .where(JobApplication.applied_at.is_not(None))
        .options(selectinload(JobApplication.interview_rounds))
    )
    if cutoff_datetime is not None:
        has_recent_interview = exists(
            select(InterviewRound.id).where(
                InterviewRound.job_application_id == JobApplication.id,
                or_(
                    InterviewRound.scheduled_at >= cutoff_datetime,
                    InterviewRound.completed_at >= cutoff_datetime,
                    InterviewRound.created_at >= cutoff_datetime,
                ),
            )
        )
        application_query = application_query.where(
            or_(
                JobApplication.applied_at >= cutoff_datetime,
                JobApplication.screening_at >= cutoff_datetime,
                JobApplication.rejected_at >= cutoff_datetime,
                JobApplication.offer_at >= cutoff_datetime,
                has_recent_interview,
            )
        )

    applications = [
        application
        for application in session.scalars(application_query.order_by(JobApplication.id.asc())).all()
        if application.status not in HIDDEN_APPLICATION_STATUSES
    ]
    total_applications = len(applications)

    max_round_by_application = {
        application.id: max((round_.round_number for round_ in application.interview_rounds), default=0)
        for application in applications
    }

    status_order = ["Submitted", "Screening", "Interview", "Offer", "Not Selected", "Ghosted", "Withdrawn", "Passed"]
    status_counts_by_label = {label: 0 for label in status_order}
    for application in applications:
        label = _application_status_label(application.status)
        status_counts_by_label[label] = status_counts_by_label.get(label, 0) + 1
    status_counts = [
        ApplicationCountRead(
            label=label,
            count=count,
            percentage=_round_percentage(count, total_applications),
        )
        for label, count in status_counts_by_label.items()
        if count > 0
    ]

    stage_order = ["Submitted", "Screening", "Round 2", "Round 3", "Round 4", "Round 5+"]
    stage_counts_by_label = {label: 0 for label in stage_order}
    for application in applications:
        max_round = max_round_by_application[application.id]
        label = "Round 5+" if max_round >= 5 else _application_stage_label(application, max_round)
        stage_counts_by_label[label] = stage_counts_by_label.get(label, 0) + 1
    stage_counts = [
        ApplicationCountRead(
            label=label,
            count=count,
            percentage=_round_percentage(count, total_applications),
        )
        for label, count in stage_counts_by_label.items()
        if count > 0
    ]

    submitted_count = total_applications
    screening_count = sum(
        1
        for application in applications
        if application.screening_at is not None
        or max_round_by_application[application.id] >= 2
        or application.status in {"screening", "interview", "offer"}
    )
    round_2_count = sum(1 for max_round in max_round_by_application.values() if max_round >= 2)
    round_3_count = sum(1 for max_round in max_round_by_application.values() if max_round >= 3)
    round_4_count = sum(1 for max_round in max_round_by_application.values() if max_round >= 4)
    offer_count = sum(1 for application in applications if application.offer_at is not None or application.status == "offer")
    funnel_data = [
        ("Submitted", submitted_count),
        ("Screening", screening_count),
        ("Round 2", round_2_count),
        ("Round 3", round_3_count),
        ("Round 4", round_4_count),
        ("Offer", offer_count),
    ]
    funnel: list[ApplicationFunnelStageRead] = []
    previous_count: int | None = None
    for label, count in funnel_data:
        funnel.append(
            ApplicationFunnelStageRead(
                label=label,
                count=count,
                percentage_from_start=_round_percentage(count, submitted_count),
                percentage_from_previous=_round_percentage(count, previous_count) if previous_count is not None else None,
            )
        )
        previous_count = count

    round_2_by_application = {
        application.id: min(
            (
                round_.completed_at or round_.scheduled_at
                for round_ in application.interview_rounds
                if round_.round_number == 2 and (round_.completed_at is not None or round_.scheduled_at is not None)
            ),
            default=None,
        )
        for application in applications
    }
    duration_metrics = [
        _duration_metric(
            "Application to Screening",
            [
                value
                for application in applications
                if (value := _duration_days(application.applied_at, application.screening_at)) is not None
            ],
        ),
        _duration_metric(
            "Application to Rejection",
            [
                value
                for application in applications
                if (value := _duration_days(application.applied_at, application.rejected_at)) is not None
            ],
        ),
        _duration_metric(
            "Screening to Round 2",
            [
                value
                for application in applications
                if (value := _duration_days(application.screening_at, round_2_by_application[application.id])) is not None
            ],
        ),
        _duration_metric(
            "Screening to Rejection",
            [
                value
                for application in applications
                if (value := _duration_days(application.screening_at, application.rejected_at)) is not None
            ],
        ),
    ]

    activity_by_date: dict[date, dict[str, int]] = {}
    for application in applications:
        _add_activity(activity_by_date, "applications", application.applied_at)
        _add_activity(activity_by_date, "screenings", application.screening_at)
        _add_activity(activity_by_date, "rejections", application.rejected_at)
        _add_activity(activity_by_date, "offers", application.offer_at)
        for round_ in application.interview_rounds:
            _add_activity(activity_by_date, "interviews", round_.completed_at or round_.scheduled_at)

    if start_date is None and activity_by_date:
        start_date = min(activity_by_date)
    end_date = utcnow().date()
    if activity_by_date:
        end_date = max(end_date, max(activity_by_date))

    activity_dates = _date_range(start_date, end_date) if start_date is not None else []
    daily_activity_ascending: list[DailyApplicationActivityRead] = []
    for activity_date in activity_dates:
        values = activity_by_date.get(activity_date, {"applications": 0, "screenings": 0, "interviews": 0, "rejections": 0, "offers": 0})
        window = daily_activity_ascending[-27:]
        daily_activity_ascending.append(
            DailyApplicationActivityRead(
                activity_date=activity_date,
                applications=values["applications"],
                screenings=values["screenings"],
                interviews=values["interviews"],
                rejections=values["rejections"],
                offers=values["offers"],
                rolling_28_day_avg_applications=round(
                    (sum(item.applications for item in window) + values["applications"]) / (len(window) + 1),
                    2,
                ),
                rolling_28_day_avg_screenings=round(
                    (sum(item.screenings for item in window) + values["screenings"]) / (len(window) + 1),
                    2,
                ),
                rolling_28_day_avg_interviews=round(
                    (sum(item.interviews for item in window) + values["interviews"]) / (len(window) + 1),
                    2,
                ),
                rolling_28_day_avg_rejections=round(
                    (sum(item.rejections for item in window) + values["rejections"]) / (len(window) + 1),
                    2,
                ),
                rolling_28_day_avg_offers=round(
                    (sum(item.offers for item in window) + values["offers"]) / (len(window) + 1),
                    2,
                ),
            )
        )

    return ApplicationStatisticsResponse(
        total_applications=total_applications,
        status_counts=status_counts,
        stage_counts=stage_counts,
        duration_metrics=duration_metrics,
        funnel=funnel,
        daily_activity=list(reversed(daily_activity_ascending)),
    )


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
    if "classification_key" in payload.model_fields_set:
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
    created_since: datetime | None = None,
    updated_since: datetime | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if sort_by == "active_funnel":
        if sort_order.lower() not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail=f"Unsupported application sort order '{sort_order}'")
        order_by_items = _active_application_ordering()
    else:
        order_by = _resolve_application_sort(sort_by, sort_order)
        secondary_order = asc(JobApplication.id) if sort_order.lower() == "asc" else desc(JobApplication.id)
        order_by_items = (order_by, secondary_order)
    search_term = _normalize_text_search(q)
    query = (
        select(JobApplication)
        .options(
            selectinload(JobApplication.job_posting),
            selectinload(JobApplication.resume),
            selectinload(JobApplication.interview_rounds),
        )
        .order_by(*order_by_items)
    )
    count_query = select(JobApplication)
    joined_job_posting = False

    def join_job_posting() -> None:
        nonlocal query, count_query, joined_job_posting
        if joined_job_posting:
            return
        query = query.join(JobPosting, JobApplication.job_posting_id == JobPosting.id)
        count_query = count_query.join(JobPosting, JobApplication.job_posting_id == JobPosting.id)
        joined_job_posting = True

    if sort_by == "posted_at":
        join_job_posting()
    if user_id is not None:
        query = query.where(JobApplication.user_id == user_id)
        count_query = count_query.where(JobApplication.user_id == user_id)
    if resume_id is not None:
        query = query.where(JobApplication.resume_id == resume_id)
        count_query = count_query.where(JobApplication.resume_id == resume_id)
    if job_posting_id is not None:
        query = query.where(JobApplication.job_posting_id == job_posting_id)
        count_query = count_query.where(JobApplication.job_posting_id == job_posting_id)
    if search_term is not None:
        join_job_posting()
        pattern = f"%{search_term}%"
        search_filter = or_(
            JobPosting.company_name.ilike(pattern),
            JobPosting.title.ilike(pattern),
            JobPosting.job_id.ilike(pattern),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    if classification_key:
        join_job_posting()
        query = query.where(JobPosting.classification_key == classification_key)
        count_query = count_query.where(JobPosting.classification_key == classification_key)
    if recommendation:
        query = query.where(JobApplication.recommendation == recommendation)
        count_query = count_query.where(JobApplication.recommendation == recommendation)
    if status:
        query = query.where(JobApplication.status == status)
        count_query = count_query.where(JobApplication.status == status)
    if status_group:
        if status_group == "active":
            query = query.where(JobApplication.status.in_(ACTIVE_APPLICATION_STATUSES))
            count_query = count_query.where(JobApplication.status.in_(ACTIVE_APPLICATION_STATUSES))
        elif status_group == "historical":
            query = query.where(JobApplication.status.in_(HISTORICAL_APPLICATION_STATUSES))
            count_query = count_query.where(JobApplication.status.in_(HISTORICAL_APPLICATION_STATUSES))
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported application status group '{status_group}'")
    if score_min is not None:
        query = query.where(JobApplication.score.is_not(None), JobApplication.score >= score_min)
        count_query = count_query.where(JobApplication.score.is_not(None), JobApplication.score >= score_min)
    if score_max is not None:
        query = query.where(JobApplication.score.is_not(None), JobApplication.score <= score_max)
        count_query = count_query.where(JobApplication.score.is_not(None), JobApplication.score <= score_max)
    if created_since is not None:
        query = query.where(JobApplication.created_at > created_since)
        count_query = count_query.where(JobApplication.created_at > created_since)
    if updated_since is not None:
        query = query.where(JobApplication.updated_at > updated_since)
        count_query = count_query.where(JobApplication.updated_at > updated_since)
    query = query.where(JobApplication.status.not_in(HIDDEN_APPLICATION_STATUSES))
    count_query = count_query.where(JobApplication.status.not_in(HIDDEN_APPLICATION_STATUSES))
    items = session.scalars(query.offset(offset).limit(limit)).all()
    total = len(session.scalars(count_query).all())
    return JobApplicationListResponse(total=total, items=[_serialize_application(item) for item in items])


@app.get("/applications/{application_id}", response_model=JobApplicationRead, tags=["applications"])
def get_application(application_id: int, session: Session = Depends(get_session)):
    application = session.scalar(
        select(JobApplication)
        .options(
            selectinload(JobApplication.job_posting),
            selectinload(JobApplication.resume),
            selectinload(JobApplication.interview_rounds),
        )
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
        existing.applied_notes = None
        existing.screening_at = None
        existing.screening_notes = None
        existing.offer_at = None
        existing.offer_notes = None
        existing.rejected_at = None
        existing.rejected_notes = None
        existing.ghosted_at = None
        existing.ghosted_notes = None
        existing.withdrawn_at = None
        existing.withdrawn_notes = None
        existing.passed_at = None
        existing.passed_notes = None
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
    score_payload: ApplicationScoreWrite,
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
    payload: ApplicationScoreRunRequest,
    session: Session = Depends(get_session),
):
    application = _get_application_by_id(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    if payload.refresh_resume_match:
        try:
            _refresh_application_resume_match(session, application)
        except ApplicationResumeMatchConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    try:
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
    except EmptyRunSelectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _commit_or_fail(session)
    session.refresh(run)
    return ApplicationsScoreRunResponse(**serialize_application_score_run(session, run))


@app.post("/applications/{application_id}/notify", response_model=JobApplicationRead, tags=["applications"])
def mark_application_notified(
    application_id: int,
    notify_payload: ApplicationNotificationWrite,
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
    error_payload: ApplicationErrorWrite,
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


@app.put("/applications/{application_id}/lifecycle-dates", response_model=JobApplicationRead, tags=["applications"])
def update_application_lifecycle_dates(
    application_id: int,
    payload: ApplicationLifecycleDatesUpdate,
    session: Session = Depends(get_session),
):
    application = _get_application_by_id(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' was not found")
    apply_application_lifecycle_dates(application, payload)
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
    if application.status not in TERMINAL_APPLICATION_STATUSES:
        application.status = "interview"
        _commit_or_fail(session)
    return InterviewRoundRead.model_validate(interview_round)


@app.put("/applications/{application_id}/interview-rounds/{interview_round_id}", response_model=InterviewRoundRead, tags=["applications"])
def update_interview_round(
    application_id: int,
    interview_round_id: int,
    payload: InterviewRoundUpdate,
    session: Session = Depends(get_session),
):
    interview_round = session.scalar(
        select(InterviewRound).where(
            InterviewRound.id == interview_round_id,
            InterviewRound.job_application_id == application_id,
        )
    )
    if interview_round is None:
        raise HTTPException(status_code=404, detail=f"Interview round '{interview_round_id}' was not found")
    apply_interview_round_updates(interview_round, payload)
    try:
        _commit_or_fail(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Interview round already exists for that application") from exc
    return InterviewRoundRead.model_validate(interview_round)


@app.delete("/applications/{application_id}/interview-rounds/{interview_round_id}", tags=["applications"])
def delete_interview_round(
    application_id: int,
    interview_round_id: int,
    session: Session = Depends(get_session),
):
    interview_round = session.scalar(
        select(InterviewRound).where(
            InterviewRound.id == interview_round_id,
            InterviewRound.job_application_id == application_id,
        )
    )
    if interview_round is None:
        raise HTTPException(status_code=404, detail=f"Interview round '{interview_round_id}' was not found")
    session.delete(interview_round)
    _commit_or_fail(session)
    return {"deleted": True, "id": interview_round_id}


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
