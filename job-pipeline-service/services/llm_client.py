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
        super().__init__(provider="ollama", model=settings.scoring_model)

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


def build_llm_client() -> LlmClient:
    if settings.scoring_provider == "ollama":
        return OllamaClient()

    raise LlmRequestError(f"Unsupported scoring provider '{settings.scoring_provider}'")
