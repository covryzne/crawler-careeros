"""Private stdin/JSONL bridge for CareerOS worker. No HTTP, database, or LLM."""
import contextlib
import json
import sys
from pathlib import Path

from .adapters import ADAPTERS
from .models import CrawlRequest
from .runner import run


def capabilities():
    return [dict(
        platform=name, status='experimental',
        date_filter=adapter.date_filter,
        default_headless=adapter.default_headless,
        location_scope='custom' if name in {'linkedin', 'indeed'} else 'Indonesia',
    ) for name, adapter in ADAPTERS.items()]


def main():
    if sys.argv[1:] == ['--capabilities']:
        print(json.dumps(capabilities()), flush=True)
        return
    data = json.loads(sys.stdin.readline())
    request = CrawlRequest(**data['request'])
    output = sys.stdout

    def emit(event):
        output.write(json.dumps(event, ensure_ascii=True) + '\n')
        output.flush()

    with contextlib.redirect_stdout(sys.stderr):
        result = run(request, Path(data['output_dir']), event_sink=emit,
                     seen_ids=data.get('seen_ids', []), known_ids=data.get('known_ids', []),
                     new_job_budget=data.get('new_job_budget'))
    emit({'type': 'finished', 'state': result['state']})


if __name__ == '__main__':
    main()
