import json

import pytest

from app.research import research_spark
from app.spark_replay import replay_turn, text_message, tool_message


@pytest.mark.asyncio
async def test_long_opinion_reaches_model_as_complete_valid_json():
    opinion = {"found": True, "text": "Background. " * 3000 + "We reverse and remand."}
    calls = 0

    async def turn(messages):
        nonlocal calls
        calls += 1
        if calls == 1:
            return tool_message("case_get", {"cluster_id": "852407"})
        delivered = json.loads(messages[-1]["content"])
        assert delivered == opinion
        return text_message('The disposition is "We reverse and remand."')

    async def source(*_):
        return opinion

    result = await research_spark("Read the disposition.", turn=turn, call_tool=source)
    assert result.complete and result.quotes_ok
    assert "reverse" in result.summary


@pytest.mark.asyncio
async def test_twenty_sequential_sources_leave_room_for_final_answer():
    script = [tool_message("ic_get_companion", {"doc_id": "public-test", "page": p}, str(p)) for p in range(1, 21)]
    script.append(text_message("All twenty requested public source pages were retrieved."))

    async def source(_name, arguments):
        return {"found": True, "doc_id": "public-test", "page": arguments["page"], "text": "Public test source."}

    result = await research_spark("Retrieve the source itinerary.", turn=replay_turn(script), call_tool=source)
    assert len(result.steps) == 20
    assert result.complete
    assert "twenty" in result.summary


@pytest.mark.asyncio
async def test_twenty_first_tool_is_rejected_without_fetching_an_extra_source():
    turns = 0

    async def endless(_messages):
        nonlocal turns
        turns += 1
        return tool_message("ic_get_companion", {"doc_id": "public-test", "page": turns}, str(turns))

    async def source(*_):
        return {"found": True, "text": "Public test source."}

    result = await research_spark("Keep looking.", turn=endless, call_tool=source)
    assert result.complete is False
    assert result.completion_state == "tool_limit"
    assert "incomplete" in result.summary.lower()
    assert turns == 21
    assert len(result.steps) == 20


@pytest.mark.asyncio
async def test_oversized_source_stops_explicitly_instead_of_cutting_json():
    async def source(*_):
        return {"found": True, "text": "x" * 200000}

    result = await research_spark("Read a very long opinion.", turn=replay_turn([
        tool_message("case_get", {"cluster_id": "public-test"}),
        text_message("Pretend the whole thing was read."),
    ]), call_tool=source)
    assert result.complete is False
    assert result.completion_state == "source_limit"
    assert "Pretend" not in result.summary
    assert "source" in result.catch.lower()


@pytest.mark.asyncio
async def test_opened_sources_have_clickable_cards_and_page_identity():
    async def source(*_):
        return {"found": True, "doc_id": "constitution-2026", "page": 3,
                "title": "Indiana Constitution", "year": 2026, "compiled_on": "2026-06-23",
                "source_page": "https://iga.in.gov/laws/ic/downloads", "text": "Public source."}

    result = await research_spark("Open the constitution.", turn=replay_turn([
        tool_message("ic_get_companion", {"doc_id": "constitution-2026", "page": 3}),
        text_message("Inspect the provision at the source."),
    ]), call_tool=source)
    assert result.source_cards[0]["url"] == "https://iga.in.gov/laws/ic/downloads"
    assert result.source_cards[0]["page"] == 3


@pytest.mark.asyncio
async def test_output_token_limit_does_not_label_partial_answer_complete():
    response = text_message("An unfinished legal conclusion")
    response["choices"][0]["finish_reason"] = "length"
    result = await research_spark("Answer the question.", turn=replay_turn([response]), call_tool=lambda *_: None)
    assert result.complete is False
    assert result.completion_state == "output_limit"
    assert "unfinished legal conclusion" not in result.summary


@pytest.mark.asyncio
async def test_content_filter_does_not_present_partial_conclusion_as_complete():
    response = text_message("A partial filtered legal conclusion")
    response["choices"][0]["finish_reason"] = "content_filter"
    result = await research_spark("Answer the question.", turn=replay_turn([response]), call_tool=lambda *_: None)
    assert result.complete is False
    assert result.completion_state == "model_incomplete"
    assert "partial filtered legal conclusion" not in result.summary


@pytest.mark.asyncio
async def test_mid_research_credit_stop_preserves_sources_without_retry():
    from app.muse_client import CreditNotReady
    turns = 0
    async def turn(_messages):
        nonlocal turns
        turns += 1
        if turns == 1:
            return tool_message('case_get', {'cluster_id': 'public-test'})
        raise CreditNotReady('Ledger insufficient for request upper bound')
    async def source(*_):
        return {'found': True, 'text': 'Public opinion text.', 'case_name': 'Public case',
                'cluster_id': 'public-test', 'url': 'https://example.com/opinion'}
    result = await research_spark('Read the opinion.', turn=turn, call_tool=source)
    assert turns == 2
    assert not result.complete and result.completion_state == 'credit_limit'
    assert result.found and len(result.steps) == 1
    assert result.source_cards[0]['cluster_id'] == 'public-test'
    assert 'incomplete' in result.summary.lower()


@pytest.mark.asyncio
async def test_unretrieved_model_answer_does_not_become_a_completed_research_result():
    result = await research_spark('What does the court hold?', turn=replay_turn([
        text_message('IC 99-99-99-99 means all tenants win automatically.'),
    ]), call_tool=lambda *_: None)
    assert not result.complete and result.completion_state == 'no_evidence'
    assert 'all tenants win' not in result.summary
