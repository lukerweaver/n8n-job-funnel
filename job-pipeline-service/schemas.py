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
    force: bool = False
    callback_url: str | None = None


class RunItemRead(BaseModel):
    id: int
    type: str
    job_posting_id: int | None = None
    job_application_id: int | None = None
    status: str
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunRead(BaseModel):
    run_id: int
    type: str
    status: str
    selected: int
    processed: int
    succeeded: int
    errored: int
    skipped: int
    jobs: list[int]
    applications: list[int]
    callback_url: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    requested_status: str
    requested_source: str | None = None
    prompt_key: str | None = None
    force: bool = False
    callback_status: str | None = None
    callback_error: str | None = None


class RunItemsResponse(BaseModel):
    total: int
    items: list[RunItemRead]


class JobsScoreRunResponse(BaseModel):
    run_id: int
    type: str
    status: str
    selected: int
    processed: int
    scored: int
    errored: int
    skipped: int
    jobs: list[int]
    applications: list[int]
    callback_url: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None


class ScoreRunRead(JobsScoreRunResponse):
    requested_status: str
    requested_source: str | None = None
    prompt_key: str | None = None
    force: bool = False
    callback_status: str | None = None
    callback_error: str | None = None


class ScoreRunItemsResponse(BaseModel):
    total: int
    items: list[RunItemRead]


class JobsBatchNotifyResponse(BaseModel):
    updated: int
    jobs: list[int]


class PromptLibraryBase(BaseModel):
    prompt_key: str
    prompt_type: str = "scoring"
    prompt_version: int
    system_prompt: str
    user_prompt_template: str
    context: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    is_active: bool = True


class PromptLibraryCreate(PromptLibraryBase):
    pass


class PromptLibraryUpdate(BaseModel):
    prompt_key: str | None = None
    prompt_type: str | None = None
    prompt_version: int | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    context: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    is_active: bool | None = None


class PromptLibraryRead(PromptLibraryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class PromptLibraryListResponse(BaseModel):
    total: int
    items: list[PromptLibraryRead]


class UserCreate(BaseModel):
    name: str
    email: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    total: int
    items: list[UserRead]


class ResumeCreate(BaseModel):
    user_id: int
    name: str
    classification_key: str
    content: str
    is_active: bool = True


class ResumeUpdate(BaseModel):
    name: str | None = None
    classification_key: str | None = None
    content: str | None = None
    is_active: bool | None = None


class ResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    classification_key: str | None = None
    content: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ResumeListResponse(BaseModel):
    total: int
    items: list[ResumeRead]


class ApplicationCreate(BaseModel):
    user_id: int
    job_posting_id: int
    resume_id: int
    status: str = "new"


class ApplicationGenerateRequest(BaseModel):
    job_posting_id: int
    user_id: int | None = None


class ApplicationGenerateResponse(BaseModel):
    created: int
    skipped: int
    applications: list[int]


class ApplicationsGenerateRunRequest(BaseModel):
    user_id: int
    limit: int = 100


class ApplicationsGenerateRunResponse(BaseModel):
    selected: int
    processed: int
    created: int
    skipped: int
    jobs: list[int]
    applications: list[int]


class ApplicationStatusWrite(BaseModel):
    status: str
    applied_at: datetime | None = None
    offer_at: datetime | None = None
    rejected_at: datetime | None = None
    withdrawn_at: datetime | None = None


class JobApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    job_posting_id: int
    resume_id: int
    job_id: str | None = None
    source: str | None = None
    company_name: str | None = None
    title: str | None = None
    yearly_min_compensation: float | None = None
    yearly_max_compensation: float | None = None
    apply_url: str | None = None
    role_type: str | None = None
    resume_name: str | None = None
    status: str
    score: float | None = None
    recommendation: str | None = None
    justification: str | None = None
    screening_likelihood: float | None = None
    dimension_scores: dict[str, float] | None = None
    gating_flags: list[str] | None = None
    strengths: list[Any] | dict[str, Any] | None = None
    gaps: list[Any] | dict[str, Any] | None = None
    missing_from_jd: list[Any] | dict[str, Any] | None = None
    scoring_prompt_key: str | None = None
    scoring_prompt_version: int | None = None
    score_error: str | None = None
    scored_at: datetime | None = None
    tailored_resume_content: str | None = None
    tailoring_prompt_key: str | None = None
    tailoring_prompt_version: int | None = None
    tailoring_error: str | None = None
    tailored_at: datetime | None = None
    notified_at: datetime | None = None
    applied_at: datetime | None = None
    offer_at: datetime | None = None
    rejected_at: datetime | None = None
    withdrawn_at: datetime | None = None
    last_error_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class JobApplicationListResponse(BaseModel):
    total: int
    items: list[JobApplicationRead]


class JobApplicationScoreResponse(BaseModel):
    id: int
    job_posting_id: int
    resume_id: int
    status: str
    score: float | None = None
    recommendation: str | None = None
    screening_likelihood: float | None = None
    dimension_scores: dict[str, float] | None = None
    gating_flags: list[str] | None = None
    scored_at: datetime | None = None
    notified_at: datetime | None = None
    last_error_at: datetime | None = None
    score_error: str | None = None


class JobClassificationRunRequest(BaseModel):
    prompt_key: str | None = None
    force: bool = False


class JobsClassificationRunRequest(BaseModel):
    limit: int = 25
    source: str | None = None
    prompt_key: str | None = None
    force: bool = False
    callback_url: str | None = None


class JobClassificationResponse(BaseModel):
    id: int
    job_id: str
    classification_key: str | None = None
    classification_prompt_version: int | None = None
    classified_at: datetime | None = None
    classification_error: str | None = None


class JobsClassificationRunResponse(BaseModel):
    run_id: int
    type: str
    status: str
    selected: int
    processed: int
    classified: int
    errored: int
    skipped: int
    jobs: list[int]
    applications: list[int] = []
    callback_url: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None


class ApplicationsScoreRunRequest(BaseModel):
    limit: int = 25
    status: str = "new"
    user_id: int | None = None
    resume_id: int | None = None
    job_posting_id: int | None = None
    prompt_key: str | None = None
    force: bool = False
    callback_url: str | None = None


class ApplicationsScoreRunResponse(BaseModel):
    run_id: int
    type: str
    status: str
    selected: int
    processed: int
    scored: int
    errored: int
    skipped: int
    jobs: list[int]
    applications: list[int]
    callback_url: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None


class InterviewRoundCreate(BaseModel):
    round_number: int
    stage_name: str | None = None
    status: str = "scheduled"
    notes: str | None = None
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None


class InterviewRoundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_application_id: int
    round_number: int
    stage_name: str | None = None
    status: str
    notes: str | None = None
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class InterviewRoundListResponse(BaseModel):
    total: int
    items: list[InterviewRoundRead]
