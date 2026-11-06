"""Private failure evidence, captured before the browser is closed."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def capture_failure(driver, root: Path, *, portal, phase, status, headless, run_id,
                    page=None, external_id=None):
    detected_at = datetime.now(UTC).isoformat()
    identifier = f'{portal}-{phase}-{uuid.uuid4().hex}'
    relative = Path('artifacts') / identifier
    metadata = {
        'run_id': run_id, 'portal': portal, 'phase': phase, 'status': status,
        'headless': headless, 'page': page, 'external_id': external_id,
        'detected_at': detected_at, 'observed_url': None, 'page_title': None,
        'screenshot': None, 'capture_errors': {},
    }
    result = {'detected_at': detected_at, 'metadata': None, 'screenshot': None}
    try:
        (root / relative.parent).mkdir(parents=True, exist_ok=True)
        if driver is not None:
            try:
                parts = urlsplit(driver.current_url)
                # Never add credentials, query tokens or fragments to new metadata.
                if parts.scheme in {'http', 'https'} and parts.hostname:
                    metadata['observed_url'] = urlunsplit((
                        parts.scheme, parts.hostname, parts.path, '', ''
                    ))
            except Exception as exc:  # noqa: BLE001 - Browser evidence must be best effort.
                metadata['capture_errors']['url'] = type(exc).__name__
            try:
                metadata['page_title'] = driver.title[:500]
            except Exception as exc:  # noqa: BLE001 - A dead browser must not mask crawl failure.
                metadata['capture_errors']['title'] = type(exc).__name__
            try:
                image = root / relative.with_suffix('.png')
                if driver.save_screenshot(str(image)) and image.is_file() and image.stat().st_size:
                    metadata['screenshot'] = relative.with_suffix('.png').as_posix()
                    result['screenshot'] = metadata['screenshot']
                else:
                    metadata['capture_errors']['screenshot'] = 'ScreenshotNotSaved'
            except Exception as exc:  # noqa: BLE001 - Driver and filesystem failures vary.
                metadata['capture_errors']['screenshot'] = type(exc).__name__
        else:
            metadata['capture_errors']['screenshot'] = 'BrowserUnavailable'
        metadata['captured_at'] = datetime.now(UTC).isoformat()
        path = root / relative.with_suffix('.json')
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
        result['metadata'] = relative.with_suffix('.json').as_posix()
    except Exception as exc:  # noqa: BLE001 - Evidence must never prevent browser cleanup.
        # Evidence failure must never replace the actual crawl failure or skip cleanup.
        result['capture_error_type'] = type(exc).__name__
    return result
