import pytest

from services.llm_client import LlmClient, LlmRequestError
from services.scoring_service import JobScoringSkipped, score_job, score_jobs
from tests.helpers import seed_job, seed_prompt


class FakeClient(LlmClient):
    def __init__(self, response: str | Exception):
        super().__init__(provider="fake", model="fake-model")
        self._response = response

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _valid_response(score=25):
    return f'{{"total_score": {score}, "recommendation": "Apply", "justification": "fit"}}'


def test_score_job_skips_for_status_and_missing_description(db_session):
    prompt = seed_prompt(db_session)
    not_new = seed_job(db_session, status="scored", description="desc")
    missing_desc = seed_job(db_session, job_id="job-2", description="")

    with pytest.raises(JobScoringSkipped):
        score_job(db_session, not_new, prompt=prompt, client=FakeClient(_valid_response()))

    with pytest.raises(JobScoringSkipped):
        score_job(db_session, missing_desc, prompt=prompt, client=FakeClient(_valid_response()), force=True)


def test_score_job_success_path(db_session):
    prompt = seed_prompt(db_session)
    job = seed_job(db_session)

    result = score_job(db_session, job, prompt=prompt, client=FakeClient(_valid_response(31)))

    assert result.outcome == "scored"
    assert job.score == 31
    assert job.status == "scored"
    assert job.score_attempts == 1


def test_score_job_error_path_for_llm_failure(db_session):
    prompt = seed_prompt(db_session)
    job = seed_job(db_session)

    result = score_job(
        db_session,
        job,
        prompt=prompt,
        client=FakeClient(LlmRequestError("network error")),
    )

    assert result.outcome == "error"
    assert job.status == "error"
    assert job.score_error == "network error"
    assert job.score_attempts == 1


def test_score_jobs_dry_run_and_counts(db_session, monkeypatch):
    seed_prompt(db_session)
    job1 = seed_job(db_session, job_id="job-1")
    seed_job(db_session, job_id="job-2")

    dry_run = score_jobs(db_session, limit=10, status="new", dry_run=True)
    assert dry_run.selected == 2
    assert dry_run.scored == 0

    monkeypatch.setattr("services.scoring_service.build_llm_client", lambda: FakeClient(_valid_response()))
    scored = score_jobs(db_session, limit=10, status="new", dry_run=False)

    assert scored.selected == 2
    assert scored.scored == 2
    assert scored.errored == 0
    assert job1.id in scored.job_ids
