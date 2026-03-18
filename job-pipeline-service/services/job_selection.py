from sqlalchemy import select
from sqlalchemy.orm import Session

from models import JobPosting


def select_jobs_for_scoring(
    session: Session,
    *,
    status: str,
    source: str | None,
    limit: int,
) -> list[JobPosting]:
    query = select(JobPosting).order_by(JobPosting.created_at.asc())

    if status:
        query = query.where(JobPosting.status == status)

    if source:
        query = query.where(JobPosting.source == source)

    return list(session.scalars(query.limit(limit)).all())
