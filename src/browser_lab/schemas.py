from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SearchHit(StrictModel):
    title: str
    url: HttpUrl
    snippet: str | None = None


class DiscoveryOutput(StrictModel):
    keyword: str
    search_engine: Literal['google']
    search_page: int
    sources: list[SearchHit] = Field(default_factory=list)
    notes: str | None = None


class ExtractedJob(StrictModel):
    title: str
    job_url: HttpUrl | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    requirements: str | None = None
    salary: str | None = None
    application_url: HttpUrl | None = None


class ExplorationOutput(StrictModel):
    source_url: HttpUrl
    page_type: Literal['job_listing', 'job_detail', 'homepage', 'irrelevant', 'blocked', 'unknown']
    status: Literal['success', 'partial', 'no_relevant_jobs', 'login_required', 'challenge_blocked', 'access_denied', 'failed']
    jobs: list[ExtractedJob] = Field(default_factory=list)
    notes: str | None = None
