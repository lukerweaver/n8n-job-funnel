from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class JobIngestItem(BaseModel):
    job_id: str
    company_name: str | None = None
    title: str | None = None
    yearly_min_compensation: float | None = None
    yearly_max_compensation: float | None = None
    apply_url: str | None = None
    description: str | None = None
    source: str = "job-scraper-chrome"
    raw_payload: dict[str, Any] | list[Any] | None = None


class JobIngestResponse(BaseModel):
    received: int
    created: int
    updated: int
    skipped: int
    jobs: list[str]


class JobScoreWrite(BaseModel):
    score: float | None = None
    recommendation: str | None = None
    justification: str | None = None
    strengths: list[Any] | dict[str, Any] | None = None
    gaps: list[Any] | dict[str, Any] | None = None
    missing_from_jd: list[Any] | dict[str, Any] | None = None
    role_type: str | None = None
    screening_likelihood: float | None = None
    dimension_scores: dict[str, float] | None = None
    gating_flags: list[str] | None = None
    prompt_key: str | None = None
    prompt_version: int | None = None
    scored_at: datetime | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    status: str = "scored"


class JobScoreBatchItem(JobScoreWrite):
    id: int


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    source: str
    status: str
    company_name: str | None
    title: str | None
    yearly_min_compensation: float | None
    yearly_max_compensation: float | None
    apply_url: str | None
    description: str | None
    score: float | None
    recommendation: str | None
    justification: str | None
    strengths: list[Any] | dict[str, Any] | None
    gaps: list[Any] | dict[str, Any] | None
    missing_from_jd: list[Any] | dict[str, Any] | None
    role_type: str | None = None
    screening_likelihood: float | None = None
    dimension_scores: dict[str, float] | None = None
    gating_flags: list[str] | None = None
    prompt_key: str | None
    prompt_version: int | None
    scored_at: datetime | None
    notified_at: datetime | None
    error_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    total: int
    items: list[JobRead]


class JobScoreResponse(BaseModel):
    id: int
    job_id: str
    status: str
    score: float | None = None
    recommendation: str | None = None
    role_type: str | None = None
    screening_likelihood: float | None = None
    dimension_scores: dict[str, float] | None = None
    gating_flags: list[str] | None = None
    scored_at: datetime | None = None
    notified_at: datetime | None = None
    error_at: datetime | None = None
    score_error: str | None = None


class JobsBatchScoreResponse(BaseModel):
    updated: int
    jobs: list[int]


class JobNotifyWrite(BaseModel):
    notified_at: datetime | None = None
    status: str = "notified"


class JobNotifyBatchItem(JobNotifyWrite):
    id: int


class JobNotifyResponse(BaseModel):
    id: int
    job_id: str
    status: str
    notified_at: datetime | None = None


class JobErrorWrite(BaseModel):
    error_at: datetime | None = None
    status: str = "error"


class JobErrorResponse(BaseModel):
    id: int
    job_id: str
    status: str
    error_at: datetime | None = None
    score_error: str | None = None


class JobScoreRunRequest(BaseModel):
    prompt_key: str | None = None
    force: bool = False


class JobsScoreRunRequest(BaseModel):
    limit: int = 25
    status: str = "new"
    source: str | None = None
    prompt_key: str | None = None
    dry_run: bool = False
    force: bool = False


class JobsScoreRunResponse(BaseModel):
    selected: int
    scored: int
    errored: int
    skipped: int
    jobs: list[int]


class JobsBatchNotifyResponse(BaseModel):
    updated: int
    jobs: list[int]


class PromptLibraryBase(BaseModel):
    prompt_key: str
    prompt_version: int
    system_prompt: str
    user_prompt_template: str
    base_resume_template: str
    is_active: bool = True


class PromptLibraryCreate(PromptLibraryBase):
    pass


class PromptLibraryUpdate(BaseModel):
    prompt_key: str | None = None
    prompt_version: int | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    base_resume_template: str | None = None
    is_active: bool | None = None


class PromptLibraryRead(PromptLibraryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class PromptLibraryListResponse(BaseModel):
    total: int
    items: list[PromptLibraryRead]
