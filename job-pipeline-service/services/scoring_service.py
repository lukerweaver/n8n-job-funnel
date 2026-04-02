from dataclasses import dataclass
from datetime import datetime, timezone
import time

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from models import JobApplication, PromptLibrary
from services.llm_client import LlmClient, LlmRequestError, build_llm_client
from services.prompt_rendering import render_application_prompt
from services.prompt_service import resolve_active_prompt, resolve_prompt_selector
from services.scoring_parser import ParsedScore, ScoringParseError, parse_scoring_response


class JobScoringSkipped(Exception):
    pass


@dataclass
class ApplicationScoringResult:
    application: JobApplication
    outcome: str
    error_message: str | None = None


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


def _increment_application_attempts(application: JobApplication) -> None:
    application.score_attempts = (application.score_attempts or 0) + 1


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


def score_application(
    session: Session,
    application: JobApplication,
    *,
    classification_key: str | None = None,
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

    effective_prompt_key = resolve_prompt_selector(
        prompt_key=prompt_key,
        classification_key=classification_key,
        fallback_key=application.job_posting.classification_key,
    )
    resolved_prompt = prompt or resolve_active_prompt(session, effective_prompt_key, prompt_type="scoring")
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
