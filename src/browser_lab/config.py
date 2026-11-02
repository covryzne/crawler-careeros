import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    provider: str
    google_model: str
    keyword: str
    max_search_pages: int
    max_sources: int
    max_jobs_per_source: int
    discovery_steps: int
    explorer_steps: int


def load_settings() -> Settings:
    load_dotenv()
    provider = os.getenv('LLM_PROVIDER', 'google').strip().lower()
    if provider not in {'google', 'browser_use'}:
        raise ValueError('LLM_PROVIDER must be google or browser_use')
    key = 'GOOGLE_API_KEY' if provider == 'google' else 'BROWSER_USE_API_KEY'
    if not os.getenv(key):
        raise RuntimeError(f'Missing {key} in .env')

    def pos_int(name: str, default: int, maximum: int) -> int:
        value = int(os.getenv(name, str(default)))
        if not 1 <= value <= maximum:
            raise ValueError(f'{name} must be between 1 and {maximum}')
        return value

    keyword = os.getenv('SEARCH_KEYWORD', 'AI Engineer loker').strip()
    if not keyword:
        raise ValueError('SEARCH_KEYWORD cannot be empty')
    return Settings(
        provider=provider,
        google_model=os.getenv('GOOGLE_MODEL', 'gemini-3.1-flash-lite'),
        keyword=keyword,
        max_search_pages=pos_int('MAX_SEARCH_PAGES', 1, 5),
        max_sources=pos_int('MAX_SOURCES', 3, 30),
        max_jobs_per_source=pos_int('MAX_JOBS_PER_SOURCE', 3, 20),
        discovery_steps=pos_int('DISCOVERY_STEPS', 20, 80),
        explorer_steps=pos_int('EXPLORER_STEPS', 40, 120),
    )
