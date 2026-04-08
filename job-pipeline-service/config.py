import os


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


class Settings:
    def __init__(self) -> None:
        self.scoring_provider = _optional_env("SCORING_PROVIDER")
        if self.scoring_provider is not None:
            self.scoring_provider = self.scoring_provider.lower()

        self.scoring_model = _optional_env("SCORING_MODEL")
        self.ollama_model = _optional_env("OLLAMA_MODEL")
        self.ollama_base_url = _optional_env("OLLAMA_BASE_URL")
        if self.ollama_base_url is not None:
            self.ollama_base_url = self.ollama_base_url.rstrip("/")

        self.llm_base_url = _optional_env("LLM_BASE_URL")
        if self.llm_base_url is not None:
            self.llm_base_url = self.llm_base_url.rstrip("/")
        self.llm_api_key = _optional_env("LLM_API_KEY")
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "50000"))
        self.llm_timeout_seconds = int(os.getenv("LLM_TIMEOUT_SECONDS", "180"))

    def resolve_llm_provider(self) -> str:
        if self.scoring_provider is not None:
            return self.scoring_provider

        if self.ollama_base_url:
            return "ollama"

        if self.llm_base_url and self.llm_api_key:
            return "openai_compatible"

        return "unconfigured"

    def resolve_model_for_provider(self, provider: str) -> str | None:
        if provider == "ollama":
            return self.ollama_model or self.scoring_model or "qwen2.5:14b-instruct"

        return self.scoring_model


settings = Settings()
