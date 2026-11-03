import pytest

from app.law_gateway import LawGateway
from app.muse_client import CreditNotReady, require_spark_key
from app.research import (
    CASELAW_CATCH,
    _missing_catch,
    _run_tools,
    _versions_catch,
    classify,
    extract_citation,
    quote_failures,
)


def test_extract_and_classify():
    assert extract_citation("See IC 31-16-15-25 please") == "IC 31-16-15-25"
    assert classify("What does IC 31-16-15-25 say?") == "statute"
    assert classify("Did IC 31-16-15-25 change across unofficial snapshots?") == "currency"
    assert classify("What does IC 99-1-1-1 say?") == "bad_cite"
    assert classify("Open Horton and tell me what it cites.") == "caselaw"


def test_catches():
    assert "not in the latest" in (_missing_catch({
        "citations": [{"citation": "IC 99-1-1-1", "exists_in_latest_snapshot": False}]
    }) or "")
    assert "more than one" in (_versions_catch({
        "versions": [
            {"snapshot_years": [2017, 2025]},
            {"snapshot_years": [2026]},
        ]
    }) or "")


def test_spark_stays_closed_without_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(CreditNotReady):
        require_spark_key()


@pytest.mark.asyncio
async def test_fixture_statute_and_currency():
    async def fake(name, arguments):
        if name == "ic_resolve_citation":
            return {"citations": [{"section_id": "31-16-15-25", "exists_in_latest_snapshot": True}]}
        if name == "ic_get_section":
            return {"found": True, "section_id": "31-16-15-25", "heading": "Income payor penalties", "snapshot_year": 2026, "text": "An income payor that discriminates…"}
        if name == "ic_get_versions":
            return {"versions": [{"snapshot_years": [2017, 2025]}, {"snapshot_years": [2026]}]}
        raise AssertionError(name)

    gateway = LawGateway(call_tool=fake)
    result = await _run_tools(gateway, "statute", "What does IC 31-16-15-25 say?", None)
    assert result.found is True
    assert result.catch and "snapshot group" in result.catch
    assert [step.tool for step in gateway.steps] == ["ic_resolve_citation", "ic_get_section", "ic_get_versions"]


@pytest.mark.asyncio
async def test_fixture_bad_cite_does_not_fetch_text():
    async def fake(name, arguments):
        if name == "ic_resolve_citation":
            return {"citations": [{"section_id": "99-1-1-1", "exists_in_latest_snapshot": False, "citation": "IC 99-1-1-1"}]}
        raise AssertionError(name)

    gateway = LawGateway(call_tool=fake)
    result = await _run_tools(gateway, "bad_cite", "What does IC 99-1-1-1 say?", None)
    assert result.found is False
    assert result.catch and "Bad-cite" in result.catch
    assert [step.tool for step in gateway.steps] == ["ic_resolve_citation"]


def test_quote_check_rejects_invented_wording():
    results = [{"case_name": "Jerry Horton v. State of Indiana", "text": "On April 11, 2011, the trial court sentenced Horton."}]
    assert quote_failures('The opinion said "On April 11, 2011, the trial court sentenced Horton."', results) == []
    failures = quote_failures('The court relied on "999 N.E.3d 1 (Ind. 2099)".', results)
    assert failures and "999 N.E.3d 1" in failures[0]


@pytest.mark.asyncio
async def test_fixture_horton_uses_named_hit_and_cited_in():
    async def fake(name, arguments):
        if name == "case_search":
            assert arguments["query"] == "Horton"
            return {
                "results": [
                    {
                        "cluster_id": "2760229",
                        "case_name": "Jerry Horton v. State of Indiana",
                        "date_filed": "2014-12-12",
                    },
                    {
                        "cluster_id": "2234235",
                        "case_name": "Spratt v. Alsup",
                        "date_filed": "1984-04-26",
                    },
                ]
            }
        if name == "case_get":
            assert arguments["cluster_id"] == "2760229"
            return {
                "found": True,
                "cluster_id": "2760229",
                "case_name": "Jerry Horton v. State of Indiana",
                "court": "Indiana Court of Appeals",
                "date_filed": "2014-12-12",
                "precedential_status": "Unpublished",
                "decision_form": "memorandum",
                "citability": "limited",
                "url": "https://www.courtlistener.com/opinion/2760229/jerry-horton-v-state-of-indiana/",
                "text": "On April 11, 2011, the trial court sentenced Horton in accordance with the terms of the plea agreement.",
            }
        if name == "cases_cited_in":
            assert arguments["query"] == "2760229"
            return {
                "results": [
                    {"cluster_id": "2725854", "case_name": "Dayron Bell v. State of Indiana", "date_filed": "2013-12-31"},
                    {"cluster_id": "2038017", "case_name": "Jones v. State", "date_filed": "2006-05-04"},
                ]
            }
        raise AssertionError(name)

    gateway = LawGateway(call_tool=fake)
    result = await _run_tools(gateway, "caselaw", "Open Horton and tell me what it cites.", None)
    assert result.found is True
    assert result.quotes_ok is True
    assert CASELAW_CATCH in (result.catch or "")
    assert "Jerry Horton v. State of Indiana" in result.summary
    assert "Dayron Bell v. State of Indiana" in result.summary
    assert "Spratt v. Alsup" not in result.summary
    assert [step.tool for step in gateway.steps] == ["case_search", "case_get", "cases_cited_in"]
    assert result.source_cards[0]["cluster_id"] == "2760229"
