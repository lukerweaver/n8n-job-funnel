import os


class Settings:
    def __init__(self) -> None:
        self.scoring_provider = os.getenv("SCORING_PROVIDER", "ollama").strip().lower()
        self.scoring_model = os.getenv("SCORING_MODEL", "qwen2.5:14b-instruct").strip()
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "50000"))
        self.llm_timeout_seconds = int(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
        self.default_prompt_key = os.getenv("DEFAULT_PROMPT_KEY")


settings = Settings()
