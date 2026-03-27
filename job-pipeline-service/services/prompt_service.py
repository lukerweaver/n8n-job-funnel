from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models import PromptLibrary


class PromptResolutionError(Exception):
    pass


def resolve_active_prompt(
    session: Session,
    prompt_key: str | None = None,
    *,
    prompt_type: str = "scoring",
) -> PromptLibrary:
    effective_prompt_key = prompt_key or settings.default_prompt_key

    query = select(PromptLibrary).where(
        PromptLibrary.is_active.is_(True),
        PromptLibrary.prompt_type == prompt_type,
    )
    if effective_prompt_key:
        query = query.where(PromptLibrary.prompt_key == effective_prompt_key)

    prompt = session.scalars(query.order_by(PromptLibrary.prompt_version.desc(), PromptLibrary.id.desc())).first()
    if prompt is None:
        if effective_prompt_key:
            raise PromptResolutionError(
                f"No active {prompt_type} prompt was found for prompt_key='{effective_prompt_key}'"
            )
        raise PromptResolutionError(f"No active {prompt_type} prompt was found")

    return prompt
