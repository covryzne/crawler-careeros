"""Exercise the real orchestration/validation with deterministic agent outputs, no LLM calls."""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from src.browser_lab.config import Settings
from src.browser_lab.schemas import DiscoveryOutput, ExplorationOutput, ExtractedJob, SearchHit


SOURCE = 'https://www.remoterocketship.com/'


def orchestrator(monkeypatch, status, jobs):
    async def discover(*args, **kwargs):
        return DiscoveryOutput(keyword='AI Engineer Indonesia', search_engine='google',
                               search_page=1, sources=[SearchHit(title='AI jobs', url=SOURCE)]), {}
    async def explore(*args, **kwargs):
        return ExplorationOutput(source_url=SOURCE, page_type='job_listing', status=status,
                                 jobs=jobs, notes='Source observation'), {}
    for name, function in [('discovery', discover), ('explorer', explore)]:
        stub = types.ModuleType(f'src.browser_lab.{name}')
        setattr(stub, 'discover' if name == 'discovery' else 'explore', function)
        monkeypatch.setitem(sys.modules, stub.__name__, stub)
    path = Path(__file__).resolve().parents[1] / 'src/browser_lab/orchestrator.py'
    spec = importlib.util.spec_from_file_location('src.browser_lab._orchestrator_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'load_settings', lambda: Settings(
        provider='google', google_model='test', keyword='AI Engineer Indonesia',
        max_search_pages=1, max_sources=1, max_jobs_per_source=2, discovery_steps=1, explorer_steps=1))
    return module


def test_partial_source_and_rejected_urls_cannot_report_complete(tmp_path, monkeypatch):
    module = orchestrator(monkeypatch, 'partial', [
        ExtractedJob(title='AI Engineer', job_url=None),
        ExtractedJob(title='AI Engineer II', job_url=None),
    ])
    result = asyncio.run(module.run(tmp_path))
    assert result['state'] == 'completed_with_errors'
    assert result['jobs'] == []
    assert result['sources'][0]['rejection_reasons'] == {'missing unique job detail URL': 2}
    assert result['errors'][0]['code'] == 'SOURCE_PARTIAL'
    saved = json.loads(next(tmp_path.glob('*/manifest.json')).read_text(encoding='utf-8'))
    assert saved['state'] == 'completed_with_errors'


def test_partial_source_keeps_valid_extractions(tmp_path, monkeypatch):
    module = orchestrator(monkeypatch, 'partial', [
        ExtractedJob(title='AI Engineer', job_url='https://example.com/jobs/123',
                     company='Example', description='Build AI systems'),
    ])
    result = asyncio.run(module.run(tmp_path))
    assert result['state'] == 'completed_with_errors'
    assert len(result['jobs']) == 1
    assert next(tmp_path.glob('*/jobs.json')).exists()


@pytest.mark.parametrize('status', ['login_required', 'challenge_blocked', 'access_denied', 'failed'])
def test_non_exception_source_failures_are_recorded(tmp_path, monkeypatch, status):
    result = asyncio.run(orchestrator(monkeypatch, status, []).run(tmp_path))
    assert result['state'] == 'completed_with_errors'
    assert result['errors'][0]['status'] == status


def test_real_empty_result_remains_successful(tmp_path, monkeypatch):
    result = asyncio.run(orchestrator(monkeypatch, 'no_relevant_jobs', []).run(tmp_path))
    assert result['state'] == 'completed'
    assert result['errors'] == []


def test_agent_success_does_not_override_missing_url_validation(tmp_path, monkeypatch):
    result = asyncio.run(orchestrator(monkeypatch, 'success', [ExtractedJob(title='AI Engineer')]).run(tmp_path))
    assert result['sources'][0]['reported_status'] == 'success'
    assert result['sources'][0]['state'] == 'partial'
    assert result['state'] == 'completed_with_errors'


def test_relevance_filtering_alone_is_not_an_execution_failure(tmp_path, monkeypatch):
    result = asyncio.run(orchestrator(monkeypatch, 'success', [
        ExtractedJob(title='Civil Engineer', job_url='https://example.com/jobs/123'),
    ]).run(tmp_path))
    assert result['jobs'] == []
    assert result['state'] == 'completed'


def test_cli_exit_code_reports_partial_failure(tmp_path, monkeypatch):
    module = orchestrator(monkeypatch, 'partial', [])
    with pytest.raises(SystemExit) as exc:
        module.main(tmp_path)
    assert exc.value.code == 1
