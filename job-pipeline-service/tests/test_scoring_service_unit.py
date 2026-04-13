import pytest
from sqlalchemy.exc import OperationalError

from services.llm_client import LlmClient, LlmRequestError
from services.scoring_service import (
    JobScoringSkipped,
    _commit_scoring_progress,
    score_application,
)
from services.settings_service import get_or_create_app_settings
from tests.helpers import seed_application, seed_job, seed_prompt, seed_resume, seed_user


class FakeClient(LlmClient):
    def __init__(self, response: str | Exception):
        super().__init__(provider="fake", model="fake-model")
        self._response = response
        self.system_prompt: str | None = None
        self.user_prompt: str | None = None

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
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


def test_score_application_includes_user_preferences(db_session):
    prompt = seed_prompt(db_session)
    user = seed_user(db_session, email="preferences@example.com")
    job = seed_job(db_session, job_id="job-preferences")
    resume = seed_resume(db_session, user=user, content="Resume body")
    application = seed_application(db_session, user=user, job=job, resume=resume)
    settings = get_or_create_app_settings(db_session)
    settings.target_roles = ["Product Marketing", "Growth"]
    db_session.commit()
    client = FakeClient(_valid_response(27))

    result = score_application(db_session, application, prompt=prompt, client=client)

    assert result.outcome == "scored"
    assert client.user_prompt is not None
    assert "Target roles: Product Marketing, Growth" in client.user_prompt


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


def test_score_application_uses_resume_prompt_key_before_job_classification(db_session):
    seed_prompt(db_session, key="product-scoring")
    user = seed_user(db_session)
    job = seed_job(db_session)
    job.classification_key = "Product Owner"
    db_session.commit()
    resume = seed_resume(
        db_session,
        user=user,
        prompt_key="product-scoring",
        classification_key="Product Owner",
        content="Resume body",
    )
    application = seed_application(db_session, user=user, job=job, resume=resume)

    result = score_application(db_session, application, client=FakeClient(_valid_response(23)))

    assert result.outcome == "scored"
    assert application.scoring_prompt_key == "product-scoring"
    assert application.score == 23


def test_score_application_still_prefers_explicit_classification_override(db_session):
    seed_prompt(db_session, key="explicit-product-owner")
    seed_prompt(db_session, key="resume-default")
    user = seed_user(db_session, email="explicit-override@example.com")
    job = seed_job(db_session, job_id="job-explicit-override")
    job.classification_key = "Product Owner"
    db_session.commit()
    resume = seed_resume(
        db_session,
        user=user,
        prompt_key="resume-default",
        classification_key="Product Owner",
        content="Resume body",
    )
    application = seed_application(db_session, user=user, job=job, resume=resume)

    result = score_application(
        db_session,
        application,
        classification_key="explicit-product-owner",
        client=FakeClient(_valid_response(24)),
    )

    assert result.outcome == "scored"
    assert application.scoring_prompt_key == "explicit-product-owner"
    assert application.score == 24


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
