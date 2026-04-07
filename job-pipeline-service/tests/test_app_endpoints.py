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
    delete_interview_round,
    delete_prompt_library,
    ensure_job_postings_schema,
    get_job,
    get_application,
    get_prompt_library,
    get_run,
    health,
    ingest_jobs,
    list_applications,
    list_jobs,
    list_run_applications,
    list_runs,
    list_prompt_library,
    list_resumes,
    list_run_items,
    list_users,
    list_interview_rounds,
    mark_application_error,
    mark_application_notified,
    merge_responses,
    operational_error_handler,
    run_application_score,
    run_applications_generate,
    run_applications_score,
    run_job_classification,
    run_jobs_classification,
    store_application_score,
    update_application_status,
    update_interview_round,
    update_resume,
    update_prompt_library,
)
from models import JobApplication, Resume, User
from schemas import (
    ApplicationCreate,
    ApplicationErrorWrite,
    ApplicationGenerateRequest,
    ApplicationNotificationWrite,
    ApplicationScoreRunRequest,
    ApplicationScoreWrite,
    ApplicationsGenerateRunRequest,
    ApplicationsScoreRunRequest,
    ApplicationStatusWrite,
    InterviewRoundCreate,
    InterviewRoundUpdate,
    JobClassificationRunRequest,
    JobIngestItem,
    ResumeCreate,
    ResumeUpdate,
    JobsClassificationRunRequest,
    PromptLibraryCreate,
    PromptLibraryUpdate,
    UserCreate,
)
from services.llm_client import LlmRequestError
from services.prompt_service import PromptResolutionError
from services.scoring_service import JobScoringSkipped
from tests.helpers import seed_application, seed_job, seed_prompt, seed_resume, seed_score_run, seed_user


def _score_payload() -> ApplicationScoreWrite:
    return ApplicationScoreWrite(
        score=22,
        recommendation="Strong Apply",
        justification="Good fit",
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
    old = seed_job(db_session, job_id="job-old")
    old.classification_key = "Designer"
    old.classified_at = datetime.now(timezone.utc) - timedelta(days=2)

    new = seed_job(db_session, job_id="job-new")
    new.classification_key = "Product Manager"
    new.classified_at = datetime.now(timezone.utc)
    db_session.commit()

    response = list_jobs(
        db_session,
        source=None,
        classification_key="Product Manager",
        q=None,
        has_classification=None,
        has_applications=None,
        classified_since=datetime.now(timezone.utc) - timedelta(hours=1),
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
        source="greenhouse",
        classification_key=None,
        q=None,
        has_classification=None,
        has_applications=None,
        classified_since=None,
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
    captured = {}

    def _fake_classify_job(session, target_job, **kwargs):
        captured.update(kwargs)
        target_job.classification_key = "Product Manager"
        target_job.classification_prompt_version = 1
        target_job.classified_at = datetime.now(timezone.utc)
        return SimpleNamespace(job=target_job)

    monkeypatch.setattr(app_module, "classify_job", _fake_classify_job)
    ok = run_job_classification(
        job.id,
        JobClassificationRunRequest(classification_key="product", force=False),
        db_session,
    )
    assert ok.classification_key == "Product Manager"
    assert captured["classification_key"] == "product"

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

    response = run_jobs_classification(
        JobsClassificationRunRequest(limit=2, classification_key="product", force=False),
        db_session,
    )
    assert captured["force"] is False
    assert captured["classification_key"] == "product"
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


def test_user_and_resume_crud(db_session):
    user = create_user(UserCreate(name="Alice", email="alice@example.com"), db_session)
    resume = create_resume(
        ResumeCreate(
            user_id=user.id,
            name="PM Resume",
            prompt_key="product-scoring",
            classification_key="Product Manager",
            content="Resume body",
            is_active=True,
            is_default=False,
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
        ResumeUpdate(prompt_key="pm-custom", content="Updated resume body", is_active=False),
        db_session,
    )

    assert listed_users.total == 1
    assert listed_resumes.total == 1
    assert listed_resumes.items[0].prompt_key == "product-scoring"
    assert listed_resumes.items[0].classification_key == "Product Manager"
    assert listed_resumes.items[0].is_default is True
    assert updated_resume.content == "Updated resume body"
    assert updated_resume.is_active is False
    assert updated_resume.prompt_key == "pm-custom"

    with pytest.raises(HTTPException):
        create_resume(
            ResumeCreate(
                user_id=9999,
                name="Missing",
                prompt_key="default",
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
        score_min=None,
        score_max=None,
        created_since=None,
        updated_since=None,
        sort_by="created_at",
        sort_order="desc",
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
    notified = mark_application_notified(created.id, ApplicationNotificationWrite(status="notified"), db_session)
    errored = mark_application_error(created.id, ApplicationErrorWrite(status="error"), db_session)

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


def test_generate_applications_supports_default_resume_strategies(db_session):
    user = seed_user(db_session, name="Default User", email="default-user@example.com")
    job = seed_job(db_session, job_id="job-default-strategy")
    job.classification_key = "Designer"
    db_session.commit()

    default_resume = seed_resume(
        db_session,
        user=user,
        name="Default Resume",
        prompt_key="default",
        classification_key=None,
        content="Generic resume",
        is_default=True,
    )
    classified_resume = seed_resume(
        db_session,
        user=user,
        name="Designer Resume",
        prompt_key="designer",
        classification_key="Designer",
        content="Designer resume",
        is_default=False,
    )

    default_only = app_module.generate_applications(
        ApplicationGenerateRequest(job_posting_id=job.id, user_id=user.id, resume_strategy="default_only"),
        db_session,
    )

    assert default_only.created == 1
    created_default = db_session.scalars(
        select(JobApplication).where(JobApplication.job_posting_id == job.id).order_by(JobApplication.id.asc())
    ).all()
    assert [application.resume_id for application in created_default] == [default_resume.id]

    db_session.query(JobApplication).delete()
    db_session.commit()

    default_fallback = app_module.generate_applications(
        ApplicationGenerateRequest(job_posting_id=job.id, user_id=user.id, resume_strategy="default_fallback"),
        db_session,
    )

    assert default_fallback.created == 1
    created_fallback = db_session.scalars(
        select(JobApplication).where(JobApplication.job_posting_id == job.id).order_by(JobApplication.id.asc())
    ).all()
    assert [application.resume_id for application in created_fallback] == [classified_resume.id]


def test_resume_defaults_and_independent_prompt_key(db_session):
    user = seed_user(db_session, name="Resume Owner", email="resume-owner@example.com")

    first = create_resume(
        ResumeCreate(
            user_id=user.id,
            name="Default Resume",
            prompt_key="default-scoring",
            classification_key=None,
            content="Generic resume",
            is_active=True,
            is_default=False,
        ),
        db_session,
    )
    second = create_resume(
        ResumeCreate(
            user_id=user.id,
            name="PM Resume",
            prompt_key="pm-scoring",
            classification_key="Product Manager",
            content="PM resume",
            is_active=True,
            is_default=True,
        ),
        db_session,
    )

    first_db = db_session.get(Resume, first.id)
    second_db = db_session.get(Resume, second.id)

    assert first_db is not None and first_db.is_default is False
    assert second_db is not None and second_db.is_default is True

    updated = update_resume(
        second.id,
        ResumeUpdate(classification_key="Product", prompt_key="pm-v2", is_default=False),
        db_session,
    )

    db_session.refresh(first_db)
    db_session.refresh(second_db)
    assert updated.classification_key == "Product"
    assert updated.prompt_key == "pm-v2"
    assert first_db.is_default is True
    assert second_db.is_default is False


def test_run_applications_generate_for_user(db_session):
    user = seed_user(db_session, name="Batch User", email="batch@example.com")
    other_user = seed_user(db_session, name="Other User", email="other-batch@example.com")
    matching_resume = seed_resume(db_session, user=user, name="PM Resume", prompt_key="Product Manager", content="Resume")
    seed_resume(db_session, user=other_user, name="Other Resume", prompt_key="Product Manager", content="Resume")

    eligible = seed_job(db_session, job_id="job-eligible")
    eligible.classification_key = "Product Manager"
    already_generated = seed_job(db_session, job_id="job-existing")
    already_generated.classification_key = "Product Manager"
    no_match = seed_job(db_session, job_id="job-no-match")
    no_match.classification_key = "Designer"
    unclassified = seed_job(db_session, job_id="job-unclassified")
    db_session.commit()

    seed_application(db_session, user=user, job=already_generated, resume=matching_resume, status="new")

    result = run_applications_generate(
        ApplicationsGenerateRunRequest(user_id=user.id, limit=10),
        db_session,
    )

    assert result.selected == 1
    assert result.processed == 1
    assert result.created == 1
    assert result.skipped == 0
    assert result.jobs == [eligible.id]
    created_applications = db_session.scalars(
        select(JobApplication).where(JobApplication.user_id == user.id, JobApplication.job_posting_id == eligible.id)
    ).all()
    assert result.applications == [created_applications[0].id]
    assert len(created_applications) == 1


def test_run_applications_generate_uses_default_resume_strategy(db_session):
    user = seed_user(db_session, name="Default Batch User", email="default-batch@example.com")
    default_resume = seed_resume(
        db_session,
        user=user,
        name="Default Resume",
        prompt_key="default",
        classification_key=None,
        content="Resume",
        is_default=True,
    )
    seed_resume(
        db_session,
        user=user,
        name="PM Resume",
        prompt_key="product",
        classification_key="Product Manager",
        content="Resume",
        is_default=False,
    )

    eligible = seed_job(db_session, job_id="job-default-eligible")
    eligible.classification_key = "Designer"
    db_session.commit()

    result = run_applications_generate(
        ApplicationsGenerateRunRequest(user_id=user.id, limit=10, resume_strategy="default_only"),
        db_session,
    )

    assert result.selected == 1
    assert result.created == 1
    application = db_session.scalar(
        select(JobApplication).where(JobApplication.job_posting_id == eligible.id, JobApplication.user_id == user.id)
    )
    assert application is not None
    assert application.resume_id == default_resume.id


def test_run_applications_generate_empty_selection_and_missing_user(db_session):
    user = seed_user(db_session, name="No Match", email="nomatch@example.com")
    job = seed_job(db_session, job_id="job-designer")
    job.classification_key = "Designer"
    seed_resume(db_session, user=user, name="PM Resume", prompt_key="Product Manager", content="Resume")
    db_session.commit()

    result = run_applications_generate(
        ApplicationsGenerateRunRequest(user_id=user.id, limit=10),
        db_session,
    )

    assert result.selected == 0
    assert result.jobs == []
    assert result.applications == []

    with pytest.raises(HTTPException):
        run_applications_generate(ApplicationsGenerateRunRequest(user_id=9999, limit=10), db_session)


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
        mark_application_notified(9999, ApplicationNotificationWrite(status="notified"), db_session)
    with pytest.raises(HTTPException):
        mark_application_error(9999, ApplicationErrorWrite(status="error"), db_session)
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
        classification_key=None,
        recommendation=None,
        status="scored",
        score_min=20,
        score_max=None,
        created_since=None,
        updated_since=None,
        sort_by="created_at",
        sort_order="desc",
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].id == high.id


def test_list_applications_filters_by_classification_key(db_session):
    user = seed_user(db_session, name="Class Filter", email="class-filter@example.com")
    matched_job = seed_job(db_session, job_id="job-class-match")
    matched_job.classification_key = "Product Manager"
    other_job = seed_job(db_session, job_id="job-class-other")
    other_job.classification_key = "Designer"
    resume = seed_resume(db_session, user=user, prompt_key="default")

    matched_application = seed_application(db_session, user=user, job=matched_job, resume=resume, status="scored")
    matched_application.score = 40
    other_application = seed_application(db_session, user=user, job=other_job, resume=resume, status="scored")
    other_application.score = 42
    db_session.commit()

    response = list_applications(
        db_session,
        user_id=user.id,
        resume_id=None,
        job_posting_id=None,
        classification_key="Product Manager",
        recommendation=None,
        status="scored",
        score_min=None,
        score_max=None,
        created_since=None,
        updated_since=None,
        sort_by="score",
        sort_order="desc",
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].id == matched_application.id
    assert response.items[0].classification_key == "Product Manager"
    assert response.items[0].id != other_application.id


def test_list_applications_filters_by_recommendation(db_session):
    user = seed_user(db_session, name="Rec Filter", email="rec-filter@example.com")
    job = seed_job(db_session, job_id="job-rec-filter")
    resume = seed_resume(db_session, user=user, name="Resume A", prompt_key="default")
    matched = seed_application(db_session, user=user, job=job, resume=resume, status="scored")
    matched.score = 88
    matched.recommendation = "Strong Apply"

    other_resume = seed_resume(db_session, user=user, name="Resume B", prompt_key="default")
    other = seed_application(db_session, user=user, job=job, resume=other_resume, status="scored")
    other.score = 72
    other.recommendation = "Selective Apply"
    db_session.commit()

    response = list_applications(
        db_session,
        user_id=user.id,
        resume_id=None,
        job_posting_id=None,
        classification_key=None,
        recommendation="Strong Apply",
        status="scored",
        score_min=None,
        score_max=None,
        created_since=None,
        updated_since=None,
        sort_by="score",
        sort_order="desc",
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].id == matched.id
    assert response.items[0].recommendation == "Strong Apply"
    assert response.items[0].id != other.id


def test_list_applications_normalizes_legacy_scoring_json_shapes(db_session):
    user = seed_user(db_session, name="Legacy JSON", email="legacy-json@example.com")
    job = seed_job(db_session, job_id="job-legacy-json")
    resume = seed_resume(db_session, user=user, prompt_key="default")
    application = seed_application(db_session, user=user, job=job, resume=resume, status="scored")
    application.missing_from_jd = "Direct experience in crypto-driven personalization."
    application.gaps = "No explicit marketplace ownership."
    application.gating_flags = "Needs sponsorship"
    application.dimension_scores = {"domain_fit": 4, "invalid": "high"}
    db_session.commit()

    response = list_applications(
        db_session,
        user_id=user.id,
        resume_id=None,
        job_posting_id=None,
        classification_key=None,
        recommendation=None,
        status="scored",
        score_min=None,
        score_max=None,
        created_since=None,
        updated_since=None,
        sort_by="created_at",
        sort_order="desc",
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].missing_from_jd == ["Direct experience in crypto-driven personalization."]
    assert response.items[0].gaps == ["No explicit marketplace ownership."]
    assert response.items[0].gating_flags == ["Needs sponsorship"]
    assert response.items[0].dimension_scores == {"domain_fit": 4.0}


def test_run_applications_score_batch(db_session, monkeypatch):
    user = seed_user(db_session, name="Gina", email="gina@example.com")
    job = seed_job(db_session, job_id="job-batch")
    resume_one = seed_resume(db_session, user=user, name="Resume 1", prompt_key="default", content="Resume body 1")
    resume_two = seed_resume(db_session, user=user, name="Resume 2", prompt_key="default", content="Resume body 2")
    application_one = seed_application(db_session, user=user, job=job, resume=resume_one, status="new")
    application_two = seed_application(db_session, user=user, job=job, resume=resume_two, status="new")

    captured = {}

    def _fake_enqueue(session, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            id=21,
            type="application_scoring",
            status="queued",
            selected_count=2,
            callback_url=kwargs.get("callback_url"),
            created_at=datetime.now(timezone.utc),
            started_at=None,
            finished_at=None,
            last_error=None,
            requested_status=kwargs.get("status"),
            requested_source=None,
            prompt_key=kwargs.get("prompt_key"),
            force=kwargs.get("force", False),
            callback_status=None,
            callback_error=None,
        )

    monkeypatch.setattr(app_module, "enqueue_application_score_run", _fake_enqueue)
    monkeypatch.setattr(app_module, "_commit_or_fail", lambda _session: None)
    monkeypatch.setattr(db_session, "refresh", lambda _obj: None)
    monkeypatch.setattr(app_module, "serialize_application_score_run", lambda _session, run: {
        "run_id": run.id,
        "type": run.type,
        "status": run.status,
        "selected": run.selected_count,
        "processed": 0,
        "scored": 0,
        "errored": 0,
        "skipped": 0,
        "jobs": [job.id, job.id],
        "applications": [application_one.id, application_two.id],
        "callback_url": run.callback_url,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "last_error": run.last_error,
    })

    result = run_applications_score(
        ApplicationsScoreRunRequest(
            status="new",
            limit=10,
            user_id=user.id,
            classification_key="product",
            force=False,
            callback_url="https://example.com/callback",
        ),
        db_session,
    )

    assert captured["status"] == "new"
    assert captured["classification_key"] == "product"
    assert captured["prompt_key"] is None
    assert captured["callback_url"] == "https://example.com/callback"
    assert result.run_id == 21
    assert result.type == "application_scoring"
    assert result.selected == 2
    assert result.processed == 0
    assert result.scored == 0
    assert result.skipped == 0
    assert result.errored == 0
    assert result.applications == [application_one.id, application_two.id]


def test_run_applications_score_empty_selection(db_session):
    result = run_applications_score(
        ApplicationsScoreRunRequest(status="new", limit=10, user_id=9999, force=False),
        db_session,
    )

    assert result.selected == 0
    assert result.processed == 0
    assert result.applications == []


def test_run_applications_score_creates_generic_run_items(db_session):
    seed_prompt(db_session)
    user = seed_user(db_session, name="Gina", email="gina2@example.com")
    job = seed_job(db_session, job_id="job-batch-2")
    resume = seed_resume(db_session, user=user, name="Resume 1", prompt_key="default", content="Resume body 1")
    application = seed_application(db_session, user=user, job=job, resume=resume, status="new")

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

    assert result.status == "queued"
    assert result.selected == 1
    assert result.applications == [application.id]
    generic_items = list_run_items(result.run_id, db_session)
    assert generic_items.items[0].job_application_id == application.id
    assert generic_items.items[0].type == "application_scoring"


def test_application_scoring_and_interview_rounds(db_session, monkeypatch):
    user = seed_user(db_session, name="Cara", email="cara@example.com")
    job = seed_job(db_session, job_id="job-score")
    resume = seed_resume(db_session, user=user, prompt_key="default", content="Resume body")
    application = seed_application(db_session, user=user, job=job, resume=resume, status="new")

    manual = store_application_score(application.id, _score_payload(), db_session)
    assert manual.status == "scored"

    application.status = "new"
    db_session.commit()

    captured = {}

    def _fake_score_application(session, target_application, **kwargs):
        captured.update(kwargs)
        target_application.status = "scored"
        target_application.score = 91
        target_application.scored_at = datetime.now(timezone.utc)
        return SimpleNamespace(application=target_application)

    monkeypatch.setattr(app_module, "score_application", _fake_score_application)
    scored = run_application_score(
        application.id,
        ApplicationScoreRunRequest(classification_key="product", force=False),
        db_session,
    )
    assert scored.score == 91
    assert captured["classification_key"] == "product"

    round_one = create_interview_round(
        application.id,
        InterviewRoundCreate(round_number=1, stage_name="Hiring Manager"),
        db_session,
    )
    updated_round = update_interview_round(
        application.id,
        round_one.id,
        InterviewRoundUpdate(status="completed", completed_at=datetime.now(timezone.utc), notes="Strong signal"),
        db_session,
    )
    rounds = list_interview_rounds(application.id, db_session)
    assert round_one.round_number == 1
    assert updated_round.status == "completed"
    assert rounds.total == 1

    with pytest.raises(HTTPException):
        create_interview_round(
            application.id,
            InterviewRoundCreate(round_number=1, stage_name="Duplicate"),
            db_session,
        )

    deleted = delete_interview_round(application.id, round_one.id, db_session)
    assert deleted == {"deleted": True, "id": round_one.id}
    assert list_interview_rounds(application.id, db_session).total == 0


def test_application_reads_include_job_context(db_session):
    user = seed_user(db_session, name="Dana", email="dana@example.com")
    job = seed_job(db_session, job_id="job-app-read")
    job.company_name = "Acme Labs"
    job.title = "Senior PM"
    job.apply_url = "https://example.com/jobs/123"
    job.yearly_min_compensation = 150000
    job.yearly_max_compensation = 180000
    job.classification_key = "Product Manager"
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
        score_min=None,
        score_max=None,
        created_since=None,
        updated_since=None,
        sort_by="created_at",
        sort_order="desc",
        limit=10,
        offset=0,
    )
    fetched = get_application(application.id, db_session)

    assert listed.total == 1
    assert listed.items[0].job_id == "job-app-read"
    assert listed.items[0].company_name == "Acme Labs"
    assert listed.items[0].title == "Senior PM"
    assert listed.items[0].apply_url == "https://example.com/jobs/123"
    assert listed.items[0].classification_key == "Product Manager"
    assert listed.items[0].resume_name == "PM Resume"
    assert fetched.job_id == "job-app-read"
    assert fetched.company_name == "Acme Labs"
    assert fetched.resume_name == "PM Resume"


def test_jobs_list_supports_text_search_and_application_presence(db_session):
    matched = seed_job(db_session, job_id="acme-role-1", source="linkedin")
    matched.company_name = "Acme Labs"
    matched.title = "Principal Product Manager"
    matched.classification_key = "Product Manager"

    other = seed_job(db_session, job_id="other-role-1", source="linkedin")
    other.company_name = "Other Corp"
    other.title = "Designer"
    other.classification_key = None

    user = seed_user(db_session, name="Search User", email="search-user@example.com")
    resume = seed_resume(db_session, user=user, prompt_key="default")
    seed_application(db_session, user=user, job=matched, resume=resume, status="new")
    db_session.commit()

    response = list_jobs(
        db_session,
        source="linkedin",
        classification_key=None,
        q="principal",
        has_classification=True,
        has_applications=True,
        classified_since=None,
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].id == matched.id
    assert response.items[0].job_id == "acme-role-1"
    assert other.id != response.items[0].id


def test_list_runs_filters_and_paginates(db_session):
    first_job = seed_job(db_session, job_id="run-job-1")
    second_job = seed_job(db_session, job_id="run-job-2")

    old_run = seed_score_run(db_session, job=first_job, status="completed")
    old_run.type = "application_scoring"
    old_run.requested_status = "new"
    old_run.prompt_key = "default"
    old_run.callback_status = "delivered"
    old_run.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    old_run.updated_at = old_run.created_at
    old_item = db_session.scalar(select(app_module.RunItem).where(app_module.RunItem.run_id == old_run.id))
    old_item.status = "scored"

    new_run = seed_score_run(db_session, job=second_job, status="failed")
    new_run.type = "classification"
    new_run.requested_status = ""
    new_run.requested_source = "linkedin"
    new_run.classification_key = "Product Manager"
    new_run.prompt_key = "classifier-v1"
    new_run.callback_status = "failed"
    new_run.created_at = datetime.now(timezone.utc)
    new_run.updated_at = new_run.created_at
    new_item = db_session.scalar(select(app_module.RunItem).where(app_module.RunItem.run_id == new_run.id))
    new_item.status = "error"
    new_item.error_message = "boom"
    db_session.commit()

    response = list_runs(
        db_session,
        type="classification",
        status="failed",
        requested_status="",
        requested_source="linkedin",
        classification_key="Product Manager",
        prompt_key="classifier-v1",
        callback_status="failed",
        created_since=datetime.now(timezone.utc) - timedelta(hours=1),
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].run_id == new_run.id
    assert response.items[0].errored == 1
    assert response.items[0].jobs == [second_job.id]


def test_list_run_applications_returns_joined_job_rows(db_session):
    user = seed_user(db_session, name="Run View User", email="run-view-user@example.com")
    job = seed_job(db_session, job_id="run-job-view")
    job.company_name = "Acme Labs"
    job.title = "Staff Product Manager"
    job.classification_key = "Product Manager"
    job.apply_url = "https://example.com/apply/1"
    job.yearly_min_compensation = 180000
    job.yearly_max_compensation = 220000
    resume = seed_resume(db_session, user=user, name="PM Resume", prompt_key="default")
    application = seed_application(db_session, user=user, job=job, resume=resume, status="scored")
    application.score = 91
    application.screening_likelihood = 72
    application.recommendation = "Apply"
    application.scored_at = datetime.now(timezone.utc)
    db_session.commit()

    run = seed_score_run(db_session, job=job, status="completed")
    run.type = "application_scoring"
    run_item = db_session.scalar(select(app_module.RunItem).where(app_module.RunItem.run_id == run.id))
    run_item.job_application_id = application.id
    run_item.status = "scored"
    db_session.commit()

    response = list_run_applications(
        run.id,
        db_session,
        run_item_status=None,
        score_min=None,
        score_max=None,
        sort_by="score",
        sort_order="desc",
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].run_item_id == run_item.id
    assert response.items[0].job_application_id == application.id
    assert response.items[0].job_id == "run-job-view"
    assert response.items[0].company_name == "Acme Labs"
    assert response.items[0].title == "Staff Product Manager"
    assert response.items[0].score == 91
    assert response.items[0].screening_likelihood == 72
    assert response.items[0].classification_key == "Product Manager"
    assert response.items[0].apply_url == "https://example.com/apply/1"
    assert response.items[0].yearly_min_compensation == 180000
    assert response.items[0].yearly_max_compensation == 220000
    assert response.items[0].resume_name == "PM Resume"


def test_list_run_applications_supports_filters_and_sorting(db_session):
    user = seed_user(db_session, name="Run Filter User", email="run-filter-user@example.com")
    low_job = seed_job(db_session, job_id="run-job-low")
    high_job = seed_job(db_session, job_id="run-job-high")
    low_resume = seed_resume(db_session, user=user, name="Resume Low", prompt_key="default")
    high_resume = seed_resume(db_session, user=user, name="Resume High", prompt_key="default")
    low_application = seed_application(db_session, user=user, job=low_job, resume=low_resume, status="scored")
    high_application = seed_application(db_session, user=user, job=high_job, resume=high_resume, status="scored")
    low_application.score = 15
    high_application.score = 55
    db_session.commit()

    run = seed_score_run(db_session, job=low_job, status="completed")
    run.type = "application_scoring"
    items = db_session.scalars(
        select(app_module.RunItem).where(app_module.RunItem.run_id == run.id).order_by(app_module.RunItem.id.asc())
    ).all()
    low_item = items[0]
    low_item.job_application_id = low_application.id
    low_item.status = "error"

    high_item = app_module.RunItem(
        run_id=run.id,
        type="application_scoring",
        job_posting_id=high_job.id,
        job_application_id=high_application.id,
        status="scored",
    )
    db_session.add(high_item)
    db_session.commit()

    response = list_run_applications(
        run.id,
        db_session,
        run_item_status="scored",
        score_min=20,
        score_max=None,
        sort_by="score",
        sort_order="desc",
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].job_application_id == high_application.id
    assert response.items[0].score == 55

    with pytest.raises(HTTPException, match="Unsupported run application sort field"):
        list_run_applications(
            run.id,
            db_session,
            run_item_status=None,
            score_min=None,
            score_max=None,
            sort_by="resume_name",
            sort_order="desc",
            limit=10,
            offset=0,
        )

    with pytest.raises(HTTPException, match="was not found"):
        list_run_applications(
            9999,
            db_session,
            run_item_status=None,
            score_min=None,
            score_max=None,
            sort_by="score",
            sort_order="desc",
            limit=10,
            offset=0,
        )


def test_list_applications_supports_dates_and_sorting(db_session):
    user = seed_user(db_session, name="Sort User", email="sort-user@example.com")
    job = seed_job(db_session, job_id="job-sort")
    first_resume = seed_resume(db_session, user=user, name="Resume 1", prompt_key="default")
    second_resume = seed_resume(db_session, user=user, name="Resume 2", prompt_key="default")

    older = seed_application(db_session, user=user, job=job, resume=first_resume, status="scored")
    older.score = 12
    older.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    older.updated_at = older.created_at

    newer = seed_application(db_session, user=user, job=job, resume=second_resume, status="scored")
    newer.score = 42
    newer.created_at = datetime.now(timezone.utc)
    newer.updated_at = newer.created_at
    db_session.commit()

    response = list_applications(
        db_session,
        user_id=user.id,
        resume_id=None,
        job_posting_id=job.id,
        status="scored",
        score_min=10,
        score_max=50,
        created_since=datetime.now(timezone.utc) - timedelta(days=1),
        updated_since=datetime.now(timezone.utc) - timedelta(days=1),
        sort_by="score",
        sort_order="desc",
        limit=10,
        offset=0,
    )

    assert response.total == 1
    assert response.items[0].id == newer.id
    assert response.items[0].score == 42

    with pytest.raises(HTTPException, match="Unsupported application sort field"):
        list_applications(
            db_session,
            user_id=user.id,
            resume_id=None,
            job_posting_id=None,
            status=None,
            score_min=None,
            score_max=None,
            created_since=None,
            updated_since=None,
            sort_by="company_name",
            sort_order="desc",
            limit=10,
            offset=0,
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


def test_exception_handlers(db_session, monkeypatch):
    user = seed_user(db_session, name="Prompt User", email="prompt-user@example.com")
    job = seed_job(db_session)
    resume = seed_resume(db_session, user=user, prompt_key="default", content="Resume body")
    application = seed_application(db_session, user=user, job=job, resume=resume)

    def _raise_prompt(*_args, **_kwargs):
        raise PromptResolutionError("prompt missing")

    monkeypatch.setattr(app_module, "score_application", _raise_prompt)
    with pytest.raises(PromptResolutionError) as exc:
        run_application_score(application.id, ApplicationScoreRunRequest(force=False), db_session)
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
        lambda _engine: SimpleNamespace(get_columns=lambda _table: [{"name": "classification_key"}]),
    )
    monkeypatch.setattr(app_module, "text", lambda statement: statement)

    ensure_job_postings_schema()

    assert any("ADD COLUMN classification_prompt_version INTEGER" in statement for statement in executed)
    assert any("ADD COLUMN classification_provider VARCHAR(100)" in statement for statement in executed)
    assert all("ADD COLUMN classification_key" not in statement for statement in executed)


def test_ensure_job_postings_schema_returns_when_no_statements(monkeypatch):
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    begin_calls = []

    monkeypatch.setattr(app_module, "engine", fake_engine)
    monkeypatch.setattr(
        app_module,
        "inspect",
        lambda _engine: SimpleNamespace(
            get_columns=lambda _table: [{"name": name} for name in (
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
    monkeypatch.setattr(app_module, "run_startup_backfill", lambda session: calls.append(("startup_backfill", session)))
    monkeypatch.setattr(app_module.run_worker, "start", lambda: calls.append(("start", None)))
    monkeypatch.setattr(app_module.run_worker, "stop", lambda: calls.append(("stop", None)))

    async def _run():
        async with app_module.lifespan(app_module.app):
            calls.append(("inside", None))

    asyncio.run(_run())

    assert [name for name, _ in calls] == [
        "create_all",
        "ensure_schema",
        "ensure_prompt_schema",
        "startup_backfill",
        "start",
        "inside",
        "stop",
    ]


def test_operational_error_handler_branches(db_session, monkeypatch):
    user = seed_user(db_session, name="Error User", email="error-user@example.com")
    job = seed_job(db_session)
    resume = seed_resume(db_session, user=user, prompt_key="default", content="Resume body")
    application = seed_application(db_session, user=user, job=job, resume=resume)

    def _raise_locked(*_args, **_kwargs):
        raise app_module.OperationalError("stmt", {}, Exception("database is locked"))

    monkeypatch.setattr(app_module, "_commit_or_fail", _raise_locked)
    with pytest.raises(app_module.OperationalError) as locked_exc:
        store_application_score(application.id, _score_payload(), db_session)
    locked_response = asyncio.run(app_module.operational_error_handler(None, locked_exc.value))
    assert locked_response.status_code == 503

    def _raise_generic(*_args, **_kwargs):
        raise app_module.OperationalError("stmt", {}, Exception("generic db issue"))

    monkeypatch.setattr(app_module, "_commit_or_fail", _raise_generic)
    with pytest.raises(app_module.OperationalError) as generic_exc:
        store_application_score(application.id, _score_payload(), db_session)
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
    application = JobApplication(status="interview")

    app_module.apply_application_status(application, ApplicationStatusWrite(status=status))

    assert application.status == status
    assert getattr(application, timestamp_field) is not None


def test_apply_application_error_preserves_non_error_status():
    application = JobApplication(status="scored")

    app_module.apply_application_error(application, ApplicationErrorWrite(status="rejected"))
    assert application.status == "rejected"
    assert application.last_error_at is not None

    app_module.apply_application_error(application, ApplicationErrorWrite(status="error"))
    assert application.status == "new"


@pytest.mark.parametrize(
    ("status", "timestamp_field"),
    [
        ("ghosted", "ghosted_at"),
        ("pass", "passed_at"),
    ],
)
def test_apply_application_status_sets_new_terminal_timestamps(status, timestamp_field):
    application = JobApplication(status="interview")

    app_module.apply_application_status(application, ApplicationStatusWrite(status=status))

    assert application.status == status
    assert getattr(application, timestamp_field) is not None


def test_apply_application_status_rejects_invalid_transition():
    application = JobApplication(status="new")

    with pytest.raises(HTTPException, match="Cannot transition application from 'new' to 'screening'"):
        app_module.apply_application_status(application, ApplicationStatusWrite(status="screening"))


def test_list_applications_filters_active_status_group(db_session):
    user = seed_user(db_session, name="Ava", email="ava@example.com")
    resume = seed_resume(db_session, user=user, name="Base", prompt_key="default")
    job_one = seed_job(db_session, job_id="job-active-1")
    job_two = seed_job(db_session, job_id="job-active-2")
    job_three = seed_job(db_session, job_id="job-active-3")
    seed_application(db_session, user=user, job=job_one, resume=resume, status="applied")
    seed_application(db_session, user=user, job=job_two, resume=resume, status="screening")
    seed_application(db_session, user=user, job=job_three, resume=resume, status="rejected")

    response = list_applications(db_session, user_id=user.id, status_group="active")

    assert response.total == 2
    assert {item.status for item in response.items} == {"applied", "screening"}


def test_list_applications_filters_by_text_search(db_session):
    user = seed_user(db_session, name="Bea", email="bea@example.com")
    resume = seed_resume(db_session, user=user, name="Base", prompt_key="default")

    matched_job = seed_job(db_session, job_id="job-search-1")
    matched_job.company_name = "Acme Robotics"
    matched_job.title = "Senior Product Manager"

    other_job = seed_job(db_session, job_id="job-search-2")
    other_job.company_name = "Northwind"
    other_job.title = "Designer"
    db_session.commit()

    seed_application(db_session, user=user, job=matched_job, resume=resume, status="applied")
    seed_application(db_session, user=user, job=other_job, resume=resume, status="applied")

    by_company = list_applications(db_session, user_id=user.id, q="Acme")
    by_title = list_applications(db_session, user_id=user.id, q="Product Manager")

    assert by_company.total == 1
    assert by_company.items[0].company_name == "Acme Robotics"
    assert by_title.total == 1
    assert by_title.items[0].title == "Senior Product Manager"


def test_ensure_prompt_library_and_resumes_schema_branches(monkeypatch):
    prompt_executed = []
    resume_executed = []
    run_executed = []

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
        lambda _engine: SimpleNamespace(get_columns=lambda _table: [{"name": "classification_key"}, {"name": "is_default"}]),
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
    assert any("ALTER TABLE resumes ADD COLUMN is_default BOOLEAN DEFAULT FALSE" in statement for statement in resume_executed)

    monkeypatch.setattr(
        app_module,
        "inspect",
        lambda _engine: SimpleNamespace(
            get_columns=lambda table: [{"name": "requested_status"}] if table == "runs" else [{"name": "run_id"}]
        ),
    )
    monkeypatch.setattr(fake_engine, "begin", lambda: FakeBegin(run_executed), raising=False)

    app_module.ensure_run_schema()

    assert any("ALTER TABLE runs ADD COLUMN type VARCHAR(50)" in statement for statement in run_executed)
    assert any("ALTER TABLE runs ADD COLUMN classification_key VARCHAR(255)" in statement for statement in run_executed)
    assert any("UPDATE runs" in statement and "SET classification_key = prompt_key" in statement for statement in run_executed)
    assert any("ALTER TABLE run_items ADD COLUMN type VARCHAR(50)" in statement for statement in run_executed)
    assert any("ALTER TABLE run_items ADD COLUMN job_application_id INTEGER" in statement for statement in run_executed)
