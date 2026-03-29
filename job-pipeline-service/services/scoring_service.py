from dataclasses import dataclass
from datetime import datetime, timezone
import time

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from models import JobApplication, JobPosting, PromptLibrary
from services.job_selection import select_jobs_for_scoring
from services.legacy_sync_service import sync_job_to_applications
from services.llm_client import LlmClient, LlmRequestError, build_llm_client
from services.prompt_rendering import render_application_prompt, render_user_prompt
from services.prompt_service import resolve_active_prompt
from services.scoring_parser import ParsedScore, ScoringParseError, parse_scoring_response


class JobScoringSkipped(Exception):
    pass


@dataclass
class JobScoringResult:
    job: JobPosting
    outcome: str
    error_message: str | None = None


@dataclass
class ApplicationScoringResult:
    application: JobApplication
    outcome: str
    error_message: str | None = None


@dataclass
class BatchScoringResult:
    selected: int
    scored: int
    errored: int
    skipped: int
    job_ids: list[int]


def _commit_scoring_progress(session: Session) -> None:
    for attempt in range(3):
        try:
            session.commit()
            return
        except OperationalError:
            session.rollback()
            if attempt == 2:
                raise
            time.sleep(0.2 * (attempt + 1))


def _increment_attempts(job: JobPosting) -> None:
    job.score_attempts = (job.score_attempts or 0) + 1


def _increment_application_attempts(application: JobApplication) -> None:
    application.score_attempts = (application.score_attempts or 0) + 1


def _apply_parsed_score(
    job: JobPosting,
    prompt: PromptLibrary,
    parsed: ParsedScore,
    raw_response: str,
    client: LlmClient,
) -> None:
    _increment_attempts(job)
    job.score = parsed.total_score
    job.recommendation = parsed.recommendation
    job.justification = parsed.justification
    job.role_type = parsed.role_type
    job.screening_likelihood = parsed.screening_likelihood
    job.dimension_scores = parsed.dimension_scores
    job.gating_flags = parsed.gating_flags
    job.strengths = parsed.strengths
    job.gaps = parsed.gaps
    job.missing_from_jd = parsed.missing_from_jd
    job.prompt_key = prompt.prompt_key
    job.prompt_version = prompt.prompt_version
    job.score_provider = client.provider
    job.score_model = client.model
    job.score_error = None
    job.score_raw_response = raw_response
    job.scored_at = datetime.now(timezone.utc)
    job.error_at = None
    job.status = "scored"


def _apply_scoring_error(job: JobPosting, error_message: str, raw_response: str | None, client: LlmClient) -> None:
    _increment_attempts(job)
    job.score_provider = client.provider
    job.score_model = client.model
    job.score_error = error_message
    job.score_raw_response = raw_response
    job.error_at = datetime.now(timezone.utc)
    job.status = "error"


def _apply_parsed_application_score(
    application: JobApplication,
    prompt: PromptLibrary,
    parsed: ParsedScore,
    raw_response: str,
    client: LlmClient,
) -> None:
    _increment_application_attempts(application)
    application.score = parsed.total_score
    application.recommendation = parsed.recommendation
    application.justification = parsed.justification
    application.screening_likelihood = parsed.screening_likelihood
    application.dimension_scores = parsed.dimension_scores
    application.gating_flags = parsed.gating_flags
    application.strengths = parsed.strengths
    application.gaps = parsed.gaps
    application.missing_from_jd = parsed.missing_from_jd
    application.scoring_prompt_key = prompt.prompt_key
    application.scoring_prompt_version = prompt.prompt_version
    application.score_provider = client.provider
    application.score_model = client.model
    application.score_error = None
    application.score_raw_response = raw_response
    application.scored_at = datetime.now(timezone.utc)
    application.last_error_at = None
    application.status = "scored"


def _apply_application_scoring_error(
    application: JobApplication,
    error_message: str,
    raw_response: str | None,
    client: LlmClient,
) -> None:
    _increment_application_attempts(application)
    application.score_provider = client.provider
    application.score_model = client.model
    application.score_error = error_message
    application.score_raw_response = raw_response
    application.last_error_at = datetime.now(timezone.utc)
    application.status = "new"


def score_job(
    session: Session,
    job: JobPosting,
    *,
    prompt_key: str | None = None,
    force: bool = False,
    client: LlmClient | None = None,
    prompt: PromptLibrary | None = None,
) -> JobScoringResult:
    if not force and job.status != "new":
        raise JobScoringSkipped(f"Job '{job.id}' is in status '{job.status}' and force=false")

    if not (job.description and job.description.strip()):
        raise JobScoringSkipped(f"Job '{job.id}' has no description to score")

    resolved_prompt = prompt or resolve_active_prompt(session, prompt_key)
    llm_client = client or build_llm_client()
    rendered_prompt = render_user_prompt(job, resolved_prompt)

    raw_response: str | None = None
    try:
        raw_response = llm_client.generate(resolved_prompt.system_prompt, rendered_prompt)
        parsed = parse_scoring_response(raw_response)
    except (LlmRequestError, ScoringParseError) as exc:
        _apply_scoring_error(job, str(exc), raw_response, llm_client)
        sync_job_to_applications(session, job)
        return JobScoringResult(job=job, outcome="error", error_message=str(exc))

    _apply_parsed_score(job, resolved_prompt, parsed, raw_response, llm_client)
    sync_job_to_applications(session, job)
    return JobScoringResult(job=job, outcome="scored")


def score_application(
    session: Session,
    application: JobApplication,
    *,
    prompt_key: str | None = None,
    force: bool = False,
    client: LlmClient | None = None,
    prompt: PromptLibrary | None = None,
) -> ApplicationScoringResult:
    if not force and application.status != "new":
        raise JobScoringSkipped(
            f"Application '{application.id}' is in status '{application.status}' and force=false"
        )

    if not (application.job_posting.description and application.job_posting.description.strip()):
        raise JobScoringSkipped(f"Application '{application.id}' has no job description to score")

    if not (application.resume.content and application.resume.content.strip()):
        raise JobScoringSkipped(f"Application '{application.id}' has no resume content to score")

    resolved_prompt = prompt or resolve_active_prompt(session, prompt_key, prompt_type="scoring")
    llm_client = client or build_llm_client()
    rendered_prompt = render_application_prompt(application, resolved_prompt)

    raw_response: str | None = None
    try:
        raw_response = llm_client.generate(resolved_prompt.system_prompt, rendered_prompt)
        parsed = parse_scoring_response(raw_response)
    except (LlmRequestError, ScoringParseError) as exc:
        _apply_application_scoring_error(application, str(exc), raw_response, llm_client)
        return ApplicationScoringResult(application=application, outcome="error", error_message=str(exc))

    _apply_parsed_application_score(application, resolved_prompt, parsed, raw_response, llm_client)
    return ApplicationScoringResult(application=application, outcome="scored")


def score_jobs(
    session: Session,
    *,
    limit: int,
    status: str,
    source: str | None = None,
    prompt_key: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> BatchScoringResult:
    jobs = select_jobs_for_scoring(session, status=status, source=source, limit=limit)
    if not jobs:
        return BatchScoringResult(selected=0, scored=0, errored=0, skipped=0, job_ids=[])

    if dry_run:
        return BatchScoringResult(
            selected=len(jobs),
            scored=0,
            errored=0,
            skipped=0,
            job_ids=[job.id for job in jobs],
        )

    prompt = resolve_active_prompt(session, prompt_key)
    client = build_llm_client()

    scored = 0
    errored = 0
    skipped = 0
    processed_job_ids: list[int] = []

    for job in jobs:
        try:
            result = score_job(
                session,
                job,
                prompt_key=prompt_key,
                force=force,
                client=client,
                prompt=prompt,
            )
        except JobScoringSkipped:
            session.rollback()
            skipped += 1
            continue

        processed_job_ids.append(job.id)
        if result.outcome == "scored":
            scored += 1
        elif result.outcome == "error":
            errored += 1
        _commit_scoring_progress(session)

    return BatchScoringResult(
        selected=len(jobs),
        scored=scored,
        errored=errored,
        skipped=skipped,
        job_ids=processed_job_ids,
    )
