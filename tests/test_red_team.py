import pytest
from fastapi.testclient import TestClient

from app.research import quote_failures, research_spark
from app.spark_replay import replay_turn, text_message, tool_message


def test_request_metadata_cannot_validate_a_legal_quotation():
    assert quote_failures('The court held "Every tenant wins automatically."', [{
        'found': True, 'text': 'The judgment is reversed.',
        'query': 'Every tenant wins automatically.',
        'heading': 'Every tenant wins automatically.',
    }])


def test_exact_closed_classifier_label_can_be_described_without_becoming_a_holding():
    assert quote_failures('The classifier says "mixed".', [{
        'found': True, 'text': 'Reversed and remanded.', 'disposition': 'mixed',
    }]) == []
    assert quote_failures('The court held "Every tenant wins automatically".', [{
        'found': True, 'text': 'Reversed and remanded.',
        'disposition': 'Every tenant wins automatically',
    }])


def test_markdown_blockquote_cannot_present_a_paraphrase_as_verbatim():
    assert quote_failures('> The tenant always wins.', [{'found': True, 'text': 'The tenant may present a defense.'}])
    assert quote_failures('> The tenant may present a defense.', [{'found': True, 'text': 'The tenant may present a defense.'}]) == []


def test_actual_numeric_source_identifier_is_not_an_opinion_quotation():
    assert quote_failures('Opened cluster "2760229".', [{
        'found': True, 'text': 'A public opinion.', 'cluster_id': '2760229',
    }]) == []
    assert quote_failures('The court held "Every tenant wins".', [{
        'found': True, 'text': 'A public opinion.', 'cluster_id': 'Every tenant wins',
    }])


@pytest.mark.parametrize('quote', ['"Every tenant wins automatically.”', '“Every tenant wins automatically."'])
def test_mixed_double_quote_typography_does_not_skip_validation(quote):
    assert quote_failures(quote, [{'text': 'The judgment is reversed.'}])


@pytest.mark.asyncio
async def test_transport_failure_after_source_retains_trace_and_no_conclusion():
    import httpx
    calls = 0
    async def turn(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            return tool_message('case_get', {'cluster_id': 'synthetic'})
        raise httpx.ReadTimeout('synthetic transport failure')
    async def source(*_):
        return {'found': True, 'text': 'A public opinion body.', 'cluster_id': 'synthetic'}
    result = await research_spark('Read the opinion.', turn=turn, call_tool=source)
    assert not result.complete and result.completion_state == 'transport_error'
    assert len(result.steps) == 1 and result.found
    assert calls == 2


@pytest.mark.asyncio
async def test_source_transport_failure_retains_previous_source():
    import httpx
    calls = 0
    async def source(*_):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise httpx.ReadTimeout('Synthetic source timeout')
        return {'found': True, 'text': 'A public opinion body.'}
    result = await research_spark('Read two opinions.', turn=replay_turn([
        tool_message('case_get', {'cluster_id': 'one'}),
        tool_message('case_get', {'cluster_id': 'two'}),
    ]), call_tool=source)
    assert not result.complete and result.completion_state == 'source_error'
    assert result.found and len(result.steps) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('lookup,arguments', [
    ('case_search', {'query': 'synthetic'}),
    ('ic_cases_citing', {'section_id': '99-99-99-99'}),
])
async def test_search_lead_cannot_qualify_a_completed_legal_answer(lookup, arguments):
    async def source(*_):
        return {'results': [], 'found': False}
    result = await research_spark('What is the holding?', turn=replay_turn([
        tool_message(lookup, arguments),
        text_message('IC 99-99-99-99 guarantees every tenant wins automatically.'),
    ]), call_tool=source)
    assert not result.complete and result.completion_state == 'no_evidence'
    assert 'every tenant wins' not in result.summary


@pytest.mark.asyncio
async def test_verified_missing_citation_can_still_return_a_limited_result():
    async def source(*_):
        return {'citations': [{'section_id': '99-1-1-1', 'citation': 'IC 99-1-1-1',
                               'exists_in_latest_snapshot': False}]}
    result = await research_spark('What does IC 99-1-1-1 say?', turn=replay_turn([
        tool_message('ic_resolve_citation', {'text': 'IC 99-1-1-1'}),
        text_message('This citation is missing from the latest unofficial snapshot.'),
    ]), call_tool=source)
    assert result.complete and not result.found


def test_cross_site_form_is_refused_before_any_credential_write(monkeypatch):
    from app.server import app
    called = []
    monkeypatch.setattr('app.server.write_key', lambda secret: called.append(secret))
    client = TestClient(app)
    response = client.post('/set-key', data={'key': 'synthetic-no-secret'}, headers={
        'Origin': 'https://attacker.invalid', 'Sec-Fetch-Site': 'cross-site'})
    assert response.status_code == 403
    assert called == []


def test_untrusted_host_cannot_dispatch_research(monkeypatch):
    from app.server import app
    called = []
    async def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError('Untrusted host reached research')
    monkeypatch.setattr('app.server.research', forbidden)
    client = TestClient(app, base_url='http://attacker.invalid')
    response = client.post('/research', json={'question': 'synthetic query'})
    assert response.status_code == 400
    assert called == []


def test_trace_keeps_classifier_and_dispositive_passage():
    from app.law_gateway import TraceStep
    from app.research import _step_dict
    result = _step_dict(TraceStep('case_get', {'cluster_id': '852407'}, {
        'found': True, 'text': 'Background. ' * 100 + 'We reverse.',
        'disposition': 'affirmed', 'disposition_quote': 'We reverse.',
        'disposition_method': 'classifier',
    }))['result']
    assert result['disposition'] == 'affirmed'
    assert result['disposition_quote'] == 'We reverse.'
    assert 'We reverse.' in result['text_ending']


def test_verified_johnson_link_is_separate_from_generic_engine_url():
    from app.law_gateway import LawGateway, TraceStep
    from app.research import TurnResult, _finish
    gateway = LawGateway(call_tool=None)
    gateway.steps.append(TraceStep('case_get', {'cluster_id': 'incourts-1106156996'}, {
        'found': True, 'cluster_id': 'incourts-1106156996', 'text': 'Public opinion.',
        'case_name': 'Johnson v. Housing Authority', 'url': 'https://www.courtlistener.com/',
    }))
    result = _finish(TurnResult('q', 'spark', 'test', True, None, 'Public answer.', ''), gateway)
    assert result.source_cards[0]['url'] == 'https://www.courtlistener.com/'
    assert result.source_cards[0]['official_url'].startswith('https://public.courts.in.gov/Decisions/')
