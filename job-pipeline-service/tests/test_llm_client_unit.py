import io
import json
from urllib import error

import pytest

from services.llm_client import (
    LlmRequestError,
    OllamaClient,
    OpenAICompatibleClient,
    build_llm_client,
)


class FakeResponse:
    def __init__(self, payload: str):
        self.payload = payload

    def read(self):
        return self.payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _reset_settings(monkeypatch):
    monkeypatch.setattr("services.llm_client.settings.scoring_provider", None)
    monkeypatch.setattr("services.llm_client.settings.scoring_model", None)
    monkeypatch.setattr("services.llm_client.settings.ollama_model", None)
    monkeypatch.setattr("services.llm_client.settings.ollama_base_url", None)
    monkeypatch.setattr("services.llm_client.settings.llm_base_url", None)
    monkeypatch.setattr("services.llm_client.settings.llm_api_key", None)


def test_ollama_client_success(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.ollama_base_url", "http://ollama.local")
    monkeypatch.setattr("services.llm_client.settings.ollama_model", "qwen-local")
    monkeypatch.setattr(
        "services.llm_client.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse('{"message": {"content": "ok"}}'),
    )
    client = OllamaClient()
    assert client.generate("system", "user") == "ok"


def test_ollama_client_http_error(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.ollama_base_url", "http://ollama.local")
    monkeypatch.setattr("services.llm_client.settings.ollama_model", "qwen-local")
    fp = io.BytesIO(b"failure")

    def _raise_http(*_args, **_kwargs):
        raise error.HTTPError("http://x", 500, "boom", {}, fp)

    monkeypatch.setattr("services.llm_client.request.urlopen", _raise_http)
    with pytest.raises(LlmRequestError, match="status 500"):
        OllamaClient().generate("system", "user")


def test_ollama_client_invalid_json(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.ollama_base_url", "http://ollama.local")
    monkeypatch.setattr("services.llm_client.settings.ollama_model", "qwen-local")
    monkeypatch.setattr("services.llm_client.request.urlopen", lambda *_args, **_kwargs: FakeResponse("not-json"))
    with pytest.raises(LlmRequestError, match="invalid JSON"):
        OllamaClient().generate("system", "user")


def test_openai_compatible_client_success(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.llm_base_url", "https://provider.example/v1")
    monkeypatch.setattr("services.llm_client.settings.llm_api_key", "secret")
    monkeypatch.setattr("services.llm_client.settings.scoring_model", "gpt-like-model")
    captured = {}

    def _fake_urlopen(req, *_args, **_kwargs):
        captured["url"] = req.full_url
        captured["authorization"] = req.headers.get("Authorization")
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse('{"choices": [{"message": {"content": "hosted-ok"}}]}')

    monkeypatch.setattr("services.llm_client.request.urlopen", _fake_urlopen)
    client = OpenAICompatibleClient()

    assert client.generate("system prompt", "user prompt") == "hosted-ok"
    assert captured["url"] == "https://provider.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret"
    assert captured["payload"]["model"] == "gpt-like-model"
    assert captured["payload"]["messages"][0]["role"] == "system"


def test_openai_compatible_client_url_error(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.llm_base_url", "https://provider.example/v1")
    monkeypatch.setattr("services.llm_client.settings.llm_api_key", "secret")
    monkeypatch.setattr("services.llm_client.settings.scoring_model", "gpt-like-model")

    def _raise_url(*_args, **_kwargs):
        raise error.URLError("timeout")

    monkeypatch.setattr("services.llm_client.request.urlopen", _raise_url)
    with pytest.raises(LlmRequestError, match="timeout"):
        OpenAICompatibleClient().generate("system", "user")


def test_openai_compatible_client_requires_model(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.llm_base_url", "https://provider.example/v1")
    monkeypatch.setattr("services.llm_client.settings.llm_api_key", "secret")

    with pytest.raises(LlmRequestError, match="requires SCORING_MODEL"):
        OpenAICompatibleClient()


def test_build_llm_client_uses_ollama_auto_detection(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.ollama_base_url", "http://ollama.local")

    client = build_llm_client()

    assert isinstance(client, OllamaClient)


def test_build_llm_client_uses_openai_compatible_auto_detection(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.llm_base_url", "https://provider.example/v1")
    monkeypatch.setattr("services.llm_client.settings.llm_api_key", "secret")
    monkeypatch.setattr("services.llm_client.settings.scoring_model", "gpt-like-model")

    client = build_llm_client()

    assert isinstance(client, OpenAICompatibleClient)
    assert client.provider == "openai_compatible"


def test_build_llm_client_supports_provider_aliases(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.scoring_provider", "groq")
    monkeypatch.setattr("services.llm_client.settings.llm_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr("services.llm_client.settings.llm_api_key", "secret")
    monkeypatch.setattr("services.llm_client.settings.scoring_model", "llama-3.3-70b-versatile")

    client = build_llm_client()

    assert isinstance(client, OpenAICompatibleClient)
    assert client.provider == "groq"


def test_build_llm_client_rejects_unconfigured_provider(monkeypatch):
    _reset_settings(monkeypatch)

    with pytest.raises(LlmRequestError, match="No LLM provider configured"):
        build_llm_client()


def test_build_llm_client_rejects_unsupported_provider(monkeypatch):
    _reset_settings(monkeypatch)
    monkeypatch.setattr("services.llm_client.settings.scoring_provider", "unsupported")
    with pytest.raises(LlmRequestError, match="Unsupported scoring provider 'unsupported'"):
        build_llm_client()
