import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib import error, request

from sqlalchemy import func, select

from database import SessionLocal
from models import JobPosting, PromptLibrary, ScoreRun, ScoreRunItem
from services.llm_client import build_llm_client
from services.prompt_service import resolve_active_prompt
from services.scoring_service import JobScoringSkipped, _commit_scoring_progress, score_job


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScoreRunCounts:
    processed: int
    scored: int
    errored: int
    skipped: int
    jobs: list[int]


def enqueue_score_run(
    session,
    *,
    limit: int,
    status: str,
    source: str | None = None,
    prompt_key: str | None = None,
    force: bool = False,
    callback_url: str | None = None,
) -> ScoreRun:
    query = select(JobPosting).order_by(JobPosting.created_at.asc()).limit(limit)

    if status:
        query = query.where(JobPosting.status == status)

    if source:
        query = query.where(JobPosting.source == source)

    jobs = list(session.scalars(query).all())
    run = ScoreRun(
        status="queued",
        requested_status=status,
        requested_source=source,
        prompt_key=prompt_key,
        force=force,
        callback_url=callback_url,
        selected_count=len(jobs),
    )
    session.add(run)
    session.flush()

    for job in jobs:
        session.add(
            ScoreRunItem(
                score_run_id=run.id,
                job_posting_id=job.id,
                status="queued",
            )
        )

    return run


def get_score_run_counts(session, run_id: int) -> ScoreRunCounts:
    rows = session.execute(
        select(ScoreRunItem.status, func.count())
        .where(ScoreRunItem.score_run_id == run_id)
        .group_by(ScoreRunItem.status)
    ).all()
    counts = {status: count for status, count in rows}
    job_ids = list(
        session.scalars(
            select(ScoreRunItem.job_posting_id)
            .where(ScoreRunItem.score_run_id == run_id)
            .order_by(ScoreRunItem.id.asc())
        ).all()
    )
    return ScoreRunCounts(
        processed=sum(counts.get(key, 0) for key in ("scored", "error", "skipped")),
        scored=counts.get("scored", 0),
        errored=counts.get("error", 0),
        skipped=counts.get("skipped", 0),
        jobs=job_ids,
    )


def serialize_score_run(session, run: ScoreRun) -> dict:
    counts = get_score_run_counts(session, run.id)
    return {
        "run_id": run.id,
        "status": run.status,
        "selected": run.selected_count,
        "processed": counts.processed,
        "scored": counts.scored,
        "errored": counts.errored,
        "skipped": counts.skipped,
        "jobs": counts.jobs,
        "callback_url": run.callback_url,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "last_error": run.last_error,
        "requested_status": run.requested_status,
        "requested_source": run.requested_source,
        "prompt_key": run.prompt_key,
        "force": run.force,
        "callback_status": run.callback_status,
        "callback_error": run.callback_error,
    }


def _mark_run_failed(session, run: ScoreRun, message: str) -> None:
    pending_items = session.scalars(
        select(ScoreRunItem).where(
            ScoreRunItem.score_run_id == run.id,
            ScoreRunItem.status.in_(("queued", "running")),
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
        run = session.get(ScoreRun, run_id)
        if run is None or not run.callback_url:
            return

        payload = serialize_score_run(session, run)
        try:
            _post_callback(run.callback_url, payload)
            run.callback_status = "delivered"
            run.callback_error = None
        except (error.HTTPError, error.URLError, TimeoutError, ValueError) as exc:
            run.callback_status = "failed"
            run.callback_error = str(exc)

        _commit_scoring_progress(session)


def process_next_score_run() -> bool:
    with SessionLocal() as session:
        run = session.scalar(
            select(ScoreRun)
            .where(ScoreRun.status == "queued")
            .order_by(ScoreRun.created_at.asc())
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
        run = session.get(ScoreRun, run_id)
        if run is None:
            return True

        try:
            prompt: PromptLibrary = resolve_active_prompt(session, run.prompt_key)
            client = build_llm_client()
        except Exception as exc:
            _mark_run_failed(session, run, str(exc))
            if run.callback_url:
                _deliver_callback(run.id)
            return True

        items = list(
            session.scalars(
                select(ScoreRunItem)
                .where(ScoreRunItem.score_run_id == run.id)
                .order_by(ScoreRunItem.id.asc())
            ).all()
        )

        for item in items:
            if item.status not in {"queued", "running"}:
                continue

            item.status = "running"
            item.started_at = utcnow()
            item.error_message = None
            _commit_scoring_progress(session)

            job = session.get(JobPosting, item.job_posting_id)
            if job is None:
                item.status = "error"
                item.error_message = f"Job '{item.job_posting_id}' was not found"
                item.finished_at = utcnow()
                _commit_scoring_progress(session)
                continue

            try:
                result = score_job(
                    session,
                    job,
                    prompt_key=run.prompt_key,
                    force=run.force,
                    client=client,
                    prompt=prompt,
                )
                item.status = result.outcome
                item.error_message = result.error_message
            except JobScoringSkipped as exc:
                session.rollback()
                item = session.get(ScoreRunItem, item.id)
                if item is None:
                    continue
                item.status = "skipped"
                item.error_message = str(exc)
            except Exception as exc:
                session.rollback()
                item = session.get(ScoreRunItem, item.id)
                if item is None:
                    continue
                item.status = "error"
                item.error_message = str(exc)

            item.finished_at = utcnow()
            _commit_scoring_progress(session)

        run = session.get(ScoreRun, run.id)
        if run is not None:
            run.status = "completed"
            run.finished_at = utcnow()
            _commit_scoring_progress(session)
            if run.callback_url:
                _deliver_callback(run.id)

    return True


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
                processed = process_next_score_run()
            except Exception:
                time.sleep(self.poll_interval_seconds)
                continue

            if not processed:
                time.sleep(self.poll_interval_seconds)
