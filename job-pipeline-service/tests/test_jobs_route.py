from fastapi.testclient import TestClient

from app import app
from database import Base, SessionLocal, engine
from models import JobPosting


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def teardown_function():
    Base.metadata.drop_all(bind=engine)


def test_get_jobs_returns_role_type_and_supports_optional_filters():
    with SessionLocal() as session:
        session.add_all(
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
        session.commit()

    client = TestClient(app)

    response = client.get("/jobs", params={"role_type": "Product Manager", "screening_likelihood": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["job_id"] == "job-1"
    assert payload["items"][0]["role_type"] == "Product Manager"
    assert payload["items"][0]["screening_likelihood"] == 30
