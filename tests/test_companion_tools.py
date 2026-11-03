"""Offline routing checks; scripted completions do not evaluate Muse reasoning."""

import json

import httpx
import pytest

from app.muse_client import spark_turn
from app.research import research_spark
from app.spark_replay import replay_turn, text_message, tool_message


@pytest.mark.asyncio
async def test_statute_mention_lead_is_opened_and_both_calls_remain_visible():
    async def source(name, arguments):
        if name == 'ic_cases_citing':
            return {'section_id': '99-1-1-1', 'results': [
                {'cluster_id': 'synthetic', 'case_name': 'Synthetic source',
                 'has_opinion_text': True}], 'flags': ['Text mentions only.']}
        assert name == 'case_get' and arguments == {'cluster_id': 'synthetic'}
        return {'found': True, 'cluster_id': 'synthetic',
                'case_name': 'Synthetic source', 'text': 'A public opinion body.'}

    result = await research_spark('Find and read an opinion.', turn=replay_turn([
        tool_message('ic_cases_citing', {'section_id': '99-1-1-1'}, 'mentions'),
        tool_message('case_get', {'cluster_id': 'synthetic'}, 'opinion'),
        text_message('The source is open; later history remains unchecked.'),
    ]), call_tool=source)
    assert result.complete and result.found
    assert [s['tool'] for s in result.steps] == ['ic_cases_citing', 'case_get']
    assert result.steps[0]['result']['result_count'] == 1
    assert result.steps[1]['result']['cluster_id'] == 'synthetic'


@pytest.mark.asyncio
async def test_spark_request_offers_companion_discovery_search_and_page(monkeypatch, tmp_path):
    # Catch missing or malformed schemas at the actual HTTP request boundary.
    monkeypatch.setenv("MODEL_API_KEY", "offline-test-key")
    from app.spend import SpendLedger
    path = tmp_path / "spend.sqlite"
    SpendLedger(path).configure("1", no_overage_verified=True, evidence="Synthetic offline test")
    monkeypatch.setenv("MUSE_SPEND_LEDGER_PATH", str(path))
    original_client = httpx.AsyncClient

    def receive(request):
        body = json.loads(request.content)
        schemas = {item["function"]["name"]: item["function"]["parameters"] for item in body["tools"]}
        assert {"ic_list_companion", "ic_search_companion", "ic_get_companion"} <= schemas.keys()
        assert schemas["ic_search_companion"]["required"] == ["query"]
        assert schemas["ic_search_companion"]["properties"]["year"]["type"] == "integer"
        assert schemas["ic_get_companion"]["required"] == ["doc_id"]
        assert schemas["ic_get_companion"]["properties"]["page"]["minimum"] == 1
        assert "ic_cases_citing" in schemas
        assert schemas["ic_cases_citing"]["required"] == ["section_id"]
        assert schemas["ic_cases_citing"]["properties"]["court"]["enum"] == ["ind", "indctapp", "indtc"]
        return httpx.Response(200, json=text_message("offline schema check"))

    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(receive), **kwargs),
    )
    await spark_turn([{"role": "user", "content": "Find Indiana's civil jury provision."}])


@pytest.mark.asyncio
@pytest.mark.parametrize("found", [True, False])
async def test_companion_page_controls_found_and_preserves_source_trace(monkeypatch, found):
    # Catch a successfully opened rule being mislabeled missing, and preserve provenance.
    monkeypatch.delenv("MODEL_API_KEY", raising=False)

    async def page(_name, arguments):
        assert arguments == {"doc_id": "court-rules-2026-small-claims", "page": 7}
        return {
            "found": found, "doc_id": "court-rules-2026-small-claims", "page": 7,
            "page_count": 15, "year": 2026, "compiled_on": "2026-06-23",
            "title": "Indiana court rules — small claims (2026)",
            "unofficial": True, "source_page": "https://iga.in.gov/laws/ic/downloads",
            "text": "Request for Jury Trial" if found else "",
        }

    result = await research_spark(
        "Open Small Claims Rule 4(C).",
        turn=replay_turn([
            tool_message("ic_get_companion", {"doc_id": "court-rules-2026-small-claims", "page": 7}, "rule"),
            text_message("Read the source page before relying on it."),
        ]),
        call_tool=page,
    )
    assert result.found is found
    assert result.steps[0]["result"]["doc_id"] == "court-rules-2026-small-claims"
    assert result.steps[0]["result"]["page"] == 7
    assert result.steps[0]["result"]["compiled_on"] == "2026-06-23"
    assert result.steps[0]["result"]["source_page"] == "https://iga.in.gov/laws/ic/downloads"
