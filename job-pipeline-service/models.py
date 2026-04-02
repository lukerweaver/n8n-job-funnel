from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    resumes: Mapped[list["Resume"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    applications: Mapped[list["JobApplication"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(100), default="unknown", index=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    yearly_min_compensation: Mapped[float | None] = mapped_column(Float, nullable=True)
    yearly_max_compensation: Mapped[float | None] = mapped_column(Float, nullable=True)
    apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)

    classification_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    classification_prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    classification_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    classification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Legacy workflow/scoring fields retained temporarily until the service
    # cutover moves scoring and application lifecycle onto JobApplication.
    status: Mapped[str] = mapped_column(String(50), default="new", index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    screening_likelihood: Mapped[float | None] = mapped_column(Float, nullable=True)
    dimension_scores: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    gating_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
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

    applications: Mapped[list["JobApplication"]] = relationship(
        back_populates="job_posting", cascade="all, delete-orphan"
    )


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    classification_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="resumes")
    applications: Mapped[list["JobApplication"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class PromptLibrary(Base):
    __tablename__ = "prompt_library"
    __table_args__ = (
        UniqueConstraint("prompt_key", "prompt_version", "prompt_type", name="uq_prompt_library_key_version_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prompt_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    prompt_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False, default="scoring")
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class JobApplication(Base):
    __tablename__ = "job_applications"
    __table_args__ = (
        UniqueConstraint("job_posting_id", "resume_id", name="uq_job_applications_posting_resume"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False, index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="new", nullable=False, index=True)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    screening_likelihood: Mapped[float | None] = mapped_column(Float, nullable=True)
    dimension_scores: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    gating_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    strengths: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    gaps: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    missing_from_jd: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)

    scoring_prompt_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scoring_prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    score_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    score_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tailored_resume_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tailoring_prompt_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tailoring_prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tailoring_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tailoring_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tailoring_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    tailoring_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tailored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="applications")
    job_posting: Mapped["JobPosting"] = relationship(back_populates="applications")
    resume: Mapped["Resume"] = relationship(back_populates="applications")
    interview_rounds: Mapped[list["InterviewRound"]] = relationship(
        back_populates="job_application", cascade="all, delete-orphan"
    )


class InterviewRound(Base):
    __tablename__ = "interview_rounds"
    __table_args__ = (
        UniqueConstraint("job_application_id", "round_number", name="uq_interview_rounds_application_round"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_application_id: Mapped[int] = mapped_column(ForeignKey("job_applications.id"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="scheduled", nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    job_application: Mapped["JobApplication"] = relationship(back_populates="interview_rounds")


class Run(Base):
    __tablename__ = "score_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    type: Mapped[str] = mapped_column(String(50), default="scoring", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="queued", nullable=False, index=True)
    requested_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    requested_source: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    classification_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    force: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    callback_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    callback_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class RunItem(Base):
    __tablename__ = "score_run_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    score_run_id: Mapped[int] = mapped_column(ForeignKey("score_runs.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), default="scoring", nullable=False, index=True)
    job_posting_id: Mapped[int | None] = mapped_column(ForeignKey("job_postings.id"), nullable=True, index=True)
    job_application_id: Mapped[int | None] = mapped_column(ForeignKey("job_applications.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="queued", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


ScoreRun = Run
ScoreRunItem = RunItem
