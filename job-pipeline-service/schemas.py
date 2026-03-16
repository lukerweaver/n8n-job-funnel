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
    jobs: list[str]


class JobScoreWrite(BaseModel):
    score: float | None = None
    recommendation: str | None = None
    justification: str | None = None
    strengths: list[Any] | dict[str, Any] | None = None
    gaps: list[Any] | dict[str, Any] | None = None
    missing_from_jd: list[Any] | dict[str, Any] | None = None
    prompt_key: str | None = None
    prompt_version: int | None = None
    scored_at: datetime | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    status: str = "scored"


class JobScoreBatchItem(JobScoreWrite):
    job_id: str


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    prompt_key: str | None
    prompt_version: int | None
    scored_at: datetime | None
    notified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    total: int
    items: list[JobRead]


class JobScoreResponse(BaseModel):
    job_id: str
    status: str
    score: float | None = None
    scored_at: datetime | None = None
    notified_at: datetime | None = None


class JobsBatchScoreResponse(BaseModel):
    updated: int
    jobs: list[str]


class JobNotifyWrite(BaseModel):
    notified_at: datetime | None = None
    status: str = "notified"


class JobNotifyBatchItem(JobNotifyWrite):
    job_id: str


class JobNotifyResponse(BaseModel):
    job_id: str
    status: str
    notified_at: datetime | None = None


class JobsBatchNotifyResponse(BaseModel):
    updated: int
    jobs: list[str]
