"""Conservative baseline role filter; future iterations should evaluate using title + text similarity."""
import ipaddress
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

TRACKING_KEYS = {'fbclid', 'gclid', 'msclkid', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'utm_referrer'}


def is_safe_public_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        host = (p.hostname or '').lower().rstrip('.')
        if p.scheme not in ('http', 'https') or not host or p.username or p.password:
            return False
        if host in {'localhost', 'metadata.google.internal'} or host.endswith(('.localhost', '.local', '.internal')):
            return False
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_global
        except ValueError:
            return True
    except ValueError:
        return False


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    cleaned = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
               if k.lower() not in TRACKING_KEYS and not k.lower().startswith('utm_')]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/') or '/', urlencode(cleaned), ''))


def relevance_decision(keyword: str, job) -> tuple[bool, str]:
    """High precision filter for AI Engineer-like query; unknown queries are not auto-rejected."""
    title = (job.title or '').casefold()
    body = f'{job.description or ""} {job.requirements or ""}'.casefold()
    q = keyword.casefold()
    if 'ai' in q and ('engineer' in q or 'ml' in q):
        positive = ('ai engineer', 'artificial intelligence engineer', 'machine learning engineer',
                    'ml engineer', 'llm engineer', 'genai engineer', 'generative ai engineer',
                    'ai platform engineer', 'ai developer', 'machine learning developer',
                    'mlops engineer')
        if any(x in title for x in positive):
            return True, 'relevant technical role title'
        adjacent = ('data scientist', 'software engineer', 'backend engineer', 'research engineer')
        if any(x in title for x in adjacent) and any(x in body for x in ('machine learning', 'large language model', 'llm', 'deep learning', 'artificial intelligence')):
            return True, 'adjacent engineering title with AI responsibilities'
        return False, 'title and responsibilities not clearly relevant to AI engineering'
    return True, 'non-AI query: requires subsequent semantic relevance verification'
