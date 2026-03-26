import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import app as app_module
from app import (
    create_prompt_library,
    delete_prompt_library,
    get_job,
    get_prompt_library,
    get_score_run,
    health,
    ingest_jobs,
    list_jobs,
    list_prompt_library,
    list_score_run_items,
    mark_job_error,
    mark_job_notified,
    mark_jobs_notified,
    run_job_score,
    run_jobs_score,
    store_job_score,
    store_job_scores,
    update_prompt_library,
)
from schemas import (
    JobErrorWrite,
    JobIngestItem,
    JobNotifyBatchItem,
    JobNotifyWrite,
    JobScoreBatchItem,
    JobScoreRunRequest,
    JobScoreWrite,
    JobsScoreRunRequest,
    PromptLibraryCreate,
    PromptLibraryUpdate,
)
from services.llm_client import LlmRequestError
from services.prompt_service import PromptResolutionError
from services.scoring_service import JobScoringResult, JobScoringSkipped
from tests.helpers import seed_job, seed_prompt, seed_score_run


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


def test_get_job_by_id(db_session):
    job = seed_job(db_session)
    found = get_job(job.id, db_session)

    assert found.id == job.id

    with pytest.raises(HTTPException, match="was not found"):
        get_job(9999, db_session)


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


def test_prompt_library_crud(db_session):
    create = create_prompt_library(
        PromptLibraryCreate(
            prompt_key="default",
            prompt_version=1,
            system_prompt="System",
            user_prompt_template="User",
            base_resume_template="Resume",
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


def test_prompt_library_conflicts(db_session):
    payload = PromptLibraryCreate(
        prompt_key="default",
        prompt_version=1,
        system_prompt="System",
        user_prompt_template="User",
        base_resume_template="Resume",
        is_active=True,
    )
    create_prompt_library(payload, db_session)

    with pytest.raises(HTTPException) as exc:
        create_prompt_library(payload, db_session)
    assert exc.value.status_code == 409


def test_exception_handlers(db_session, monkeypatch):
    seed_job(db_session)

    def _raise_prompt(*_args, **_kwargs):
        raise PromptResolutionError("prompt missing")

    monkeypatch.setattr(app_module, "score_job", _raise_prompt)
    with pytest.raises(PromptResolutionError) as exc:
        run_job_score(1, JobScoreRunRequest(force=False), db_session)
    response = asyncio.run(app_module.prompt_resolution_error_handler(None, exc.value))
    assert response.status_code == 503

    def _raise_llm(*_args, **_kwargs):
        raise LlmRequestError("llm unavailable")

    monkeypatch.setattr(app_module, "score_job", _raise_llm)
    with pytest.raises(LlmRequestError) as exc2:
        run_job_score(1, JobScoreRunRequest(force=False), db_session)
    response2 = asyncio.run(app_module.llm_request_error_handler(None, exc2.value))
    assert response2.status_code == 503


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
