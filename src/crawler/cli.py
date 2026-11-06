import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .models import CrawlRequest, PORTALS


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description='Standalone CareerOS crawler')
    cli.add_argument('--mode', choices=('browser-use', 'selenium'), default='browser-use')
    cli.add_argument('--keyword', help='Search intent; defaults to SEARCH_KEYWORD in .env')
    cli.add_argument('--portals', nargs='+', choices=PORTALS)
    cli.add_argument('--location', default='Indonesia')
    cli.add_argument('--linkedin-geo-id', default='102478259')
    cli.add_argument('--days', type=int, default=7)
    cli.add_argument('--max-pages', type=int, default=2)
    cli.add_argument('--max-jobs', type=int, default=20, help='Maximum detail attempts per portal')
    cli.add_argument('--timeout', type=float, default=20)
    cli.add_argument('--delay', type=float, default=2, help='Seconds between browser operations')
    cli.add_argument('--auto-verify', action='store_true',
                     help='Try available Cloudflare checkboxes on JobStreet/Indeed')
    cli.add_argument('--verification-max-clicks', type=int, default=1,
                     help='Maximum checkbox clicks per verification stage (1-20, default 1)')
    cli.add_argument('--verification-timeout', type=float, default=60,
                     help='Seconds to wait per verification stage with --auto-verify (maximum 300)')
    cli.add_argument('--indeed-user-data-dir',
                     help='Dedicated persistent Chrome user-data directory for Indeed only')
    browser = cli.add_mutually_exclusive_group()
    browser.add_argument('--headed', dest='headless', action='store_false',
                         help='Show the browser for all selected portals')
    browser.add_argument('--headless', dest='headless', action='store_true',
                         help='Force headless for all selected portals, including JobStreet/Glints')
    cli.set_defaults(headless=None)
    cli.add_argument('--output-dir', type=Path, default=Path('output/runs'))
    return cli


def main(argv=None):
    cli = parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = cli.parse_args(argv)
    load_dotenv()
    if args.mode == 'browser-use':
        selenium_flags = ('--portals', '--location', '--linkedin-geo-id', '--days',
                          '--max-pages', '--max-jobs', '--timeout', '--delay', '--headed', '--headless',
                          '--auto-verify', '--verification-timeout', '--verification-max-clicks',
                          '--indeed-user-data-dir')
        if any(value.split('=', 1)[0] in selenium_flags for value in argv):
            cli.error('Portal, location, date, page, job and browser options require --mode selenium; '
                      'Browser Use uses the existing .env settings')
        if args.keyword is not None:
            if not args.keyword.strip():
                cli.error('--keyword cannot be empty')
            os.environ['SEARCH_KEYWORD'] = args.keyword
        # Lazy import: deterministic crawling never loads Browser Use or requires an LLM key.
        from src.browser_lab.orchestrator import main as browser_main
        browser_main(output_dir=args.output_dir)
        return
    try:
        request = CrawlRequest(
            keyword=args.keyword if args.keyword is not None else os.getenv('SEARCH_KEYWORD', 'AI Engineer'),
            portals=tuple(args.portals or PORTALS), location=args.location,
            linkedin_geo_id=args.linkedin_geo_id, days=args.days,
            max_pages=args.max_pages, max_jobs=args.max_jobs,
            timeout=args.timeout, delay=args.delay, headless=args.headless,
            auto_verify=args.auto_verify, verification_timeout=args.verification_timeout,
            verification_max_clicks=args.verification_max_clicks,
            indeed_user_data_dir=args.indeed_user_data_dir,
        )
    except ValueError as exc:
        cli.error(str(exc))
    from .runner import run
    result = run(request, args.output_dir)
    if result['state'] != 'completed':
        raise SystemExit(1)
