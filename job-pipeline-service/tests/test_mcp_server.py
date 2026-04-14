import asyncio

import pytest

import mcp_server


def test_compact_application_omits_full_description_by_default():
    application = {
        "id": 1,
        "company_name": "Example Co",
        "title": "Product Manager",
        "description": "x" * 600,
        "score": 22,
        "scored_at": "2026-04-14T10:00:00Z",
    }

    compacted = mcp_server.compact_application(application)

    assert compacted["id"] == 1
    assert compacted["company_name"] == "Example Co"
    assert "description" not in compacted
    assert compacted["description_preview"] == "x" * mcp_server.DESCRIPTION_PREVIEW_CHARS
    assert compacted["description_truncated"] is True


def test_compact_application_can_include_full_description():
    application = {"id": 1, "description": "Full description"}

    compacted = mcp_server.compact_application(application, include_description=True)

    assert compacted["description"] == "Full description"
    assert "description_preview" not in compacted


def test_list_applications_builds_filtered_query(monkeypatch):
    captured = {}

    async def fake_api_get(path, params=None):
        captured["path"] = path
        captured["params"] = params
        return {
            "total": 1,
            "items": [
                {
                    "id": 123,
                    "company_name": "Example Co",
                    "title": "Product Manager",
                    "description": "body",
                    "score": 24,
                }
            ],
        }

    monkeypatch.setattr(mcp_server, "api_get", fake_api_get)

    response = asyncio.run(
        mcp_server.list_applications(
            status="scored",
            score_min=20.000001,
            sort_by="score",
            sort_order="desc",
            limit=10,
        )
    )

    assert captured["path"] == "/applications"
    assert captured["params"]["status"] == "scored"
    assert captured["params"]["score_min"] == 20.000001
    assert captured["params"]["sort_by"] == "score"
    assert response["total"] == 1
    assert "description" not in response["items"][0]


def test_get_application_apply_url_returns_limited_identity(monkeypatch):
    async def fake_api_get(path, params=None):
        assert path == "/applications/31008"
        return {
            "id": 31008,
            "company_name": "JustPark",
            "title": "Technical Product Manager - Integrations",
            "status": "scored",
            "score": 23,
            "recommendation": "Strong Apply",
            "apply_url": "https://apply.workable.com/j/BC25CA8827",
            "description": "large body",
        }

    monkeypatch.setattr(mcp_server, "api_get", fake_api_get)

    response = asyncio.run(mcp_server.get_application_apply_url(31008))

    assert response == {
        "id": 31008,
        "company_name": "JustPark",
        "title": "Technical Product Manager - Integrations",
        "status": "scored",
        "score": 23,
        "recommendation": "Strong Apply",
        "apply_url": "https://apply.workable.com/j/BC25CA8827",
    }


def test_find_applications_for_email_signal_requires_human_selection_for_ambiguous_matches(monkeypatch):
    captured = {}

    async def fake_list_applications(**kwargs):
        captured.update(kwargs)
        return {
            "total": 2,
            "items": [
                {"id": 1, "company_name": "Example Co"},
                {"id": 2, "company_name": "Example Co"},
            ],
        }

    monkeypatch.setattr(mcp_server, "list_applications", fake_list_applications)

    response = asyncio.run(
        mcp_server.find_applications_for_email_signal(
            company_name="Example Co",
            title="Product Manager",
            status_group="active",
        )
    )

    assert captured["q"] == "Example Co Product Manager"
    assert captured["status_group"] == "active"
    assert captured["sort_by"] == "updated_at"
    assert response["requires_human_selection"] is True
    assert response["total"] == 2


def test_write_tools_require_confirmation():
    with pytest.raises(mcp_server.JobFunnelSafetyError, match="confirm_write=true"):
        asyncio.run(mcp_server.ingest_job(job_id="example_1"))


def test_force_tools_require_force_confirmation():
    with pytest.raises(mcp_server.JobFunnelSafetyError, match="confirm_force=true"):
        asyncio.run(
            mcp_server.queue_scoring_run(
                force=True,
                confirm_write=True,
                acknowledge_service_automation=True,
            )
        )


def test_ingest_job_posts_normalized_payload(monkeypatch):
    captured = {}

    async def fake_api_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"received": 1, "created": 1, "updated": 0, "skipped": 0, "jobs": ["agent_1"]}

    monkeypatch.setattr(mcp_server, "api_post", fake_api_post)

    response = asyncio.run(
        mcp_server.ingest_job(
            job_id="agent_1",
            company_name="Example Co",
            title="Product Manager",
            source="agent_mcp",
            confirm_write=True,
        )
    )

    assert captured["path"] == "/jobs/ingest"
    assert captured["payload"] == {
        "job_id": "agent_1",
        "company_name": "Example Co",
        "title": "Product Manager",
        "source": "agent_mcp",
    }
    assert response["created"] == 1


def test_queue_classification_run_blocks_when_service_automation_is_enabled(monkeypatch):
    async def fake_get_settings():
        return {"automation_settings": {"auto_process_jobs": True}}

    async def fail_api_post(path, payload):
        raise AssertionError("api_post should not be called when automation guard blocks")

    monkeypatch.setattr(mcp_server, "get_settings", fake_get_settings)
    monkeypatch.setattr(mcp_server, "api_post", fail_api_post)

    response = asyncio.run(mcp_server.queue_classification_run(confirm_write=True))

    assert response["blocked"] is True
    assert "auto_process_jobs" in response["reason"]


def test_queue_scoring_run_posts_when_service_automation_is_acknowledged(monkeypatch):
    captured = {}

    async def fake_get_settings():
        return {"automation_settings": {"auto_process_jobs": True}}

    async def fake_api_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {
            "run_id": 55,
            "type": "application_score",
            "status": "queued",
            "selected": 2,
            "processed": 0,
            "scored": 0,
            "errored": 0,
            "skipped": 0,
            "jobs": [10, 11],
            "applications": [20, 21],
        }

    monkeypatch.setattr(mcp_server, "get_settings", fake_get_settings)
    monkeypatch.setattr(mcp_server, "api_post", fake_api_post)

    response = asyncio.run(
        mcp_server.queue_scoring_run(
            status="new",
            limit=2,
            confirm_write=True,
            acknowledge_service_automation=True,
        )
    )

    assert captured["path"] == "/applications/score/run"
    assert captured["payload"]["status"] == "new"
    assert captured["payload"]["limit"] == 2
    assert response["run_id"] == 55
    assert response["applications"] == [20, 21]


def test_mark_application_status_posts_notes_and_tracks_previous_status(monkeypatch):
    calls = []

    async def fake_api_get(path, params=None):
        calls.append(("get", path, params))
        return {
            "id": 123,
            "status": "scored",
            "company_name": "Example Co",
            "title": "Product Manager",
        }

    async def fake_api_post(path, payload):
        calls.append(("post", path, payload))
        return {
            "id": 123,
            "status": "applied",
            "applied_at": "2026-04-14T12:00:00Z",
            "applied_notes": "Applied manually.",
        }

    monkeypatch.setattr(mcp_server, "api_get", fake_api_get)
    monkeypatch.setattr(mcp_server, "api_post", fake_api_post)

    response = asyncio.run(
        mcp_server.mark_application_status(
            application_id=123,
            status="applied",
            notes="Applied manually.",
            effective_at="2026-04-14T12:00:00Z",
            confirm_write=True,
        )
    )

    assert calls[0] == ("get", "/applications/123", None)
    assert calls[1] == (
        "post",
        "/applications/123/status",
        {
            "status": "applied",
            "applied_notes": "Applied manually.",
            "applied_at": "2026-04-14T12:00:00Z",
        },
    )
    assert response["previous_status"] == "scored"
    assert response["application"]["status"] == "applied"


def test_mark_application_rejected_from_email_posts_evidence_note(monkeypatch):
    captured = {}

    async def fake_mark_application_status(**kwargs):
        captured.update(kwargs)
        return {"application": {"id": kwargs["application_id"], "status": "rejected"}}

    monkeypatch.setattr(mcp_server, "mark_application_status", fake_mark_application_status)

    response = asyncio.run(
        mcp_server.mark_application_rejected_from_email(
            application_id=123,
            email_from="recruiting@example.com",
            email_subject="Application update",
            email_received_at="2026-04-14T12:00:00Z",
            notes="No further action.",
            confirm_write=True,
        )
    )

    assert captured["application_id"] == 123
    assert captured["status"] == "rejected"
    assert captured["effective_at"] == "2026-04-14T12:00:00Z"
    assert captured["confirm_write"] is True
    assert "recruiting@example.com" in captured["notes"]
    assert "Application update" in captured["notes"]
    assert response["application"]["status"] == "rejected"
