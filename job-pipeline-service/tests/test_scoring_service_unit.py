import pytest
from sqlalchemy.exc import OperationalError

from services.llm_client import LlmClient, LlmRequestError
from services.scoring_service import (
    JobScoringSkipped,
    _commit_scoring_progress,
    score_application,
)
from tests.helpers import seed_application, seed_job, seed_prompt, seed_resume, seed_user


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


def test_score_application_success_path(db_session):
    prompt = seed_prompt(db_session)
    user = seed_user(db_session)
    job = seed_job(db_session)
    resume = seed_resume(db_session, user=user, content="Resume body")
    application = seed_application(db_session, user=user, job=job, resume=resume)

    result = score_application(db_session, application, prompt=prompt, client=FakeClient(_valid_response(27)))

    assert result.outcome == "scored"
    assert application.score == 27
    assert application.status == "scored"
    assert application.score_attempts == 1


def test_score_application_skips_for_status_and_missing_content(db_session):
    prompt = seed_prompt(db_session)
    user = seed_user(db_session)
    not_new_job = seed_job(db_session, job_id="job-app-1", description="desc")
    not_new_resume = seed_resume(db_session, user=user, name="Resume1", content="Resume body")
    not_new_application = seed_application(db_session, user=user, job=not_new_job, resume=not_new_resume, status="applied")

    missing_desc_job = seed_job(db_session, job_id="job-app-2", description="")
    missing_desc_resume = seed_resume(db_session, user=user, name="Resume2", content="Resume body")
    missing_desc_application = seed_application(
        db_session,
        user=user,
        job=missing_desc_job,
        resume=missing_desc_resume,
        status="new",
    )

    missing_resume_job = seed_job(db_session, job_id="job-app-3", description="desc")
    missing_resume = seed_resume(db_session, user=user, name="Resume3", content="")
    missing_resume_application = seed_application(
        db_session,
        user=user,
        job=missing_resume_job,
        resume=missing_resume,
        status="new",
    )

    with pytest.raises(JobScoringSkipped):
        score_application(db_session, not_new_application, prompt=prompt, client=FakeClient(_valid_response()))
    with pytest.raises(JobScoringSkipped):
        score_application(db_session, missing_desc_application, prompt=prompt, client=FakeClient(_valid_response()), force=True)
    with pytest.raises(JobScoringSkipped):
        score_application(db_session, missing_resume_application, prompt=prompt, client=FakeClient(_valid_response()), force=True)


def test_score_application_error_path_for_llm_failure(db_session):
    prompt = seed_prompt(db_session)
    user = seed_user(db_session)
    job = seed_job(db_session)
    resume = seed_resume(db_session, user=user, content="Resume body")
    application = seed_application(db_session, user=user, job=job, resume=resume)

    result = score_application(
        db_session,
        application,
        prompt=prompt,
        client=FakeClient(LlmRequestError("network error")),
    )

    assert result.outcome == "error"
    assert application.status == "new"
    assert application.score_error == "network error"
    assert application.score_attempts == 1


def test_commit_scoring_progress_retries_and_raises():
    class FakeSession:
        def __init__(self, failures):
            self.failures = iter(failures)
            self.rollbacks = 0
            self.commits = 0

        def commit(self):
            self.commits += 1
            failure = next(self.failures, None)
            if failure is not None:
                raise failure

        def rollback(self):
            self.rollbacks += 1

    retry_session = FakeSession([OperationalError("stmt", {}, Exception("database is locked")), None])
    _commit_scoring_progress(retry_session)
    assert retry_session.commits == 2
    assert retry_session.rollbacks == 1

    fail_session = FakeSession([OperationalError("stmt", {}, Exception("database is locked"))] * 3)
    with pytest.raises(OperationalError):
        _commit_scoring_progress(fail_session)
