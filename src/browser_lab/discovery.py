import json
from urllib.parse import urlencode
from .agent import create_agent, parse_output, history_debug
from .schemas import DiscoveryOutput


def discovery_prompt(keyword: str, page_number: int, count: int) -> str:
    # Google start=0,10,20...; agent is explicitly told not to rewrite this URL.
    serp_url = 'https://www.google.com/search?' + urlencode({
        'q': keyword, 'hl': 'id', 'gl': 'ID', 'num': '10', 'start': str((page_number - 1) * 10)
    })
    return f'''You are a Google organic search discovery agent.
EXACT QUERY: {json.dumps(keyword)}
SEARCH PAGE NUMBER: {page_number}
EXACT GOOGLE SEARCH URL: {serp_url}

1. Navigate directly to the EXACT Google Search URL above. Do not start from the Google homepage.
2. Extract up to {count} distinct ORGANIC result links appearing on THIS search results page.
3. For each result, preserve the full observed destination URL, visible title, and snippet (or null).
4. Include job listings, career categories, direct vacancy links; exclude Google internal links, advertisements, general tutorials and courses.
5. Do not replace specific results with their domain homepages. Do not manufacture or shorten URLs.
6. Do NOT visit result websites in this task. The orchestrator will explore them separately.
7. Do not solve security challenges, log in, or bypass restrictions. On blockage return an empty list with notes.
8. Return structured data: keyword={json.dumps(keyword)}, search_engine='google', search_page={page_number}.
The search_page field is the requested page number, NOT the number of visible result items.
'''


async def discover(settings, page_number: int, count: int):
    agent = create_agent(discovery_prompt(settings.keyword, page_number, count), settings, DiscoveryOutput)
    history = await agent.run(max_steps=settings.discovery_steps)
    debug = history_debug(history)
    if not history.is_done() or history.is_successful() is False:
        raise RuntimeError(f'Discovery incomplete: {debug["errors"]}')
    output = parse_output(history, DiscoveryOutput)
    if output.keyword != settings.keyword or output.search_page != page_number:
        raise ValueError('Discovery context mismatch')
    return output, debug
