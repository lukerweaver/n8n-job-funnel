from sqlalchemy import select
from sqlalchemy.orm import Session

from models import AppSettings, PromptLibrary, Resume, User
from services.llm_client import LlmClientConfig


DEFAULT_PROMPT_KEY = "default"

DEFAULT_CLASSIFICATION_SYSTEM_PROMPT = """You classify job descriptions for resume matching.

Return only valid JSON with this shape:
{
  "role_type": "one of the provided classification labels",
  "classification_flags": [string],
  "classification_reason": "1 short paragraph"
}

Choose the closest category based on job responsibilities. Use "Other" only when no category is a reasonable fit."""

DEFAULT_CLASSIFICATION_USER_PROMPT = """JOB DESCRIPTION:
<<<
{{description}}
>>>

Return only the JSON object."""

DEFAULT_SCORING_SYSTEM_PROMPT = """You evaluate how well a resume fits a job description.

Return only valid JSON with this exact shape:
{
  "total_score": 0-25,
  "screening_likelihood": 0-25,
  "dimension_scores": {
    "role_fit": 0-5,
    "experience_fit": 0-5,
    "skills_fit": 0-5,
    "domain_fit": 0-5,
    "practical_fit": 0-5
  },
  "gating_flags": [string],
  "strengths": [string],
  "gaps": [string],
  "missing_from_jd": [string],
  "recommendation": "Strong Apply" | "Selective Apply" | "Stretch Apply" | "Skip",
  "justification": "1 short paragraph"
}

Use only evidence from the resume and job description. total_score must equal the sum of dimension_scores."""

DEFAULT_SCORING_USER_PROMPT = """RESUME:
<<<
{{resume}}
>>>

JOB DESCRIPTION:
<<<
{{description}}
>>>

Return only the JSON object."""

DEFAULT_SCORING_PREFERENCES = {
    "strong_apply_min_score": 20,
    "selective_apply_min_score": 15,
    "stretch_apply_min_score": 10,
}

DEFAULT_AUTOMATION_SETTINGS = {
    "auto_process_jobs": True,
    "unprocessed_jobs_threshold": 5,
    "minutes_since_last_run_threshold": 60,
    "opportunistic_trigger_enabled": True,
    "resume_strategy": "default_fallback",
}

DEFAULT_CLASSIFICATION_KEYS = [
    "Product",
    "Marketing",
    "Sales",
    "Operations",
    "Engineering",
    "Design",
    "Finance",
    "People",
]


def _clean_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _clean_string_list(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    cleaned = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    return cleaned or None


def get_or_create_app_settings(session: Session) -> AppSettings:
    settings = session.scalar(select(AppSettings).order_by(AppSettings.id.asc()).limit(1))
    if settings is not None:
        return settings

    default_user_id = session.scalar(select(User.id).order_by(User.id.asc()).limit(1))
    settings = AppSettings(
        onboarding_completed=False,
        default_user_id=default_user_id,
        provider_mode="configure_later",
        default_prompt_key=DEFAULT_PROMPT_KEY,
        scoring_preferences=DEFAULT_SCORING_PREFERENCES,
        automation_settings=DEFAULT_AUTOMATION_SETTINGS,
        automation_state={},
    )
    session.add(settings)
    session.flush()
    return settings


def seed_default_prompts(session: Session) -> None:
    existing_classification = session.scalar(
        select(PromptLibrary.id)
        .where(
            PromptLibrary.prompt_key == DEFAULT_PROMPT_KEY,
            PromptLibrary.prompt_type == "classification",
            PromptLibrary.prompt_version == 1,
        )
        .limit(1)
    )
    if existing_classification is None:
        session.add(
            PromptLibrary(
                prompt_key=DEFAULT_PROMPT_KEY,
                prompt_type="classification",
                prompt_version=1,
                system_prompt=DEFAULT_CLASSIFICATION_SYSTEM_PROMPT,
                user_prompt_template=DEFAULT_CLASSIFICATION_USER_PROMPT,
                temperature=0.0,
                is_active=True,
            )
        )

    existing_scoring = session.scalar(
        select(PromptLibrary.id)
        .where(
            PromptLibrary.prompt_key == DEFAULT_PROMPT_KEY,
            PromptLibrary.prompt_type == "scoring",
            PromptLibrary.prompt_version == 1,
        )
        .limit(1)
    )
    if existing_scoring is None:
        session.add(
            PromptLibrary(
                prompt_key=DEFAULT_PROMPT_KEY,
                prompt_type="scoring",
                prompt_version=1,
                system_prompt=DEFAULT_SCORING_SYSTEM_PROMPT,
                user_prompt_template=DEFAULT_SCORING_USER_PROMPT,
                temperature=0.1,
                is_active=True,
            )
        )


def serialize_settings(settings: AppSettings) -> dict:
    return {
        "onboarding_completed": settings.onboarding_completed,
        "default_user_id": settings.default_user_id,
        "profile_name": settings.profile_name,
        "target_roles": settings.target_roles,
        "provider": {
            "provider_mode": settings.provider_mode,
            "provider_name": settings.provider_name,
            "provider_base_url": settings.provider_base_url,
            "provider_model": settings.provider_model,
            "has_api_key": bool(settings.provider_api_key),
        },
        "default_prompt_key": settings.default_prompt_key,
        "scoring_preferences": settings.scoring_preferences,
        "automation_settings": settings.automation_settings,
        "automation_state": settings.automation_state,
        "advanced_mode_enabled": settings.advanced_mode_enabled,
    }


def apply_provider_settings(settings: AppSettings, payload) -> None:
    settings.provider_mode = payload.provider_mode
    if payload.provider_mode == "ollama":
        settings.provider_name = "ollama"
        settings.provider_base_url = _clean_string(payload.provider_base_url) or "http://localhost:11434"
        settings.provider_model = _clean_string(payload.provider_model) or "qwen2.5:14b-instruct"
        settings.provider_api_key = None
        return

    if payload.provider_mode == "hosted":
        settings.provider_name = _clean_string(payload.provider_name) or "openai_compatible"
        settings.provider_base_url = _clean_string(payload.provider_base_url)
        settings.provider_model = _clean_string(payload.provider_model)
        if payload.provider_api_key is not None:
            settings.provider_api_key = _clean_string(payload.provider_api_key)
        return

    settings.provider_name = None
    settings.provider_base_url = None
    settings.provider_model = None
    settings.provider_api_key = None


def apply_settings_update(settings: AppSettings, payload) -> None:
    if payload.profile_name is not None:
        settings.profile_name = _clean_string(payload.profile_name)
    if payload.target_roles is not None:
        settings.target_roles = _clean_string_list(payload.target_roles)
    if payload.provider is not None:
        apply_provider_settings(settings, payload.provider)
    if payload.default_prompt_key is not None:
        settings.default_prompt_key = _clean_string(payload.default_prompt_key) or DEFAULT_PROMPT_KEY
    if payload.scoring_preferences is not None:
        settings.scoring_preferences = payload.scoring_preferences
    if payload.automation_settings is not None:
        settings.automation_settings = payload.automation_settings
    if payload.advanced_mode_enabled is not None:
        settings.advanced_mode_enabled = payload.advanced_mode_enabled


def resolve_classification_keys(settings: AppSettings) -> list[str]:
    configured_roles = _clean_string_list(settings.target_roles if isinstance(settings.target_roles, list) else None)
    keys = configured_roles or DEFAULT_CLASSIFICATION_KEYS
    if not any(key.lower() == "other" for key in keys):
        keys = [*keys, "Other"]
    return keys


def build_classification_system_prompt(system_prompt: str, settings: AppSettings) -> str:
    keys = resolve_classification_keys(settings)
    key_list = " | ".join(keys)
    return (
        f"{system_prompt.strip()}\n\n"
        "Use the user's target roles as the classification labels.\n"
        f"Set role_type to exactly one of: {key_list}.\n"
        'If none fit, set role_type to "Other".\n'
        "For compatibility, classification_key is also accepted, but role_type is preferred."
    )


def build_scoring_preference_context(settings: AppSettings) -> str:
    lines: list[str] = []
    target_roles = _clean_string_list(settings.target_roles if isinstance(settings.target_roles, list) else None)
    if target_roles:
        lines.append(f"Target roles: {', '.join(target_roles)}")
    if not lines:
        return ""
    return "CANDIDATE PREFERENCES:\n" + "\n".join(f"- {line}" for line in lines)


def resolve_default_resume(session: Session, settings: AppSettings) -> Resume | None:
    if settings.default_user_id is None:
        return None
    return session.scalar(
        select(Resume)
        .where(Resume.user_id == settings.default_user_id, Resume.is_active.is_(True))
        .order_by(Resume.is_default.desc(), Resume.id.asc())
        .limit(1)
    )


def resolve_llm_config(session: Session) -> LlmClientConfig | None:
    settings = get_or_create_app_settings(session)
    if settings.provider_mode == "ollama":
        return LlmClientConfig(
            provider="ollama",
            model=settings.provider_model,
            base_url=settings.provider_base_url,
        )
    if settings.provider_mode == "hosted":
        return LlmClientConfig(
            provider=settings.provider_name or "openai_compatible",
            model=settings.provider_model,
            base_url=settings.provider_base_url,
            api_key=settings.provider_api_key,
        )
    return None


def is_provider_configured(settings: AppSettings) -> bool:
    if settings.provider_mode == "ollama":
        return bool(settings.provider_base_url and settings.provider_model)
    if settings.provider_mode == "hosted":
        return bool(settings.provider_name and settings.provider_base_url and settings.provider_model and settings.provider_api_key)
    return False
