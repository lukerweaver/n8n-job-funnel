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
