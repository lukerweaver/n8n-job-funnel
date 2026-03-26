import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError

import app as app_module
from app import (
    _commit_or_fail,
    create_prompt_library,
    delete_prompt_library,
    ensure_job_postings_schema,
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
    merge_responses,
    operational_error_handler,
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
            prompt_version=3,
            system_prompt="New system",
            user_prompt_template="New user",
            base_resume_template="New resume",
            is_active=False,
        ),
        db_session,
    )

    assert updated.prompt_key == "custom"
    assert updated.prompt_version == 3
    assert updated.system_prompt == "New system"
    assert updated.user_prompt_template == "New user"
    assert updated.base_resume_template == "New resume"
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
    monkeypatch.setattr(app_module.score_run_worker, "start", lambda: calls.append(("start", None)))
    monkeypatch.setattr(app_module.score_run_worker, "stop", lambda: calls.append(("stop", None)))

    async def _run():
        async with app_module.lifespan(app_module.app):
            calls.append(("inside", None))

    asyncio.run(_run())

    assert [name for name, _ in calls] == ["create_all", "ensure_schema", "start", "inside", "stop"]


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
