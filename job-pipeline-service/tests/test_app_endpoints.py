import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy import select, text

import app as app_module
from app import (
    _commit_or_fail,
    create_application,
    create_interview_round,
    create_prompt_library,
    create_resume,
    create_user,
    delete_prompt_library,
    ensure_job_postings_schema,
    get_job,
    get_application,
    get_prompt_library,
    get_run,
    get_score_run,
    health,
    ingest_jobs,
    list_applications,
    list_jobs,
    list_prompt_library,
    list_resumes,
    list_run_items,
    list_users,
    list_score_run_items,
    list_interview_rounds,
    mark_application_error,
    mark_application_notified,
    mark_job_error,
    mark_job_notified,
    mark_jobs_notified,
    merge_responses,
    operational_error_handler,
    run_phase_two_backfill,
    run_application_score,
    run_applications_score,
    run_job_classification,
    run_jobs_classification,
    run_job_score,
    run_jobs_score,
    store_application_score,
    store_job_score,
    store_job_scores,
    update_application_status,
    update_resume,
    update_prompt_library,
)
from models import JobApplication, Resume, User
from schemas import (
    ApplicationCreate,
    ApplicationGenerateRequest,
    ApplicationsScoreRunRequest,
    ApplicationStatusWrite,
    InterviewRoundCreate,
    JobErrorWrite,
    JobClassificationRunRequest,
    JobIngestItem,
    JobNotifyBatchItem,
    JobNotifyWrite,
    ResumeCreate,
    ResumeUpdate,
    JobScoreBatchItem,
    JobScoreRunRequest,
    JobScoreWrite,
    JobsScoreRunRequest,
    JobsClassificationRunRequest,
    PromptLibraryCreate,
    PromptLibraryUpdate,
    UserCreate,
)
from services.llm_client import LlmRequestError
from services.prompt_service import PromptResolutionError
from services.scoring_service import JobScoringResult, JobScoringSkipped
from tests.helpers import seed_application, seed_job, seed_prompt, seed_resume, seed_score_run, seed_user


def _score_payload() -> JobScoreWrite:
    return JobScoreWrite(
        score=22,
        recommendation="Strong Apply",
        justification="Good fit",
        role_type="Product Manager",
        screening_likelihood=60,
        dimension_scores={"domain_fit": 4},
        gating_flags=["No"],
        status="scored",
    )


def _operational_error(message: str) -> OperationalError:
    return OperationalError("stmt", {}, Exception(message))


def test_health():
    assert asyncio.run(health()) == {"ok": True}


def test_jobs_ingest_single_and_duplicate(db_session):
    payload = JobIngestItem(job_id="job-1", source="linkedin", description="desc")
    created = ingest_jobs(payload, db_session)
    duplicate = ingest_jobs(payload, db_session)

    assert created.created == 1
    assert duplicate.skipped == 1


def test_jobs_list_with_filters(db_session):
    old = seed_job(db_session, job_id="job-old", status="scored")
    old.scored_at = datetime.now(timezone.utc) - timedelta(days=2)
    old.score = 10
    old.role_type = "Designer"
    old.screening_likelihood = 20

    new = seed_job(db_session, job_id="job-new", status="scored")
    new.scored_at = datetime.now(timezone.utc)
    new.score = 30
    new.role_type = "Product Manager"
    new.screening_likelihood = 80
    db_session.commit()

    response = list_jobs(
        db_session,
        status="SCORED",
        source=None,
        score=20,
        role_type="Product Manager",
        screening_likelihood=50,
        scored_since=datetime.now(timezone.utc) - timedelta(hours=1),
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].id == new.id


def test_jobs_list_filters_by_source_and_paginates(db_session):
    newest = seed_job(db_session, job_id="job-newest", source="greenhouse")
    middle = seed_job(db_session, job_id="job-middle", source="linkedin")
    oldest = seed_job(db_session, job_id="job-oldest", source="greenhouse")

    newest.created_at = datetime.now(timezone.utc)
    middle.created_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    oldest.created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    db_session.commit()

    response = list_jobs(
        db_session,
        status=None,
        source="greenhouse",
        score=None,
        role_type=None,
        screening_likelihood=None,
        scored_since=None,
        limit=1,
        offset=1,
    )

    assert response.total == 2
    assert [item.id for item in response.items] == [oldest.id]


def test_get_job_by_id(db_session):
    job = seed_job(db_session)
    found = get_job(job.id, db_session)

    assert found.id == job.id

    with pytest.raises(HTTPException, match="was not found"):
        get_job(9999, db_session)


def test_run_job_classification_success_and_conflict(db_session, monkeypatch):
    job = seed_job(db_session)

    def _fake_classify_job(session, target_job, **_kwargs):
        target_job.classification_key = "Product Manager"
        target_job.classification_prompt_version = 1
        target_job.classified_at = datetime.now(timezone.utc)
        return SimpleNamespace(job=target_job)

    monkeypatch.setattr(app_module, "classify_job", _fake_classify_job)
    ok = run_job_classification(job.id, JobClassificationRunRequest(force=False), db_session)
    assert ok.classification_key == "Product Manager"

    def _fake_skip(*_args, **_kwargs):
        raise JobScoringSkipped("skipped")

    monkeypatch.setattr(app_module, "classify_job", _fake_skip)
    with pytest.raises(HTTPException) as exc:
        run_job_classification(job.id, JobClassificationRunRequest(force=False), db_session)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as missing:
        run_job_classification(9999, JobClassificationRunRequest(force=False), db_session)
    assert missing.value.status_code == 404


def test_run_jobs_classification_batch(db_session, monkeypatch):
    seed_job(db_session, job_id="job-1")
    seed_job(db_session, job_id="job-2")

    captured = {}

    def _fake_enqueue(session, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            id=11,
            type="classification",
            status="queued",
            selected_count=2,
            callback_url=None,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            finished_at=None,
            last_error=None,
            requested_status="",
            requested_source=kwargs.get("source"),
            prompt_key=kwargs.get("prompt_key"),
            force=kwargs.get("force", False),
            callback_status=None,
            callback_error=None,
        )

    monkeypatch.setattr(app_module, "enqueue_classification_run", _fake_enqueue)
    monkeypatch.setattr(app_module, "_commit_or_fail", lambda _session: None)
    monkeypatch.setattr(db_session, "refresh", lambda _obj: None)
    monkeypatch.setattr(app_module, "serialize_classification_run", lambda _session, run: {
        "run_id": run.id,
        "type": run.type,
        "status": run.status,
        "selected": run.selected_count,
        "processed": 0,
        "classified": 0,
        "errored": 0,
        "skipped": 0,
        "jobs": [1],
        "callback_url": run.callback_url,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "last_error": run.last_error,
    })

    response = run_jobs_classification(JobsClassificationRunRequest(limit=2, force=False), db_session)
    assert captured["force"] is False
    assert response.selected == 2
    assert response.run_id == 11
    assert response.type == "classification"
    assert response.classified == 0
    assert response.jobs == [1]


def test_run_jobs_classification_filters_preclassified_jobs(db_session):
    included = seed_job(db_session, job_id="job-1")
    excluded = seed_job(db_session, job_id="job-2")
    excluded.classification_key = "Product Manager"
    db_session.commit()

    response = run_jobs_classification(JobsClassificationRunRequest(limit=10, force=False), db_session)

    assert response.status == "queued"
    assert response.selected == 1
    assert response.jobs == [included.id]
    assert excluded.id not in response.jobs


def test_store_job_score(db_session):
    job = seed_job(db_session)
    scored = store_job_score(job.id, _score_payload(), db_session)
    applications = db_session.scalars(select(JobApplication).where(JobApplication.job_posting_id == job.id)).all()

    assert scored.status == "scored"
    assert len(applications) == 1
    assert applications[0].score == _score_payload().score
    assert applications[0].status == "scored"

    with pytest.raises(HTTPException, match="was not found"):
        store_job_score(9999, _score_payload(), db_session)


def test_run_job_score_success_and_conflict(db_session, monkeypatch):
    job = seed_job(db_session)

    def _fake_score_job(session, target_job, **_kwargs):
        target_job.status = "scored"
        target_job.score = 88
        return JobScoringResult(job=target_job, outcome="scored")

    monkeypatch.setattr(app_module, "score_job", _fake_score_job)
    ok = run_job_score(job.id, JobScoreRunRequest(force=False), db_session)
    assert ok.score == 88

    def _fake_skip(*_args, **_kwargs):
        raise JobScoringSkipped("skipped")

    monkeypatch.setattr(app_module, "score_job", _fake_skip)
    with pytest.raises(HTTPException) as exc:
        run_job_score(job.id, JobScoreRunRequest(force=False), db_session)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as missing:
        run_job_score(9999, JobScoreRunRequest(force=False), db_session)
    assert missing.value.status_code == 404


def test_run_jobs_score_creates_run(db_session):
    seed_prompt(db_session)
    seed_job(db_session, job_id="job-1")
    seed_job(db_session, job_id="job-2")

    response = run_jobs_score(JobsScoreRunRequest(status="new", limit=2, force=False), db_session)
    assert response.selected == 2
    assert response.status == "queued"


def test_get_score_run_and_items(db_session):
    job = seed_job(db_session)
    run = seed_score_run(db_session, job=job)

    generic_run_response = get_run(run.id, db_session)
    generic_items_response = list_run_items(run.id, db_session)
    run_response = get_score_run(run.id, db_session)
    items_response = list_score_run_items(run.id, db_session)

    assert generic_run_response.run_id == run.id
    assert generic_run_response.type == "scoring"
    assert generic_items_response.total == 1
    assert run_response.run_id == run.id
    assert items_response.total == 1

    with pytest.raises(HTTPException):
        get_run(9999, db_session)
    with pytest.raises(HTTPException):
        list_run_items(9999, db_session)
    with pytest.raises(HTTPException):
        get_score_run(9999, db_session)
    with pytest.raises(HTTPException):
        list_score_run_items(9999, db_session)


def test_store_job_scores_batch(db_session):
    job = seed_job(db_session)
    payload = [JobScoreBatchItem(id=job.id, **_score_payload().model_dump())]

    ok = store_job_scores(payload, db_session)
    assert ok.updated == 1

    with pytest.raises(HTTPException):
        store_job_scores([JobScoreBatchItem(id=9999, **_score_payload().model_dump())], db_session)


def test_notify_and_error_endpoints(db_session):
    job = seed_job(db_session)
    user = seed_user(db_session, name="Legacy User", email="legacy-user@example.com")
    resume = seed_resume(db_session, user=user)
    application = seed_application(
        db_session,
        user=user,
        job=job,
        resume=resume,
        status="scored",
    )

    notify = mark_job_notified(job.id, JobNotifyWrite(status="notified"), db_session)
    error = mark_job_error(job.id, JobErrorWrite(status="error"), db_session)
    notify_batch = mark_jobs_notified([JobNotifyBatchItem(id=job.id, status="notified")], db_session)

    assert notify.status == "notified"
    assert error.status == "error"
    assert notify_batch.updated == 1
    db_session.refresh(application)
    assert application.status == "notified"
    assert application.notified_at is not None
    assert application.last_error_at is not None

    with pytest.raises(HTTPException):
        mark_job_notified(9999, JobNotifyWrite(status="notified"), db_session)
    with pytest.raises(HTTPException):
        mark_job_error(9999, JobErrorWrite(status="error"), db_session)
    with pytest.raises(HTTPException):
        mark_jobs_notified([JobNotifyBatchItem(id=9999, status="notified")], db_session)


def test_legacy_job_sync_does_not_overwrite_protected_application_status(db_session):
    user = seed_user(db_session, name="Protected", email="protected@example.com")
    job = seed_job(db_session, job_id="job-protected", status="new")
    resume = seed_resume(db_session, user=user, prompt_key="default")
    application = seed_application(db_session, user=user, job=job, resume=resume, status="applied")

    store_job_score(job.id, _score_payload(), db_session)
    mark_job_notified(job.id, JobNotifyWrite(status="notified"), db_session)

    db_session.refresh(application)
    assert application.status == "applied"
    assert application.score is None
    assert application.notified_at is None


def test_user_and_resume_crud(db_session):
    user = create_user(UserCreate(name="Alice", email="alice@example.com"), db_session)
    resume = create_resume(
        ResumeCreate(
            user_id=user.id,
            name="PM Resume",
            classification_key="Product Manager",
            content="Resume body",
            is_active=True,
        ),
        db_session,
    )
    listed_users = list_users(db_session, limit=10, offset=0)
    listed_resumes = list_resumes(
        db_session,
        user_id=user.id,
        classification_key="Product Manager",
        is_active=True,
        limit=10,
        offset=0,
    )
    updated_resume = update_resume(
        resume.id,
        ResumeUpdate(content="Updated resume body", is_active=False),
        db_session,
    )

    assert listed_users.total == 1
    assert listed_resumes.total == 1
    assert listed_resumes.items[0].classification_key == "Product Manager"
    assert updated_resume.content == "Updated resume body"
    assert updated_resume.is_active is False

    with pytest.raises(HTTPException):
        create_resume(
            ResumeCreate(
                user_id=9999,
                name="Missing",
                classification_key="default",
                content="nope",
                is_active=True,
            ),
            db_session,
        )
    with pytest.raises(HTTPException):
        create_user(UserCreate(name="Alice 2", email="alice@example.com"), db_session)


def test_application_crud_generate_and_status_flow(db_session):
    user = seed_user(db_session, name="Bob", email="bob@example.com")
    job = seed_job(db_session, job_id="job-apps")
    job.classification_key = "Product Manager"
    db_session.commit()
    resume = seed_resume(db_session, user=user, prompt_key="Product Manager", content="Resume body")

    created = create_application(
        ApplicationCreate(user_id=user.id, job_posting_id=job.id, resume_id=resume.id, status="new"),
        db_session,
    )
    fetched = get_application(created.id, db_session)
    listed = list_applications(
        db_session,
        user_id=user.id,
        resume_id=resume.id,
        job_posting_id=job.id,
        status="new",
        limit=10,
        offset=0,
    )
    generated = app_module.generate_applications(
        ApplicationGenerateRequest(job_posting_id=job.id, user_id=user.id),
        db_session,
    )
    status_updated = update_application_status(
        created.id,
        ApplicationStatusWrite(status="applied"),
        db_session,
    )
    notified = mark_application_notified(created.id, JobNotifyWrite(status="notified"), db_session)
    errored = mark_application_error(created.id, JobErrorWrite(status="error"), db_session)

    assert fetched.id == created.id
    assert listed.total == 1
    assert generated.created == 0
    assert generated.skipped == 1
    assert status_updated.status == "applied"
    assert status_updated.applied_at is not None
    assert notified.status == "notified"
    assert notified.notified_at is not None
    assert errored.status == "new"
    assert errored.last_error_at is not None


def test_application_endpoint_conflicts_and_not_found(db_session):
    user = seed_user(db_session, name="Dana", email="dana@example.com")
    other_user = seed_user(db_session, name="Evan", email="evan@example.com")
    job = seed_job(db_session, job_id="job-conflict")
    resume = seed_resume(db_session, user=user, prompt_key="Product Manager")
    existing = seed_application(db_session, user=user, job=job, resume=resume, status="scored")

    regenerated = create_application(
        ApplicationCreate(user_id=user.id, job_posting_id=job.id, resume_id=resume.id, status="new"),
        db_session,
    )
    assert regenerated.id == existing.id
    assert regenerated.status == "new"
    assert regenerated.score is None

    with pytest.raises(HTTPException):
        get_application(9999, db_session)
    with pytest.raises(HTTPException):
        create_application(
            ApplicationCreate(user_id=other_user.id, job_posting_id=job.id, resume_id=resume.id, status="new"),
            db_session,
        )
    with pytest.raises(HTTPException):
        app_module.generate_applications(ApplicationGenerateRequest(job_posting_id=9999), db_session)
    with pytest.raises(HTTPException):
        app_module.generate_applications(ApplicationGenerateRequest(job_posting_id=job.id), db_session)
    with pytest.raises(HTTPException):
        update_resume(9999, ResumeUpdate(name="missing"), db_session)
    with pytest.raises(HTTPException):
        mark_application_notified(9999, JobNotifyWrite(status="notified"), db_session)
    with pytest.raises(HTTPException):
        mark_application_error(9999, JobErrorWrite(status="error"), db_session)
    with pytest.raises(HTTPException):
        update_application_status(9999, ApplicationStatusWrite(status="applied"), db_session)
    with pytest.raises(HTTPException):
        list_interview_rounds(9999, db_session)
    with pytest.raises(HTTPException):
        create_interview_round(9999, InterviewRoundCreate(round_number=1), db_session)


def test_list_applications_filters_by_score(db_session):
    user = seed_user(db_session, name="Fran", email="fran@example.com")
    job = seed_job(db_session, job_id="job-filter")
    resume = seed_resume(db_session, user=user, prompt_key="default")
    low = seed_application(db_session, user=user, job=job, resume=resume, status="scored")
    low.score = 10
    low.updated_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    resume_two = seed_resume(db_session, user=user, name="Resume 2", prompt_key="default")
    high = seed_application(db_session, user=user, job=job, resume=resume_two, status="scored")
    high.score = 30
    high.updated_at = datetime.now(timezone.utc)
    db_session.commit()

    response = list_applications(
        db_session,
        user_id=user.id,
        resume_id=None,
        job_posting_id=job.id,
        status="scored",
        score=20,
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].id == high.id


def test_run_applications_score_batch(db_session, monkeypatch):
    user = seed_user(db_session, name="Gina", email="gina@example.com")
    job = seed_job(db_session, job_id="job-batch")
    resume_one = seed_resume(db_session, user=user, name="Resume 1", prompt_key="default", content="Resume body 1")
    resume_two = seed_resume(db_session, user=user, name="Resume 2", prompt_key="default", content="Resume body 2")
    application_one = seed_application(db_session, user=user, job=job, resume=resume_one, status="new")
    application_two = seed_application(db_session, user=user, job=job, resume=resume_two, status="new")

    outcomes = iter(
        [
            SimpleNamespace(application=application_one, outcome="scored"),
            JobScoringSkipped("skip"),
        ]
    )

    def _fake_score_application(*_args, **_kwargs):
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(app_module, "score_application", _fake_score_application)

    result = run_applications_score(
        ApplicationsScoreRunRequest(
            status="new",
            limit=10,
            user_id=user.id,
            prompt_key="default",
            force=False,
        ),
        db_session,
    )

    assert result.selected == 2
    assert result.processed == 1
    assert result.scored == 1
    assert result.skipped == 1
    assert result.errored == 0
    assert result.applications == [application_one.id]


def test_run_applications_score_empty_selection(db_session):
    result = run_applications_score(
        ApplicationsScoreRunRequest(status="new", limit=10, user_id=9999, force=False),
        db_session,
    )

    assert result.selected == 0
    assert result.processed == 0
    assert result.applications == []


def test_application_scoring_and_interview_rounds(db_session, monkeypatch):
    user = seed_user(db_session, name="Cara", email="cara@example.com")
    job = seed_job(db_session, job_id="job-score")
    resume = seed_resume(db_session, user=user, prompt_key="default", content="Resume body")
    application = seed_application(db_session, user=user, job=job, resume=resume, status="new")

    manual = store_application_score(application.id, _score_payload(), db_session)
    assert manual.status == "scored"

    application.status = "new"
    db_session.commit()

    def _fake_score_application(session, target_application, **_kwargs):
        target_application.status = "scored"
        target_application.score = 91
        target_application.scored_at = datetime.now(timezone.utc)
        return SimpleNamespace(application=target_application)

    monkeypatch.setattr(app_module, "score_application", _fake_score_application)
    scored = run_application_score(application.id, JobScoreRunRequest(force=False), db_session)
    assert scored.score == 91

    round_one = create_interview_round(
        application.id,
        InterviewRoundCreate(round_number=1, stage_name="Hiring Manager"),
        db_session,
    )
    rounds = list_interview_rounds(application.id, db_session)
    assert round_one.round_number == 1
    assert rounds.total == 1

    with pytest.raises(HTTPException):
        create_interview_round(
            application.id,
            InterviewRoundCreate(round_number=1, stage_name="Duplicate"),
            db_session,
        )


def test_application_reads_include_job_context(db_session):
    user = seed_user(db_session, name="Dana", email="dana@example.com")
    job = seed_job(db_session, job_id="job-app-read", status="scored")
    job.company_name = "Acme Labs"
    job.title = "Senior PM"
    job.apply_url = "https://example.com/jobs/123"
    job.yearly_min_compensation = 150000
    job.yearly_max_compensation = 180000
    job.role_type = "Product Manager"
    db_session.commit()
    resume = seed_resume(db_session, user=user, name="PM Resume", prompt_key="default")
    application = seed_application(db_session, user=user, job=job, resume=resume, status="scored")
    application.score = 24
    application.screening_likelihood = 19
    db_session.commit()

    listed = list_applications(
        db_session,
        user_id=user.id,
        resume_id=None,
        job_posting_id=None,
        status="scored",
        score=None,
        limit=10,
        offset=0,
    )
    fetched = get_application(application.id, db_session)

    assert listed.total == 1
    assert listed.items[0].job_id == "job-app-read"
    assert listed.items[0].company_name == "Acme Labs"
    assert listed.items[0].title == "Senior PM"
    assert listed.items[0].apply_url == "https://example.com/jobs/123"
    assert listed.items[0].role_type == "Product Manager"
    assert listed.items[0].resume_name == "PM Resume"
    assert fetched.job_id == "job-app-read"
    assert fetched.company_name == "Acme Labs"
    assert fetched.resume_name == "PM Resume"


def test_prompt_library_crud(db_session):
    create = create_prompt_library(
        PromptLibraryCreate(
            prompt_key="default",
            prompt_type="scoring",
            prompt_version=1,
            system_prompt="System",
            user_prompt_template="User",
            context="Resume",
            max_tokens=600,
            temperature=0.2,
            is_active=True,
        ),
        db_session,
    )

    listing = list_prompt_library(
        db_session,
        prompt_key="default",
        prompt_version=1,
        is_active=True,
        limit=100,
        offset=0,
    )
    fetched = get_prompt_library(create.id, db_session)
    updated = update_prompt_library(create.id, PromptLibraryUpdate(is_active=False), db_session)
    deleted = delete_prompt_library(create.id, db_session)

    assert listing.total == 1
    assert fetched.id == create.id
    assert updated.is_active is False
    assert deleted["deleted"] is True

    with pytest.raises(HTTPException):
        get_prompt_library(9999, db_session)


def test_list_prompt_library_individual_filters(db_session):
    first = seed_prompt(db_session, key="default", version=1, active=True)
    second = seed_prompt(db_session, key="default", version=2, active=False)
    third = seed_prompt(db_session, key="alt", version=1, active=True)

    key_filtered = list_prompt_library(db_session, prompt_key="default", prompt_version=None, is_active=None, limit=10, offset=0)
    version_filtered = list_prompt_library(db_session, prompt_key=None, prompt_version=1, is_active=None, limit=10, offset=0)
    active_filtered = list_prompt_library(db_session, prompt_key=None, prompt_version=None, is_active=False, limit=10, offset=0)

    assert [item.id for item in key_filtered.items] == [second.id, first.id]
    assert [item.id for item in version_filtered.items] == [third.id, first.id]
    assert [item.id for item in active_filtered.items] == [second.id]


def test_update_prompt_library_updates_all_fields(db_session):
    prompt = seed_prompt(db_session, key="default", version=1, active=True)

    updated = update_prompt_library(
        prompt.id,
        PromptLibraryUpdate(
            prompt_key="custom",
            prompt_type="tailoring",
            prompt_version=3,
            system_prompt="New system",
            user_prompt_template="New user",
            context="New context",
            max_tokens=900,
            temperature=0.5,
            is_active=False,
        ),
        db_session,
    )

    assert updated.prompt_key == "custom"
    assert updated.prompt_type == "tailoring"
    assert updated.prompt_version == 3
    assert updated.system_prompt == "New system"
    assert updated.user_prompt_template == "New user"
    assert updated.context == "New context"
    assert updated.max_tokens == 900
    assert updated.temperature == 0.5
    assert updated.is_active is False


def test_update_and_delete_prompt_library_not_found(db_session):
    with pytest.raises(HTTPException) as update_exc:
        update_prompt_library(9999, PromptLibraryUpdate(is_active=False), db_session)
    assert update_exc.value.status_code == 404

    with pytest.raises(HTTPException) as delete_exc:
        delete_prompt_library(9999, db_session)
    assert delete_exc.value.status_code == 404


def test_prompt_library_conflicts(db_session):
    payload = PromptLibraryCreate(
        prompt_key="default",
        prompt_type="scoring",
        prompt_version=1,
        system_prompt="System",
        user_prompt_template="User",
        context="Resume",
        is_active=True,
    )
    create_prompt_library(payload, db_session)

    with pytest.raises(HTTPException) as exc:
        create_prompt_library(payload, db_session)
    assert exc.value.status_code == 409


def test_update_prompt_library_conflict(db_session):
    prompt = seed_prompt(db_session, key="default", version=1, active=True)
    seed_prompt(db_session, key="custom", version=2, active=True)

    with pytest.raises(HTTPException) as exc:
        update_prompt_library(
            prompt.id,
            PromptLibraryUpdate(prompt_key="custom", prompt_version=2),
            db_session,
        )
    assert exc.value.status_code == 409


def test_run_phase_two_backfill_migrates_legacy_prompt_and_job_data(db_session):
    created_prompt = create_prompt_library(
        PromptLibraryCreate(
            prompt_key="default",
            prompt_type="scoring",
            prompt_version=1,
            system_prompt="System",
            user_prompt_template="User {{resume}} {{description}}",
            context=None,
            is_active=True,
        ),
        db_session,
    )
    prompt = db_session.get(app_module.PromptLibrary, created_prompt.id)
    assert prompt is not None
    db_session.execute(text("ALTER TABLE prompt_library ADD COLUMN base_resume_template TEXT"))
    db_session.execute(
        text("UPDATE prompt_library SET base_resume_template = :resume WHERE id = :prompt_id"),
        {"resume": "Legacy Resume", "prompt_id": prompt.id},
    )

    migrated_job = seed_job(db_session, job_id="job-migrated", status="notified")
    migrated_job.role_type = "Product Manager"
    migrated_job.prompt_key = "default"
    migrated_job.prompt_version = 1
    migrated_job.score = 42
    migrated_job.recommendation = "Apply"
    migrated_job.justification = "Strong fit"
    migrated_job.scored_at = datetime.now(timezone.utc)
    migrated_job.notified_at = datetime.now(timezone.utc)

    untouched_job = seed_job(db_session, job_id="job-untouched", status="new")
    db_session.commit()

    run_phase_two_backfill(db_session)

    db_session.refresh(migrated_job)
    db_session.refresh(prompt)

    legacy_user = db_session.scalar(select(User).where(User.email == app_module.LEGACY_MIGRATION_USER_EMAIL))
    resumes = db_session.scalars(select(Resume).order_by(Resume.id.asc())).all()
    applications = db_session.scalars(select(JobApplication).order_by(JobApplication.id.asc())).all()

    assert prompt.context == "Legacy Resume"
    assert migrated_job.classification_key == "Product Manager"
    assert migrated_job.classified_at == migrated_job.scored_at
    assert legacy_user is not None
    assert len(resumes) == 1
    assert resumes[0].prompt_key == "default"
    assert resumes[0].content == "Legacy Resume"
    assert len(applications) == 1
    assert applications[0].job_posting_id == migrated_job.id
    assert applications[0].resume_id == resumes[0].id
    assert applications[0].status == "notified"
    assert applications[0].score == 42
    assert applications[0].scoring_prompt_key == "default"
    assert applications[0].notified_at == migrated_job.notified_at
    assert all(application.job_posting_id != untouched_job.id for application in applications)

    run_phase_two_backfill(db_session)

    assert db_session.query(User).count() == 1
    assert db_session.query(Resume).count() == 1
    assert db_session.query(JobApplication).count() == 1


def test_run_phase_two_backfill_maps_error_jobs_to_new_applications(db_session):
    job = seed_job(db_session, job_id="job-error", status="error")
    job.score_error = "LLM failed"
    job.error_at = datetime.now(timezone.utc)
    db_session.commit()

    run_phase_two_backfill(db_session)

    application = db_session.scalar(select(JobApplication).where(JobApplication.job_posting_id == job.id))
    assert application is not None
    assert application.status == "new"
    assert application.score_error == "LLM failed"
    assert application.last_error_at == job.error_at


def test_exception_handlers(db_session, monkeypatch):
    seed_job(db_session)

    def _raise_prompt(*_args, **_kwargs):
        raise PromptResolutionError("prompt missing")

    monkeypatch.setattr(app_module, "score_job", _raise_prompt)
    with pytest.raises(PromptResolutionError) as exc:
        run_job_score(1, JobScoreRunRequest(force=False), db_session)
    response = asyncio.run(app_module.prompt_resolution_error_handler(None, exc.value))
    assert response.status_code == 503


def test_llm_request_error_handler():
    response = asyncio.run(app_module.llm_request_error_handler(None, LlmRequestError("upstream down")))
    assert response.status_code == 503
    assert response.body == b'{"detail":"upstream down"}'


def test_operational_error_handler():
    retryable = asyncio.run(operational_error_handler(None, _operational_error("database is locked")))
    fatal = asyncio.run(operational_error_handler(None, _operational_error("syntax error")))

    assert retryable.status_code == 503
    assert fatal.status_code == 500


def test_merge_responses_handles_lists_dicts_and_scalars():
    assert merge_responses([1], [2, 3]) == [1, 2, 3]
    assert merge_responses({"a": {"x": 1}}, {"a": {"y": 2}, "b": 3}) == {"a": {"x": 1, "y": 2}, "b": 3}
    assert merge_responses("old", "new") == "new"


def test_commit_or_fail_retries_and_raises_service_unavailable():
    class FakeSession:
        def __init__(self, errors):
            self._errors = iter(errors)
            self.commits = 0
            self.rollbacks = 0

        def commit(self):
            self.commits += 1
            error = next(self._errors, None)
            if error is not None:
                raise error

        def rollback(self):
            self.rollbacks += 1

    retry_session = FakeSession([_operational_error("database is locked"), None])
    _commit_or_fail(retry_session)
    assert retry_session.commits == 2
    assert retry_session.rollbacks == 1

    disk_error_session = FakeSession([_operational_error("disk i/o error")] * 3)
    with pytest.raises(HTTPException) as exc:
        _commit_or_fail(disk_error_session)
    assert exc.value.status_code == 503


def test_commit_or_fail_raises_non_retryable_error():
    class FakeSession:
        def commit(self):
            raise _operational_error("constraint failed")

        def rollback(self):
            pass

    with pytest.raises(OperationalError):
        _commit_or_fail(FakeSession())


def test_ensure_job_postings_schema_executes_only_missing_columns(monkeypatch):
    executed = []

    class FakeConnection:
        def execute(self, statement):
            executed.append(statement)

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="sqlite"),
        begin=lambda: FakeBegin(),
    )

    monkeypatch.setattr(app_module, "engine", fake_engine)
    monkeypatch.setattr(
        app_module,
        "inspect",
        lambda _engine: SimpleNamespace(get_columns=lambda _table: [{"name": "error_at"}, {"name": "role_type"}]),
    )
    monkeypatch.setattr(app_module, "text", lambda statement: statement)

    ensure_job_postings_schema()

    assert any("ADD COLUMN screening_likelihood REAL" in statement for statement in executed)
    assert any("ADD COLUMN classification_key VARCHAR(100)" in statement for statement in executed)
    assert all("ADD COLUMN error_at" not in statement for statement in executed)


def test_ensure_job_postings_schema_returns_when_no_statements(monkeypatch):
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    begin_calls = []

    monkeypatch.setattr(app_module, "engine", fake_engine)
    monkeypatch.setattr(
        app_module,
        "inspect",
        lambda _engine: SimpleNamespace(
            get_columns=lambda _table: [{"name": name} for name in (
                "error_at",
                "role_type",
                "screening_likelihood",
                "dimension_scores",
                "gating_flags",
                "score_provider",
                "score_model",
                "score_error",
                "score_raw_response",
                "score_attempts",
                "classification_key",
                "classification_prompt_version",
                "classification_provider",
                "classification_model",
                "classification_error",
                "classification_raw_response",
                "classified_at",
            )]
        ),
    )
    monkeypatch.setattr(
        fake_engine,
        "begin",
        lambda: begin_calls.append(True),
        raising=False,
    )

    ensure_job_postings_schema()

    assert begin_calls == []


def test_lifespan_starts_and_stops_worker(monkeypatch):
    calls = []

    monkeypatch.setattr(app_module.Base.metadata, "create_all", lambda bind: calls.append(("create_all", bind)))
    monkeypatch.setattr(app_module, "ensure_job_postings_schema", lambda: calls.append(("ensure_schema", None)))
    monkeypatch.setattr(app_module, "ensure_prompt_library_schema", lambda: calls.append(("ensure_prompt_schema", None)))
    monkeypatch.setattr(app_module, "run_phase_two_backfill", lambda session: calls.append(("phase_two", session)))
    monkeypatch.setattr(app_module.score_run_worker, "start", lambda: calls.append(("start", None)))
    monkeypatch.setattr(app_module.score_run_worker, "stop", lambda: calls.append(("stop", None)))

    async def _run():
        async with app_module.lifespan(app_module.app):
            calls.append(("inside", None))

    asyncio.run(_run())

    assert [name for name, _ in calls] == [
        "create_all",
        "ensure_schema",
        "ensure_prompt_schema",
        "phase_two",
        "start",
        "inside",
        "stop",
    ]


def test_operational_error_handler_branches(db_session, monkeypatch):
    seed_job(db_session)

    def _raise_locked(*_args, **_kwargs):
        raise app_module.OperationalError("stmt", {}, Exception("database is locked"))

    monkeypatch.setattr(app_module, "_commit_or_fail", _raise_locked)
    with pytest.raises(app_module.OperationalError) as locked_exc:
        store_job_score(1, _score_payload(), db_session)
    locked_response = asyncio.run(app_module.operational_error_handler(None, locked_exc.value))
    assert locked_response.status_code == 503

    def _raise_generic(*_args, **_kwargs):
        raise app_module.OperationalError("stmt", {}, Exception("generic db issue"))

    monkeypatch.setattr(app_module, "_commit_or_fail", _raise_generic)
    with pytest.raises(app_module.OperationalError) as generic_exc:
        store_job_score(1, _score_payload(), db_session)
    generic_response = asyncio.run(app_module.operational_error_handler(None, generic_exc.value))
    assert generic_response.status_code == 500


def test_validate_application_entities_error_paths(db_session):
    user = seed_user(db_session, name="Entity User", email="entity-user@example.com")
    other_user = seed_user(db_session, name="Other User", email="other-user@example.com")
    job = seed_job(db_session, job_id="job-entity")
    resume = seed_resume(db_session, user=user, prompt_key="default")
    wrong_resume = seed_resume(db_session, user=other_user, name="Other Resume", prompt_key="default")

    validated_user, validated_resume, validated_job = app_module._validate_application_entities(
        db_session,
        user_id=user.id,
        resume_id=resume.id,
        job_posting_id=job.id,
    )
    assert validated_user.id == user.id
    assert validated_resume.id == resume.id
    assert validated_job.id == job.id

    with pytest.raises(HTTPException, match="User '9999' was not found"):
        app_module._validate_application_entities(
            db_session,
            user_id=9999,
            resume_id=resume.id,
            job_posting_id=job.id,
        )

    with pytest.raises(HTTPException, match=f"Resume '{9999}' was not found"):
        app_module._validate_application_entities(
            db_session,
            user_id=user.id,
            resume_id=9999,
            job_posting_id=job.id,
        )

    with pytest.raises(HTTPException, match="Resume does not belong to the selected user"):
        app_module._validate_application_entities(
            db_session,
            user_id=user.id,
            resume_id=wrong_resume.id,
            job_posting_id=job.id,
        )

    with pytest.raises(HTTPException, match="Job '9999' was not found"):
        app_module._validate_application_entities(
            db_session,
            user_id=user.id,
            resume_id=resume.id,
            job_posting_id=9999,
        )


@pytest.mark.parametrize(
    ("status", "timestamp_field"),
    [
        ("offer", "offer_at"),
        ("rejected", "rejected_at"),
        ("withdrawn", "withdrawn_at"),
    ],
)
def test_apply_application_status_sets_terminal_timestamps(status, timestamp_field):
    application = JobApplication(status="new")

    app_module.apply_application_status(application, ApplicationStatusWrite(status=status))

    assert application.status == status
    assert getattr(application, timestamp_field) is not None


def test_apply_application_error_preserves_non_error_status():
    application = JobApplication(status="scored")

    app_module.apply_application_error(application, JobErrorWrite(status="rejected"))
    assert application.status == "rejected"
    assert application.last_error_at is not None

    app_module.apply_application_error(application, JobErrorWrite(status="error"))
    assert application.status == "new"


def test_job_backfill_helpers_cover_legacy_status_paths(db_session):
    pristine_job = seed_job(db_session, job_id="job-pristine", status="new")
    pristine_job.score = None
    pristine_job.recommendation = None
    pristine_job.justification = None
    pristine_job.screening_likelihood = None
    pristine_job.dimension_scores = None
    pristine_job.gating_flags = None
    pristine_job.strengths = None
    pristine_job.gaps = None
    pristine_job.missing_from_jd = None
    pristine_job.prompt_key = None
    pristine_job.prompt_version = None
    pristine_job.score_provider = None
    pristine_job.score_model = None
    pristine_job.score_error = None
    pristine_job.score_raw_response = None
    pristine_job.scored_at = None
    pristine_job.notified_at = None
    pristine_job.error_at = None
    pristine_job.score_attempts = 0

    scored_job = seed_job(db_session, job_id="job-scored", status="error")
    scored_job.scored_at = datetime.now(timezone.utc)

    unknown_job = seed_job(db_session, job_id="job-unknown", status="mystery")
    prompted_job = seed_job(db_session, job_id="job-prompted", status="new")
    prompted_job.prompt_key = "custom-key"

    db_session.commit()

    assert app_module._job_requires_application_backfill(pristine_job) is False
    assert app_module._job_requires_application_backfill(prompted_job) is True
    assert app_module._map_legacy_job_status_to_application_status(pristine_job) == "new"
    assert app_module._map_legacy_job_status_to_application_status(scored_job) == "scored"
    assert app_module._map_legacy_job_status_to_application_status(unknown_job) == "new"


def test_legacy_resume_helpers_cover_fallbacks(db_session):
    user = seed_user(db_session, name="Legacy Helper", email="legacy-helper@example.com")

    assert app_module._legacy_resume_content(db_session, "missing-key").startswith(
        "Legacy resume content unavailable"
    )

    blank_prompt = seed_prompt(db_session, key="blank-key", version=1, active=True)
    blank_prompt.context = "   "
    db_session.commit()

    assert app_module._legacy_resume_content(db_session, "blank-key").startswith(
        "Legacy resume content unavailable"
    )

    user_from_helper = app_module._get_or_create_legacy_user(db_session)
    same_user = app_module._get_or_create_legacy_user(db_session)
    assert user_from_helper.id == same_user.id

    resume = app_module._get_or_create_legacy_resume(db_session, user, "missing-key")
    same_resume = app_module._get_or_create_legacy_resume(db_session, user, "missing-key")
    assert resume.id == same_resume.id


def test_ensure_prompt_library_and_resumes_schema_branches(monkeypatch):
    prompt_executed = []
    resume_executed = []

    class FakeConnection:
        def __init__(self, executed):
            self.executed = executed

        def execute(self, statement):
            self.executed.append(statement)

    class FakeBegin:
        def __init__(self, executed):
            self.executed = executed

        def __enter__(self):
            return FakeConnection(self.executed)

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    monkeypatch.setattr(app_module, "engine", fake_engine)
    monkeypatch.setattr(app_module, "text", lambda statement: statement)

    monkeypatch.setattr(
        app_module,
        "inspect",
        lambda _engine: SimpleNamespace(get_columns=lambda _table: [{"name": "system_prompt"}]),
    )
    monkeypatch.setattr(fake_engine, "begin", lambda: FakeBegin(prompt_executed), raising=False)

    app_module.ensure_prompt_library_schema()

    assert any("ADD COLUMN prompt_type VARCHAR(50)" in statement for statement in prompt_executed)
    assert any("UPDATE prompt_library SET prompt_type = 'scoring'" in statement for statement in prompt_executed)
    assert any("UPDATE prompt_library SET created_at = CURRENT_TIMESTAMP" in statement for statement in prompt_executed)
    assert any("UPDATE prompt_library SET updated_at = CURRENT_TIMESTAMP" in statement for statement in prompt_executed)

    monkeypatch.setattr(
        app_module,
        "inspect",
        lambda _engine: SimpleNamespace(get_columns=lambda _table: [{"name": "classification_key"}]),
    )
    begin_calls = []
    monkeypatch.setattr(fake_engine, "begin", lambda: begin_calls.append(True), raising=False)

    app_module.ensure_resumes_schema()

    assert begin_calls == []

    monkeypatch.setattr(
        app_module,
        "inspect",
        lambda _engine: SimpleNamespace(get_columns=lambda _table: [{"name": "prompt_key"}]),
    )
    monkeypatch.setattr(fake_engine, "begin", lambda: FakeBegin(resume_executed), raising=False)

    app_module.ensure_resumes_schema()

    assert any("ALTER TABLE resumes ADD COLUMN classification_key VARCHAR(100)" in statement for statement in resume_executed)
    assert any("UPDATE resumes" in statement for statement in resume_executed)
