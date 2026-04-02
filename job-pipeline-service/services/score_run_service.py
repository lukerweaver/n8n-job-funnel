import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib import error, request

from sqlalchemy import func, select

from database import SessionLocal
from models import JobApplication, JobPosting, PromptLibrary, Run, RunItem
from services.classification_service import classify_job
from services.llm_client import build_llm_client
from services.prompt_service import resolve_active_prompt, resolve_prompt_selector
from services.scoring_service import JobScoringSkipped, _commit_scoring_progress, score_application, score_job


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScoreRunCounts:
    processed: int
    succeeded: int
    errored: int
    skipped: int
    jobs: list[int]
    applications: list[int]


SUCCESS_STATUSES = {"scored", "classified"}


def enqueue_run(
    session,
    *,
    run_type: str,
    limit: int,
    status: str = "",
    source: str | None = None,
    classification_key: str | None = None,
    prompt_key: str | None = None,
    force: bool = False,
    callback_url: str | None = None,
) -> Run:
    query = select(JobPosting).order_by(JobPosting.created_at.asc()).limit(limit)

    if status:
        query = query.where(JobPosting.status == status)

    if source:
        query = query.where(JobPosting.source == source)

    if run_type == "classification" and not force:
        query = query.where(JobPosting.classification_key.is_(None))

    jobs = list(session.scalars(query).all())
    effective_prompt_key = resolve_prompt_selector(prompt_key=prompt_key, classification_key=classification_key)
    run = Run(
        type=run_type,
        status="queued",
        requested_status=status,
        requested_source=source,
        classification_key=classification_key,
        prompt_key=effective_prompt_key,
        force=force,
        callback_url=callback_url,
        selected_count=len(jobs),
    )
    session.add(run)
    session.flush()

    for job in jobs:
        session.add(
            RunItem(
                score_run_id=run.id,
                type=run_type,
                job_posting_id=job.id,
                status="queued",
            )
        )

    return run


def enqueue_application_score_run(
    session,
    *,
    limit: int,
    status: str,
    user_id: int | None = None,
    resume_id: int | None = None,
    job_posting_id: int | None = None,
    classification_key: str | None = None,
    prompt_key: str | None = None,
    force: bool = False,
    callback_url: str | None = None,
) -> Run:
    query = select(JobApplication).order_by(JobApplication.created_at.asc()).limit(limit)

    if status:
        query = query.where(JobApplication.status == status)
    if user_id is not None:
        query = query.where(JobApplication.user_id == user_id)
    if resume_id is not None:
        query = query.where(JobApplication.resume_id == resume_id)
    if job_posting_id is not None:
        query = query.where(JobApplication.job_posting_id == job_posting_id)

    applications = list(session.scalars(query).all())
    effective_prompt_key = resolve_prompt_selector(prompt_key=prompt_key, classification_key=classification_key)
    run = Run(
        type="application_scoring",
        status="queued",
        requested_status=status,
        requested_source=None,
        classification_key=classification_key,
        prompt_key=effective_prompt_key,
        force=force,
        callback_url=callback_url,
        selected_count=len(applications),
    )
    session.add(run)
    session.flush()

    for application in applications:
        session.add(
            RunItem(
                score_run_id=run.id,
                type="application_scoring",
                job_posting_id=application.job_posting_id,
                job_application_id=application.id,
                status="queued",
            )
        )

    return run


def enqueue_score_run(
    session,
    *,
    limit: int,
    status: str,
    source: str | None = None,
    classification_key: str | None = None,
    prompt_key: str | None = None,
    force: bool = False,
    callback_url: str | None = None,
) -> Run:
    return enqueue_run(
        session,
        run_type="scoring",
        limit=limit,
        status=status,
        source=source,
        classification_key=classification_key,
        prompt_key=prompt_key,
        force=force,
        callback_url=callback_url,
    )


def enqueue_classification_run(
    session,
    *,
    limit: int,
    source: str | None = None,
    classification_key: str | None = None,
    prompt_key: str | None = None,
    force: bool = False,
    callback_url: str | None = None,
) -> Run:
    return enqueue_run(
        session,
        run_type="classification",
        limit=limit,
        source=source,
        classification_key=classification_key,
        prompt_key=prompt_key,
        force=force,
        callback_url=callback_url,
    )


def get_run_counts(session, run_id: int) -> ScoreRunCounts:
    rows = session.execute(
        select(RunItem.status, func.count())
        .where(RunItem.score_run_id == run_id)
        .group_by(RunItem.status)
    ).all()
    counts = {status: count for status, count in rows}
    job_ids = list(
        session.scalars(
            select(RunItem.job_posting_id)
            .where(RunItem.score_run_id == run_id)
            .where(RunItem.job_posting_id.is_not(None))
            .order_by(RunItem.id.asc())
        ).all()
    )
    application_ids = list(
        session.scalars(
            select(RunItem.job_application_id)
            .where(RunItem.score_run_id == run_id)
            .where(RunItem.job_application_id.is_not(None))
            .order_by(RunItem.id.asc())
        ).all()
    )
    return ScoreRunCounts(
        processed=sum(counts.get(key, 0) for key in (*SUCCESS_STATUSES, "error", "skipped")),
        succeeded=sum(counts.get(key, 0) for key in SUCCESS_STATUSES),
        errored=counts.get("error", 0),
        skipped=counts.get("skipped", 0),
        jobs=job_ids,
        applications=application_ids,
    )


def serialize_run(session, run: Run) -> dict:
    counts = get_run_counts(session, run.id)
    return {
        "run_id": run.id,
        "type": run.type,
        "status": run.status,
        "selected": run.selected_count,
        "processed": counts.processed,
        "succeeded": counts.succeeded,
        "errored": counts.errored,
        "skipped": counts.skipped,
        "jobs": counts.jobs,
        "applications": counts.applications,
        "callback_url": run.callback_url,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "last_error": run.last_error,
        "requested_status": run.requested_status,
        "requested_source": run.requested_source,
        "classification_key": run.classification_key,
        "prompt_key": run.prompt_key,
        "force": run.force,
        "callback_status": run.callback_status,
        "callback_error": run.callback_error,
    }


def serialize_score_run(session, run: Run) -> dict:
    payload = serialize_run(session, run)
    payload["scored"] = payload.pop("succeeded")
    return payload


def serialize_classification_run(session, run: Run) -> dict:
    payload = serialize_run(session, run)
    payload["classified"] = payload.pop("succeeded")
    return payload


def serialize_application_score_run(session, run: Run) -> dict:
    payload = serialize_run(session, run)
    payload["scored"] = payload.pop("succeeded")
    return payload


def _mark_run_failed(session, run: Run, message: str) -> None:
    pending_items = session.scalars(
        select(RunItem).where(
            RunItem.score_run_id == run.id,
            RunItem.status.in_(("queued", "running")),
        )
    ).all()
    for item in pending_items:
        item.status = "error"
        item.error_message = message
        item.finished_at = utcnow()
    run.status = "failed"
    run.last_error = message
    run.finished_at = utcnow()
    _commit_scoring_progress(session)


def _post_callback(callback_url: str, payload: dict) -> None:
    req = request.Request(
        url=callback_url,
        data=json.dumps(payload, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=15) as response:
        response.read()


def _deliver_callback(run_id: int) -> None:
    with SessionLocal() as session:
        run = session.get(Run, run_id)
        if run is None or not run.callback_url:
            return

        payload = serialize_run(session, run)
        try:
            _post_callback(run.callback_url, payload)
            run.callback_status = "delivered"
            run.callback_error = None
        except (error.HTTPError, error.URLError, TimeoutError, ValueError) as exc:
            run.callback_status = "failed"
            run.callback_error = str(exc)

        _commit_scoring_progress(session)


def process_next_run() -> bool:
    with SessionLocal() as session:
        run = session.scalar(
            select(Run)
            .where(Run.status == "queued")
            .order_by(Run.created_at.asc())
            .limit(1)
        )
        if run is None:
            return False

        run.status = "running"
        run.started_at = utcnow()
        run.last_error = None
        _commit_scoring_progress(session)
        run_id = run.id

    with SessionLocal() as session:
        run = session.get(Run, run_id)
        if run is None:
            return True

        try:
            prompt: PromptLibrary = resolve_active_prompt(
                session,
                run.prompt_key,
                prompt_type="classification" if run.type == "classification" else "scoring",
            )
            client = build_llm_client()
        except Exception as exc:
            _mark_run_failed(session, run, str(exc))
            if run.callback_url:
                _deliver_callback(run.id)
            return True

        items = list(
            session.scalars(
                select(RunItem)
                .where(RunItem.score_run_id == run.id)
                .order_by(RunItem.id.asc())
            ).all()
        )

        for item in items:
            if item.status not in {"queued", "running"}:
                continue

            item.status = "running"
            item.started_at = utcnow()
            item.error_message = None
            _commit_scoring_progress(session)

            try:
                if item.type == "application_scoring":
                    application = session.get(JobApplication, item.job_application_id)
                    if application is None:
                        item.status = "error"
                        item.error_message = f"Application '{item.job_application_id}' was not found"
                    else:
                        result = score_application(
                            session,
                            application,
                            classification_key=run.classification_key or application.job_posting.classification_key,
                            prompt_key=run.prompt_key,
                            force=run.force,
                            client=client,
                            prompt=prompt,
                        )
                        item.status = result.outcome
                        item.error_message = result.error_message
                else:
                    job = session.get(JobPosting, item.job_posting_id)
                    if job is None:
                        item.status = "error"
                        item.error_message = f"Job '{item.job_posting_id}' was not found"
                        item.finished_at = utcnow()
                        _commit_scoring_progress(session)
                        continue

                if item.type == "classification":
                    result = classify_job(
                        session,
                        job,
                        classification_key=run.classification_key or job.classification_key,
                        prompt_key=run.prompt_key,
                        force=run.force,
                        client=client,
                        prompt=prompt,
                    )
                    item.status = result.outcome
                    item.error_message = result.error_message
                elif item.type == "scoring":
                    result = score_job(
                        session,
                        job,
                        classification_key=run.classification_key or job.classification_key,
                        prompt_key=run.prompt_key,
                        force=run.force,
                        client=client,
                        prompt=prompt,
                    )
                    item.status = result.outcome
                    item.error_message = result.error_message
            except JobScoringSkipped as exc:
                session.rollback()
                item = session.get(RunItem, item.id)
                if item is None:
                    continue
                item.status = "skipped"
                item.error_message = str(exc)
            except Exception as exc:
                session.rollback()
                item = session.get(RunItem, item.id)
                if item is None:
                    continue
                item.status = "error"
                item.error_message = str(exc)

            item.finished_at = utcnow()
            _commit_scoring_progress(session)

        run = session.get(Run, run.id)
        if run is not None:
            run.status = "completed"
            run.finished_at = utcnow()
            _commit_scoring_progress(session)
            if run.callback_url:
                _deliver_callback(run.id)

    return True


def process_next_score_run() -> bool:
    return process_next_run()


class ScoreRunWorker:
    def __init__(self, poll_interval_seconds: float = 1.0) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="score-run-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                processed = process_next_run()
            except Exception:
                time.sleep(self.poll_interval_seconds)
                continue

            if not processed:
                time.sleep(self.poll_interval_seconds)
