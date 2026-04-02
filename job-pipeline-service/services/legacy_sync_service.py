from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models import JobApplication, JobPosting, PromptLibrary, Resume, User


LEGACY_MIGRATION_USER_EMAIL = "legacy-migration@job-pipeline-service.local"
LEGACY_MIGRATION_USER_NAME = "Legacy Migration User"
PROTECTED_APPLICATION_STATUSES = {"applied", "screening", "interview", "offer", "rejected", "withdrawn"}


def _get_or_create_legacy_user(session: Session) -> User:
    user = session.scalar(select(User).where(User.email == LEGACY_MIGRATION_USER_EMAIL))
    if user is not None:
        return user

    user = User(name=LEGACY_MIGRATION_USER_NAME, email=LEGACY_MIGRATION_USER_EMAIL)
    session.add(user)
    session.flush()
    return user


def _effective_legacy_prompt_key(job: JobPosting) -> str:
    for candidate in (job.prompt_key, job.classification_key, job.role_type, settings.default_prompt_key):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return "legacy-unspecified"


def _effective_legacy_classification_key(job: JobPosting) -> str | None:
    for candidate in (job.classification_key, job.role_type):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return None


def _legacy_resume_content(session: Session, prompt_key: str) -> str:
    prompt = session.scalar(
        select(PromptLibrary)
        .where(PromptLibrary.prompt_key == prompt_key, PromptLibrary.prompt_type == "scoring")
        .order_by(PromptLibrary.prompt_version.desc(), PromptLibrary.id.desc())
    )
    if prompt is not None and prompt.context and prompt.context.strip():
        return prompt.context.strip()
    return f"Legacy resume content unavailable for prompt_key '{prompt_key}'."


def _get_or_create_legacy_resume(
    session: Session,
    user: User,
    *,
    classification_key: str | None,
    prompt_key: str,
) -> Resume:
    resume_name = "Legacy Default Resume" if classification_key is None else f"Legacy Resume ({classification_key})"
    query = select(Resume).where(
        Resume.user_id == user.id,
        Resume.name == resume_name,
    )
    if classification_key is None:
        query = query.where(Resume.is_default.is_(True))
    else:
        query = query.where(Resume.classification_key == classification_key)
    resume = session.scalar(query)
    if resume is not None:
        return resume

    resume = Resume(
        user_id=user.id,
        name=resume_name,
        prompt_key=prompt_key,
        classification_key=classification_key,
        content=_legacy_resume_content(session, prompt_key),
        is_active=True,
        is_default=classification_key is None,
    )
    session.add(resume)
    session.flush()
    return resume


def _map_legacy_job_status_to_application_status(job: JobPosting) -> str:
    status = (job.status or "new").strip().lower()
    if status == "error":
        return "new"
    if status in {"new", "scored", "tailored", "notified"}:
        return status
    return "new"


def _get_or_create_applications_for_job(session: Session, job: JobPosting) -> list[JobApplication]:
    applications = session.scalars(
        select(JobApplication).where(JobApplication.job_posting_id == job.id).order_by(JobApplication.id.asc())
    ).all()
    if applications:
        return applications

    legacy_user = _get_or_create_legacy_user(session)
    prompt_key = _effective_legacy_prompt_key(job)
    classification_key = _effective_legacy_classification_key(job)
    resume = _get_or_create_legacy_resume(
        session,
        legacy_user,
        classification_key=classification_key,
        prompt_key=prompt_key,
    )
    application = JobApplication(
        user_id=legacy_user.id,
        job_posting_id=job.id,
        resume_id=resume.id,
        status=_map_legacy_job_status_to_application_status(job),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
    session.add(application)
    session.flush()
    return [application]


def sync_job_to_applications(session: Session, job: JobPosting) -> list[JobApplication]:
    applications = _get_or_create_applications_for_job(session, job)

    for application in applications:
        if application.status in PROTECTED_APPLICATION_STATUSES:
            continue

        application.status = _map_legacy_job_status_to_application_status(job)
        application.score = job.score
        application.recommendation = job.recommendation
        application.justification = job.justification
        application.screening_likelihood = job.screening_likelihood
        application.dimension_scores = job.dimension_scores
        application.gating_flags = job.gating_flags
        application.strengths = job.strengths
        application.gaps = job.gaps
        application.missing_from_jd = job.missing_from_jd
        application.scoring_prompt_key = job.prompt_key
        application.scoring_prompt_version = job.prompt_version
        application.score_provider = job.score_provider
        application.score_model = job.score_model
        application.score_raw_response = job.score_raw_response
        application.score_error = job.score_error
        application.score_attempts = job.score_attempts or 0
        application.scored_at = job.scored_at
        application.notified_at = job.notified_at
        application.last_error_at = job.error_at

    return applications
