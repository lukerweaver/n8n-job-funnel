from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import JobPosting, PromptLibrary
from services.classification_parser import ClassificationParseError, parse_classification_response
from services.job_selection import select_jobs_for_scoring
from services.llm_client import LlmClient, LlmRequestError, build_llm_client
from services.prompt_rendering import render_user_prompt
from services.prompt_service import resolve_active_prompt, resolve_prompt_selector
from services.scoring_service import JobScoringSkipped


@dataclass
class JobClassificationResult:
    job: JobPosting
    outcome: str
    error_message: str | None = None


@dataclass
class BatchClassificationResult:
    selected: int
    classified: int
    errored: int
    skipped: int
    job_ids: list[int]


def _apply_classification(job: JobPosting, classification_key: str, prompt: PromptLibrary, raw_response: str, client: LlmClient) -> None:
    now = datetime.now(timezone.utc)
    job.classification_key = classification_key
    job.classification_prompt_version = prompt.prompt_version
    job.classification_provider = client.provider
    job.classification_model = client.model
    job.classification_error = None
    job.classification_raw_response = raw_response
    job.classified_at = now
    job.role_type = classification_key


def _apply_classification_error(job: JobPosting, error_message: str, raw_response: str | None, client: LlmClient) -> None:
    job.classification_provider = client.provider
    job.classification_model = client.model
    job.classification_error = error_message
    job.classification_raw_response = raw_response


def classify_job(
    session: Session,
    job: JobPosting,
    *,
    classification_key: str | None = None,
    prompt_key: str | None = None,
    force: bool = False,
    client: LlmClient | None = None,
    prompt: PromptLibrary | None = None,
) -> JobClassificationResult:
    if not force and job.classification_key:
        raise JobScoringSkipped(f"Job '{job.id}' is already classified and force=false")
    if not (job.description and job.description.strip()):
        raise JobScoringSkipped(f"Job '{job.id}' has no description to classify")

    effective_prompt_key = resolve_prompt_selector(prompt_key=prompt_key, classification_key=classification_key)
    resolved_prompt = prompt or resolve_active_prompt(session, effective_prompt_key, prompt_type="classification")
    llm_client = client or build_llm_client()
    rendered_prompt = render_user_prompt(job, resolved_prompt)

    raw_response: str | None = None
    try:
        raw_response = llm_client.generate(resolved_prompt.system_prompt, rendered_prompt)
        classification_key = parse_classification_response(raw_response)
    except (LlmRequestError, ClassificationParseError) as exc:
        _apply_classification_error(job, str(exc), raw_response, llm_client)
        return JobClassificationResult(job=job, outcome="error", error_message=str(exc))

    _apply_classification(job, classification_key, resolved_prompt, raw_response, llm_client)
    return JobClassificationResult(job=job, outcome="classified")


def classify_jobs(
    session: Session,
    *,
    limit: int,
    source: str | None = None,
    classification_key: str | None = None,
    prompt_key: str | None = None,
    force: bool = False,
) -> BatchClassificationResult:
    jobs = select_jobs_for_scoring(session, status="", source=source, limit=limit)
    if not jobs:
        return BatchClassificationResult(selected=0, classified=0, errored=0, skipped=0, job_ids=[])

    effective_prompt_key = resolve_prompt_selector(prompt_key=prompt_key, classification_key=classification_key)
    prompt = resolve_active_prompt(session, effective_prompt_key, prompt_type="classification")
    client = build_llm_client()

    classified = 0
    errored = 0
    skipped = 0
    processed: list[int] = []

    for job in jobs:
        try:
            result = classify_job(
                session,
                job,
                classification_key=classification_key,
                prompt_key=prompt_key,
                force=force,
                client=client,
                prompt=prompt,
            )
        except JobScoringSkipped:
            session.rollback()
            skipped += 1
            continue

        processed.append(job.id)
        if result.outcome == "classified":
            classified += 1
        elif result.outcome == "error":
            errored += 1
        session.commit()

    return BatchClassificationResult(
        selected=len(jobs),
        classified=classified,
        errored=errored,
        skipped=skipped,
        job_ids=processed,
    )
