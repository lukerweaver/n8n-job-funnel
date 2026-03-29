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
    get_score_run,
    health,
    ingest_jobs,
    list_applications,
    list_jobs,
    list_prompt_library,
    list_resumes,
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

    monkeypatch.setattr(
        app_module,
        "classify_jobs",
        lambda session, **_kwargs: SimpleNamespace(selected=2, classified=1, errored=0, skipped=1, job_ids=[1]),
    )

    response = run_jobs_classification(JobsClassificationRunRequest(limit=2, force=False), db_session)
    assert response.selected == 2
    assert response.classified == 1
    assert response.jobs == [1]


def test_store_job_score(db_session):
    job = seed_job(db_session)
    scored = store_job_score(job.id, _score_payload(), db_session)

    assert scored.status == "scored"

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

    run_response = get_score_run(run.id, db_session)
    items_response = list_score_run_items(run.id, db_session)

    assert run_response.run_id == run.id
    assert items_response.total == 1

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

    notify = mark_job_notified(job.id, JobNotifyWrite(status="notified"), db_session)
    error = mark_job_error(job.id, JobErrorWrite(status="error"), db_session)
    notify_batch = mark_jobs_notified([JobNotifyBatchItem(id=job.id, status="notified")], db_session)

    assert notify.status == "notified"
    assert error.status == "error"
    assert notify_batch.updated == 1

    with pytest.raises(HTTPException):
        mark_job_notified(9999, JobNotifyWrite(status="notified"), db_session)
    with pytest.raises(HTTPException):
        mark_job_error(9999, JobErrorWrite(status="error"), db_session)
    with pytest.raises(HTTPException):
        mark_jobs_notified([JobNotifyBatchItem(id=9999, status="notified")], db_session)


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
