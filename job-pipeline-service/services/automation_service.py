from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models import JobApplication, JobPosting, Resume, Run, RunItem
from services.prompt_service import resolve_prompt_selector
from services.scoring_service import _commit_scoring_progress
from services.settings_service import DEFAULT_PROMPT_KEY, get_or_create_app_settings, is_provider_configured


AUTO_CLASSIFICATION_RUN_STATE_KEY = "active_auto_classification_run_id"
AUTO_LAST_RUN_AT_STATE_KEY = "last_auto_process_run_at"
AUTO_LAST_SCORING_RUN_STATE_KEY = "last_auto_scoring_run_id"
RESUME_STRATEGIES = {"classification_first", "default_only", "default_fallback"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _automation_settings(settings) -> dict:
    return settings.automation_settings if isinstance(settings.automation_settings, dict) else {}


def _automation_state(settings) -> dict:
    return settings.automation_state if isinstance(settings.automation_state, dict) else {}


def _automation_int(settings, key: str, default: int) -> int:
    value = _automation_settings(settings).get(key, default)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _automation_resume_strategy(settings) -> str:
    value = _automation_settings(settings).get("resume_strategy", "default_fallback")
    return value if value in RESUME_STRATEGIES else "default_fallback"


def _automation_user_id(settings) -> int | None:
    value = _automation_settings(settings).get("user_id", settings.default_user_id)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return settings.default_user_id


def _parse_datetime(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _service_workflow_enabled(settings) -> bool:
    automation = _automation_settings(settings)
    return automation.get("auto_process_jobs", True) is not False and is_provider_configured(settings)


def _active_run_exists(session) -> bool:
    return session.scalar(
        select(Run.id)
        .where(Run.status.in_(("queued", "running")))
        .where(Run.type.in_(("classification", "application_scoring")))
        .limit(1)
    ) is not None


def _pending_classification_count(session) -> int:
    return session.scalar(
        select(func.count())
        .select_from(JobPosting)
        .where(JobPosting.classification_key.is_(None))
        .where(JobPosting.description.is_not(None))
        .where(JobPosting.description != "")
    ) or 0


def _should_enqueue_auto_classification(settings, pending_count: int) -> bool:
    threshold = max(1, _automation_int(settings, "unprocessed_jobs_threshold", 5))
    if pending_count >= threshold:
        return True

    last_run_at = _parse_datetime(_automation_state(settings).get(AUTO_LAST_RUN_AT_STATE_KEY))
    if last_run_at is None:
        return True

    minutes_threshold = _automation_int(settings, "minutes_since_last_run_threshold", 60)
    return utcnow() - last_run_at >= timedelta(minutes=minutes_threshold)


def maybe_enqueue_next_service_managed_run(session) -> bool:
    from services.run_service import EmptyRunSelectionError, enqueue_classification_run

    settings = get_or_create_app_settings(session)
    if not _service_workflow_enabled(settings) or _active_run_exists(session):
        return False

    pending_count = _pending_classification_count(session)
    if pending_count <= 0 or not _should_enqueue_auto_classification(settings, pending_count):
        return False

    try:
        run = enqueue_classification_run(
            session,
            limit=pending_count,
            prompt_key=settings.default_prompt_key or DEFAULT_PROMPT_KEY,
        )
    except EmptyRunSelectionError:
        return False

    settings.automation_state = {
        **_automation_state(settings),
        AUTO_CLASSIFICATION_RUN_STATE_KEY: run.id,
        AUTO_LAST_RUN_AT_STATE_KEY: utcnow().isoformat(),
    }
    _commit_scoring_progress(session)
    return True


def _enqueue_scoring_run_for_applications(
    session,
    *,
    applications: list[JobApplication],
    prompt_key: str | None,
) -> Run:
    run = Run(
        type="application_scoring",
        status="queued",
        requested_status="new",
        requested_source=None,
        classification_key=None,
        prompt_key=resolve_prompt_selector(prompt_key=prompt_key, classification_key=None),
        force=False,
        callback_url=None,
        selected_count=len(applications),
    )
    session.add(run)
    session.flush()

    for application in applications:
        session.add(
            RunItem(
                run_id=run.id,
                type="application_scoring",
                job_posting_id=application.job_posting_id,
                job_application_id=application.id,
                status="queued",
            )
        )
    session.flush()

    return run


def _select_resumes_for_job_generation(
    session,
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


def _applications_for_auto_scoring(
    session,
    *,
    job_ids: list[int],
    settings,
) -> list[JobApplication]:
    applications: list[JobApplication] = []
    seen_application_ids: set[int] = set()
    user_id = _automation_user_id(settings)
    resume_strategy = _automation_resume_strategy(settings)

    jobs = session.scalars(
        select(JobPosting).where(JobPosting.id.in_(job_ids)).order_by(JobPosting.created_at.asc())
    ).all()
    for job in jobs:
        resumes = _select_resumes_for_job_generation(
            session,
            job=job,
            user_id=user_id,
            resume_strategy=resume_strategy,
        )
        for resume in resumes:
            existing = session.scalar(
                select(JobApplication).where(
                    JobApplication.job_posting_id == job.id,
                    JobApplication.resume_id == resume.id,
                )
            )
            if existing is None:
                existing = JobApplication(
                    user_id=resume.user_id,
                    job_posting_id=job.id,
                    resume_id=resume.id,
                    status="new",
                )
                session.add(existing)
                session.flush()

            if existing.status == "new" and existing.id not in seen_application_ids:
                applications.append(existing)
                seen_application_ids.add(existing.id)

    return applications


def handle_classification_run_completed(session, run: Run) -> Run | None:
    if run.type != "classification":
        return None

    settings = get_or_create_app_settings(session)
    automation_state = _automation_state(settings)
    if automation_state.get(AUTO_CLASSIFICATION_RUN_STATE_KEY) != run.id or not _service_workflow_enabled(settings):
        return None

    classified_job_ids = session.scalars(
        select(RunItem.job_posting_id)
        .where(RunItem.run_id == run.id)
        .where(RunItem.status == "classified")
        .where(RunItem.job_posting_id.is_not(None))
        .order_by(RunItem.id.asc())
    ).all()
    if not classified_job_ids:
        settings.automation_state = {key: value for key, value in automation_state.items() if key != AUTO_CLASSIFICATION_RUN_STATE_KEY}
        return None

    applications = _applications_for_auto_scoring(session, job_ids=list(classified_job_ids), settings=settings)
    if not applications:
        settings.automation_state = {key: value for key, value in automation_state.items() if key != AUTO_CLASSIFICATION_RUN_STATE_KEY}
        return None

    scoring_run = _enqueue_scoring_run_for_applications(
        session,
        applications=list(applications),
        prompt_key=run.prompt_key or settings.default_prompt_key or DEFAULT_PROMPT_KEY,
    )
    settings.automation_state = {
        **automation_state,
        AUTO_LAST_SCORING_RUN_STATE_KEY: scoring_run.id,
        AUTO_CLASSIFICATION_RUN_STATE_KEY: None,
    }
    return scoring_run
