"""Small helpers for observed public DOM sections and matching JobPosting metadata."""
import json

from selenium.webdriver.common.by import By

from .base import first_text


def heading_section(root, label):
    # Immediate content only: never consume a parent containing company/recommended jobs.
    for heading in root.find_elements(By.CSS_SELECTOR, 'h2, h3'):
        if heading.is_displayed() and heading.text.strip().casefold() == label.casefold():
            siblings = heading.find_elements(By.XPATH, './following-sibling::*[1]')
            if siblings and siblings[0].tag_name.lower() in {'div', 'ul', 'p'}:
                return first_text(heading.find_element(By.XPATH, '..'), (':scope > div', ':scope > ul', ':scope > p'))
    return None


def join_sections(parts):
    return '\n\n'.join(dict.fromkeys(part for part in parts if part)) or None


def matching_posting(adapter, driver, ref):
    title = first_text(driver, adapter.title_selectors)
    matches = []
    for script in driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_attribute('textContent') or '')
        except (ValueError, TypeError):
            continue
        queue = list(data) if isinstance(data, list) else [data]
        while queue:
            item = queue.pop()
            if not isinstance(item, dict):
                continue
            graph = item.get('@graph')
            if isinstance(graph, list):
                queue.extend(graph)
            if item.get('@type') != 'JobPosting' or item.get('title') != title:
                continue
            url = item.get('url') or item.get('@id')
            if url:
                identity = adapter.reference(url, '', '', 1) if isinstance(url, str) else None
                if identity is None or identity.key != ref.key:
                    continue
            matches.append(item)
    return matches[0] if len(matches) == 1 else {}


def posting_metadata(posting):
    fields = {}
    date = posting.get('datePosted')
    if isinstance(date, str) and date:
        fields['posted_at_raw'] = date
    place = posting.get('jobLocation', {})
    places = place if isinstance(place, list) else [place]
    locations = []
    for place in places:
        address = place.get('address', {}) if isinstance(place, dict) else {}
        if isinstance(address, dict):
            parts = [address.get(k) for k in ('addressLocality', 'addressRegion', 'addressCountry')]
            value = ', '.join(dict.fromkeys(v for v in parts if isinstance(v, str) and v))
            if value:
                locations.append(value)
    if locations:
        fields['location'] = '; '.join(dict.fromkeys(locations))
    return fields
