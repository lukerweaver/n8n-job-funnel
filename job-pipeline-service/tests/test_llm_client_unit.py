import io
from urllib import error

import pytest

from services.llm_client import LlmRequestError, OllamaClient


class FakeResponse:
    def __init__(self, payload: str):
        self.payload = payload

    def read(self):
        return self.payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_ollama_client_success(monkeypatch):
    monkeypatch.setattr(
        "services.llm_client.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse('{"message": {"content": "ok"}}'),
    )
    client = OllamaClient()
    assert client.generate("system", "user") == "ok"


def test_ollama_client_http_error(monkeypatch):
    fp = io.BytesIO(b"failure")

    def _raise_http(*_args, **_kwargs):
        raise error.HTTPError("http://x", 500, "boom", {}, fp)

    monkeypatch.setattr("services.llm_client.request.urlopen", _raise_http)
    with pytest.raises(LlmRequestError, match="status 500"):
        OllamaClient().generate("system", "user")


def test_ollama_client_url_error(monkeypatch):
    def _raise_url(*_args, **_kwargs):
        raise error.URLError("no route")

    monkeypatch.setattr("services.llm_client.request.urlopen", _raise_url)
    with pytest.raises(LlmRequestError, match="no route"):
        OllamaClient().generate("system", "user")


def test_ollama_client_invalid_json(monkeypatch):
    monkeypatch.setattr("services.llm_client.request.urlopen", lambda *_args, **_kwargs: FakeResponse("not-json"))
    with pytest.raises(LlmRequestError, match="invalid JSON"):
        OllamaClient().generate("system", "user")


def test_ollama_client_empty_content(monkeypatch):
    monkeypatch.setattr(
        "services.llm_client.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse('{"message": {"content": "  "}}'),
    )
    with pytest.raises(LlmRequestError, match="empty response"):
        OllamaClient().generate("system", "user")
