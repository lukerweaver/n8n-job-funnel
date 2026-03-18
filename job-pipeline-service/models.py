from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(100), default="unknown", index=True)
    status: Mapped[str] = mapped_column(String(50), default="new", index=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    yearly_min_compensation: Mapped[float | None] = mapped_column(Float, nullable=True)
    yearly_max_compensation: Mapped[float | None] = mapped_column(Float, nullable=True)
    apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    gaps: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    missing_from_jd: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    prompt_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    score_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    score_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PromptLibrary(Base):
    __tablename__ = "prompt_library"
    __table_args__ = (UniqueConstraint("prompt_key", "prompt_version", name="uq_prompt_library_key_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prompt_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    base_resume_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
