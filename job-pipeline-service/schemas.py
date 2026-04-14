from datetime import date, datetime
from typing import Literal
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic import model_validator


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


class ProviderSettingsWrite(BaseModel):
    provider_mode: Literal["ollama", "hosted", "configure_later"] = "configure_later"
    provider_name: str | None = None
    provider_base_url: str | None = None
    provider_api_key: str | None = None
    provider_model: str | None = None


class ProviderSettingsRead(BaseModel):
    provider_mode: str
    provider_name: str | None = None
    provider_base_url: str | None = None
    provider_model: str | None = None
    has_api_key: bool = False


class AppSettingsRead(BaseModel):
    onboarding_completed: bool
    default_user_id: int | None = None
    profile_name: str | None = None
    target_roles: list[str] | None = None
    provider: ProviderSettingsRead
    default_prompt_key: str
    scoring_preferences: dict[str, Any] | None = None
    automation_settings: dict[str, Any] | None = None
    automation_state: dict[str, Any] | None = None
    advanced_mode_enabled: bool


class AppSettingsUpdate(BaseModel):
    profile_name: str | None = None
    target_roles: list[str] | None = None
    provider: ProviderSettingsWrite | None = None
    default_prompt_key: str | None = None
    scoring_preferences: dict[str, Any] | None = None
    automation_settings: dict[str, Any] | None = None
    advanced_mode_enabled: bool | None = None


class OnboardingStatusResponse(BaseModel):
    completed: bool
    settings: AppSettingsRead
    default_user: "UserRead | None" = None
    default_resume: "ResumeRead | None" = None
    missing_steps: list[str]


class OnboardingCompleteRequest(BaseModel):
    profile_name: str
    resume_name: str | None = None
    resume_content: str
    target_roles: list[str]
    provider: ProviderSettingsWrite = ProviderSettingsWrite()


class PasteJobRequest(BaseModel):
    input_type: Literal["url", "description"] = "description"
    url: str | None = None
    description: str | None = None
    title: str | None = None
    company_name: str | None = None
    user_id: int | None = None
    process_now: bool = True
    mode: Literal["async", "sync"] = "async"


class PasteJobResponse(BaseModel):
    job: "JobRead"
    application: "JobApplicationRead"
    status: str
    run_ids: list[int]
    provider_configured: bool
    message: str | None = None

class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    source: str
    company_name: str | None
    title: str | None
    yearly_min_compensation: float | None
    yearly_max_compensation: float | None
    apply_url: str | None
    description: str | None
    classification_key: str | None
    classification_prompt_version: int | None
    classification_error: str | None
    classified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    total: int
    items: list[JobRead]


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
    classification_key: str | None = None
    prompt_key: str | None = None
    force: bool = False
    callback_status: str | None = None
    callback_error: str | None = None


class RunListResponse(BaseModel):
    total: int
    items: list[RunRead]


class RunItemsResponse(BaseModel):
    total: int
    items: list[RunItemRead]


class RunApplicationRead(BaseModel):
    run_item_id: int
    run_item_status: str
    run_item_error_message: str | None = None
    job_application_id: int | None = None
    job_posting_id: int | None = None
    resume_id: int | None = None
    job_id: str | None = None
    company_name: str | None = None
    title: str | None = None
    score: float | None = None
    screening_likelihood: float | None = None
    classification_key: str | None = None
    classification_error: str | None = None
    apply_url: str | None = None
    yearly_min_compensation: float | None = None
    yearly_max_compensation: float | None = None
    recommendation: str | None = None
    resume_name: str | None = None
    classified_at: datetime | None = None
    scored_at: datetime | None = None


class RunApplicationsResponse(BaseModel):
    total: int
    items: list[RunApplicationRead]


class DailyIngestStatisticsRead(BaseModel):
    created_date: date
    ingested_job_postings: int
    rolling_7_day_avg_ingested: float
    high_job_postings: int
    rolling_7_day_avg_high: float
    percentage_high: float | None = None
    rolling_7_day_percentage: float | None = None


class IngestStatisticsResponse(BaseModel):
    total_days: int
    total_ingested_job_postings: int
    total_high_job_postings: int
    average_daily_ingested: float
    average_daily_high: float
    items: list[DailyIngestStatisticsRead]


class ScoreDistributionBucketRead(BaseModel):
    bucket_start: float
    bucket_end: float
    count: int


class ScoreDistributionResponse(BaseModel):
    total_scored_jobs: int
    average_score: float | None = None
    minimum_score: float | None = None
    maximum_score: float | None = None
    bucket_size: float
    buckets: list[ScoreDistributionBucketRead]


class StatisticsResponse(BaseModel):
    ingested_jobs: IngestStatisticsResponse
    score_distribution: ScoreDistributionResponse


class ApplicationCountRead(BaseModel):
    label: str
    count: int
    percentage: float | None = None


class ApplicationDurationMetricRead(BaseModel):
    label: str
    count: int
    average_days: float | None = None
    minimum_days: float | None = None
    maximum_days: float | None = None


class ApplicationFunnelStageRead(BaseModel):
    label: str
    count: int
    percentage_from_start: float | None = None
    percentage_from_previous: float | None = None


class DailyApplicationActivityRead(BaseModel):
    activity_date: date
    applications: int
    screenings: int
    interviews: int
    rejections: int
    offers: int
    rolling_28_day_avg_applications: float
    rolling_28_day_avg_screenings: float
    rolling_28_day_avg_interviews: float
    rolling_28_day_avg_rejections: float
    rolling_28_day_avg_offers: float


class ApplicationStatisticsResponse(BaseModel):
    total_applications: int
    status_counts: list[ApplicationCountRead]
    stage_counts: list[ApplicationCountRead]
    duration_metrics: list[ApplicationDurationMetricRead]
    funnel: list[ApplicationFunnelStageRead]
    daily_activity: list[DailyApplicationActivityRead]


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
    prompt_key: str | None = None
    classification_key: str | None = None
    content: str
    is_active: bool = True
    is_default: bool = False


class ResumeUpdate(BaseModel):
    name: str | None = None
    prompt_key: str | None = None
    classification_key: str | None = None
    content: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None


class ResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    prompt_key: str
    classification_key: str | None = None
    content: str
    is_active: bool
    is_default: bool
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
    resume_strategy: Literal["classification_first", "default_only", "default_fallback"] = "classification_first"


class ApplicationGenerateResponse(BaseModel):
    created: int
    skipped: int
    applications: list[int]


class ApplicationsGenerateRunRequest(BaseModel):
    user_id: int
    limit: int = 100
    resume_strategy: Literal["classification_first", "default_only", "default_fallback"] = "classification_first"


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
    applied_notes: str | None = None
    screening_at: datetime | None = None
    screening_notes: str | None = None
    offer_at: datetime | None = None
    offer_notes: str | None = None
    rejected_at: datetime | None = None
    rejected_notes: str | None = None
    ghosted_at: datetime | None = None
    ghosted_notes: str | None = None
    withdrawn_at: datetime | None = None
    withdrawn_notes: str | None = None
    passed_at: datetime | None = None
    passed_notes: str | None = None


class ApplicationLifecycleDatesUpdate(BaseModel):
    applied_at: datetime | None = None
    applied_notes: str | None = None
    screening_at: datetime | None = None
    screening_notes: str | None = None
    offer_at: datetime | None = None
    offer_notes: str | None = None
    rejected_at: datetime | None = None
    rejected_notes: str | None = None
    ghosted_at: datetime | None = None
    ghosted_notes: str | None = None
    withdrawn_at: datetime | None = None
    withdrawn_notes: str | None = None
    passed_at: datetime | None = None
    passed_notes: str | None = None


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
    description: str | None = None
    classification_key: str | None = None
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
    applied_notes: str | None = None
    screening_at: datetime | None = None
    screening_notes: str | None = None
    offer_at: datetime | None = None
    offer_notes: str | None = None
    rejected_at: datetime | None = None
    rejected_notes: str | None = None
    ghosted_at: datetime | None = None
    ghosted_notes: str | None = None
    withdrawn_at: datetime | None = None
    withdrawn_notes: str | None = None
    passed_at: datetime | None = None
    passed_notes: str | None = None
    last_error_at: datetime | None = None
    next_interview_at: datetime | None = None
    next_interview_stage: str | None = None
    interview_rounds_total: int = 0
    created_at: datetime
    updated_at: datetime


class JobApplicationListResponse(BaseModel):
    total: int
    items: list[JobApplicationRead]


class JobApplicationScoreResponse(BaseModel):
    id: int
    job_posting_id: int
    resume_id: int
    resume_name: str | None = None
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


class ApplicationScoreWrite(BaseModel):
    score: float | None = None
    recommendation: str | None = None
    justification: str | None = None
    strengths: list[Any] | dict[str, Any] | None = None
    gaps: list[Any] | dict[str, Any] | None = None
    missing_from_jd: list[Any] | dict[str, Any] | None = None
    screening_likelihood: float | None = None
    dimension_scores: dict[str, float] | None = None
    gating_flags: list[str] | None = None
    prompt_key: str | None = None
    prompt_version: int | None = None
    scored_at: datetime | None = None
    status: str = "scored"


class JobClassificationRunRequest(BaseModel):
    classification_key: str | None = None
    prompt_key: str | None = None
    force: bool = False


class JobsClassificationRunRequest(BaseModel):
    limit: int = 25
    source: str | None = None
    classification_key: str | None = None
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
    classification_key: str | None = None
    prompt_key: str | None = None
    force: bool = False
    callback_url: str | None = None


class ApplicationScoreRunRequest(BaseModel):
    classification_key: str | None = None
    prompt_key: str | None = None
    force: bool = False
    refresh_resume_match: bool = False


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


class ApplicationNotificationWrite(BaseModel):
    notified_at: datetime | None = None
    status: str = "notified"


class ApplicationErrorWrite(BaseModel):
    error_at: datetime | None = None
    status: str = "error"


class InterviewRoundCreate(BaseModel):
    round_number: int
    stage_name: str | None = None
    status: Literal["scheduled", "completed"] = "scheduled"
    notes: str | None = None
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None


class InterviewRoundUpdate(BaseModel):
    round_number: int | None = None
    stage_name: str | None = None
    status: Literal["scheduled", "completed"] | None = None
    notes: str | None = None
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def reject_null_for_required_fields(self):
        if "round_number" in self.model_fields_set and self.round_number is None:
            raise ValueError("round_number may not be null")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status may not be null")
        return self


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
