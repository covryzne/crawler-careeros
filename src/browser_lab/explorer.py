import json
from .agent import create_agent, parse_output, history_debug
from .schemas import ExplorationOutput


def explorer_prompt(keyword: str, url: str, count: int) -> str:
    return f'''You are a keyword-conditioned job site exploration agent.
ORIGINAL KEYWORD: {json.dumps(keyword)}
EXACT SOURCE URL FROM GOOGLE: {json.dumps(url)}
MAX RELEVANT JOBS: {count}

PROCEDURE:
1. Navigate to the EXACT source URL, including path and query parameters. Do NOT replace it with a homepage.
2. Identify page type: job_listing, job_detail, homepage, irrelevant, blocked, unknown.
3. If listing, find jobs relevant to the original search intent. Open each selected job detail one by one (detail page, panel, or tab). Extract its OWN job fields, then move to the next.
4. If direct job_detail, extract that one job. If homepage/irrelevant, look for a keyword-relevant careers/listing route ONLY if clearly available; otherwise return no_relevant_jobs.
5. A role is eligible only when its title AND/OR actual responsibilities are clearly relevant to the search intent. For AI Engineer, adjacent technical roles can include ML Engineer, LLM Engineer, GenAI Engineer, or AI platform engineering. Exclude civil engineering, graphic design, unrelated operations, etc.
6. Do not fill the quota with unrelated vacancies. Maximum {count} jobs, fewer or zero is fine.
7. Each job: title, actual unique job detail URL (null if none), company, location, full visible description, requirements, salary, application URL (null if missing). Never copy another job's description or fabricate content.
8. The source_url output MUST equal the EXACT source URL above, even if the page redirects. Report redirects in notes.

INTERRUPTIONS:
- Cookie banner: use reject optional cookies or minimal consent when offered.
- Promo/newsletter modal: dismiss once; retry at most once.
- Optional login overlay: close or continue as guest; never log in.
- Mandatory login: status=login_required; return partial extracted jobs if any.
- Ordinary Cloudflare loading: wait briefly for normal completion.
- Interactive CAPTCHA/security challenge: do NOT solve/bypass; status=challenge_blocked.
- Access denied: status=access_denied; timeout/error: status=failed or partial.
- Never repeatedly click the same obstruction.

SAFETY:
No login, sign-up, Apply button, submission, downloading, or attempts to circumvent access restrictions. Respect the website's access rules. Do not visit localhost/private network endpoints. Stay on the site and directly linked job detail hosts.
If completed with relevant jobs: status=success. If some jobs extracted before interruption: status=partial. If no relevant jobs: status=no_relevant_jobs. Always provide explanatory notes for unexpected outcomes.
Return structured JSON matching the schema.
'''


async def explore(settings, source_url: str):
    agent = create_agent(explorer_prompt(settings.keyword, source_url, settings.max_jobs_per_source), settings, ExplorationOutput)
    history = await agent.run(max_steps=settings.explorer_steps)
    debug = history_debug(history)
    if not history.is_done() or history.is_successful() is False:
        raise RuntimeError(f'Exploration incomplete: {debug["errors"]}')
    return parse_output(history, ExplorationOutput), debug
