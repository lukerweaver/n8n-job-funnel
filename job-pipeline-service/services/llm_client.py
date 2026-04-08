import json
from dataclasses import dataclass
from urllib import error, request

from config import settings


class LlmRequestError(Exception):
    pass


@dataclass
class LlmClient:
    provider: str
    model: str

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


class OllamaClient(LlmClient):
    def __init__(self) -> None:
        model = settings.resolve_model_for_provider("ollama")
        if settings.ollama_base_url is None:
            raise LlmRequestError("Ollama provider requires OLLAMA_BASE_URL to be set")
        if model is None:
            raise LlmRequestError("Ollama provider requires OLLAMA_MODEL or SCORING_MODEL to be set")

        super().__init__(provider="ollama", model=model)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"num_ctx": settings.ollama_num_ctx},
        }

        req = request.Request(
            url=f"{settings.ollama_base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=settings.llm_timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LlmRequestError(f"Ollama request failed with status {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise LlmRequestError(f"Ollama request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LlmRequestError("Ollama returned invalid JSON") from exc

        message = parsed.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LlmRequestError("Ollama returned an empty response")

        return content


class OpenAICompatibleClient(LlmClient):
    def __init__(self, provider_name: str = "openai_compatible") -> None:
        model = settings.resolve_model_for_provider(provider_name)
        if settings.llm_base_url is None:
            raise LlmRequestError(
                f"{provider_name} provider requires LLM_BASE_URL to be set"
            )
        if settings.llm_api_key is None:
            raise LlmRequestError(
                f"{provider_name} provider requires LLM_API_KEY to be set"
            )
        if model is None:
            raise LlmRequestError(
                f"{provider_name} provider requires SCORING_MODEL to be set"
            )

        super().__init__(provider=provider_name, model=model)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        req = request.Request(
            url=f"{settings.llm_base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.llm_api_key}",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=settings.llm_timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LlmRequestError(f"{self.provider} request failed with status {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise LlmRequestError(f"{self.provider} request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LlmRequestError(f"{self.provider} returned invalid JSON") from exc

        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LlmRequestError(f"{self.provider} returned an empty response")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LlmRequestError(f"{self.provider} returned an empty response")

        return content


def build_llm_client() -> LlmClient:
    provider = settings.resolve_llm_provider()

    if provider == "ollama":
        return OllamaClient()
    if provider in {"openai_compatible", "openai", "groq"}:
        return OpenAICompatibleClient(provider_name=provider)
    if provider == "unconfigured":
        raise LlmRequestError(
            "No LLM provider configured. Set SCORING_PROVIDER or configure OLLAMA_BASE_URL, "
            "or configure LLM_BASE_URL, LLM_API_KEY, and SCORING_MODEL."
        )

    raise LlmRequestError(f"Unsupported scoring provider '{provider}'")
