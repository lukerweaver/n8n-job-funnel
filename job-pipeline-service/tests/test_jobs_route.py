from app import list_jobs
from models import JobPosting


def test_get_jobs_returns_role_type_and_supports_optional_filters(db_session):
    db_session.add_all(
        [
            JobPosting(
                job_id="job-1",
                source="linkedin",
                status="scored",
                company_name="Acme",
                title="PM",
                role_type="Product Manager",
                screening_likelihood=30,
                score=20,
            ),
            JobPosting(
                job_id="job-2",
                source="linkedin",
                status="scored",
                company_name="Beta",
                title="Platform PM",
                role_type="Product Manager",
                screening_likelihood=15,
                score=18,
            ),
            JobPosting(
                job_id="job-3",
                source="linkedin",
                status="scored",
                company_name="Gamma",
                title="Designer",
                role_type="Designer",
                screening_likelihood=40,
                score=25,
            ),
        ]
    )
    db_session.commit()

    response = list_jobs(
        db_session,
        status=None,
        source=None,
        score=None,
        role_type="Product Manager",
        screening_likelihood=20,
        scored_since=None,
        limit=100,
        offset=0,
    )

    assert response.total == 1
    assert len(response.items) == 1
    assert response.items[0].job_id == "job-1"
    assert response.items[0].role_type == "Product Manager"
    assert response.items[0].screening_likelihood == 30
