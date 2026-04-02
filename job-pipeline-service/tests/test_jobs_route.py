from datetime import datetime, timedelta, timezone

from app import list_jobs
from models import JobPosting


def test_get_jobs_returns_classification_metadata_and_supports_optional_filters(db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            JobPosting(
                job_id="job-1",
                source="linkedin",
                company_name="Acme",
                title="PM",
                classification_key="Product Manager",
                classified_at=now,
            ),
            JobPosting(
                job_id="job-2",
                source="linkedin",
                company_name="Beta",
                title="Platform PM",
                classification_key="Product Manager",
                classified_at=now - timedelta(days=2),
            ),
            JobPosting(
                job_id="job-3",
                source="linkedin",
                company_name="Gamma",
                title="Designer",
                classification_key="Designer",
                classified_at=now,
            ),
        ]
    )
    db_session.commit()

    response = list_jobs(
        db_session,
        source=None,
        classification_key="Product Manager",
        classified_since=now - timedelta(days=1),
        limit=100,
        offset=0,
    )

    assert response.total == 1
    assert len(response.items) == 1
    assert response.items[0].job_id == "job-1"
    assert response.items[0].classification_key == "Product Manager"
