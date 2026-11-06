from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.browser_lab.schemas import ExtractedJob

PortalName = Literal['linkedin', 'jobstreet', 'glints', 'indeed', 'dealls', 'kalibrr', 'techinasia']
PORTALS = ('linkedin', 'jobstreet', 'glints', 'indeed', 'dealls', 'kalibrr', 'techinasia')


@dataclass(frozen=True)
class CrawlRequest:
    keyword: str
    portals: tuple[str, ...]
    location: str = 'Indonesia'
    linkedin_geo_id: str = '102478259'
    days: int = 7
    max_pages: int = 2
    max_jobs: int = 20  # Per portal, including attempted details.
    timeout: float = 20
    delay: float = 2
    headless: bool | None = None  # None selects the adapter's browser default.
    auto_verify: bool = False  # Opt-in checkbox interaction for JobStreet/Indeed.
    verification_timeout: float = 60
    verification_max_clicks: int = 1
    indeed_user_data_dir: str | None = None

    def __post_init__(self):
        if not self.keyword.strip() or not self.location.strip():
            raise ValueError('keyword and location cannot be empty')
        if not self.portals or any(p not in PORTALS for p in self.portals):
            raise ValueError(f'Choose at least one supported portal: {PORTALS}')
        if len(set(self.portals)) != len(self.portals):
            raise ValueError('portals must be unique')
        if self.indeed_user_data_dir is not None:
            if not isinstance(self.indeed_user_data_dir, str) or not self.indeed_user_data_dir.strip():
                raise ValueError('indeed_user_data_dir must be a non-empty directory path')
            if 'indeed' not in self.portals:
                raise ValueError('--indeed-user-data-dir requires indeed in --portals')
            object.__setattr__(self, 'indeed_user_data_dir',
                               str(Path(self.indeed_user_data_dir).expanduser().resolve()))
        for name, maximum in (('days', 30), ('max_pages', 20), ('max_jobs', 200)):
            if not 1 <= getattr(self, name) <= maximum:
                raise ValueError(f'{name} must be between 1 and {maximum}')
        if not 0 < self.timeout <= 120 or not 0 <= self.delay <= 60:
            raise ValueError('timeout must be > 0 and <= 120; delay must be >= 0 and <= 60')
        if not 0 < self.verification_timeout <= 300:
            raise ValueError('verification_timeout must be > 0 and <= 300')
        if type(self.verification_max_clicks) is not int or not 1 <= self.verification_max_clicks <= 20:
            raise ValueError('verification_max_clicks must be an integer between 1 and 20')
        if not self.linkedin_geo_id.isdigit():
            raise ValueError('linkedin_geo_id must contain digits')
        if ('linkedin' in self.portals and self.location.casefold().strip() != 'indonesia'
                and self.linkedin_geo_id == '102478259'):
            raise ValueError('A custom LinkedIn location requires its corresponding --linkedin-geo-id')
        # Other JobStreet locations need explicit portal-specific mappings.
        for portal in ('jobstreet', 'glints', 'dealls', 'kalibrr', 'techinasia'):
            if portal in self.portals and self.location.casefold().strip() != 'indonesia':
                raise ValueError(f'{portal} currently supports location=Indonesia only')


@dataclass(frozen=True)
class JobReference:
    portal: str
    external_id: str
    url: str
    title: str
    discovered_from: str
    search_page: int
    observed_url: str | None = None
    company: str | None = None
    location: str | None = None
    salary: str | None = None
    snippet: str | None = None

    @property
    def key(self) -> str:
        return f'{self.portal}:{self.external_id}'


class CrawledJob(ExtractedJob):
    portal: PortalName
    external_id: str
    extraction_method: Literal['selenium'] = 'selenium'
    raw_description: str
    posted_at_raw: str | None = None
    observed_url: str
    keyword: str
    discovered_from: str
    search_page: int
    crawled_at: str
