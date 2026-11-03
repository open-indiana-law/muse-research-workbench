import pytest

from app.research import DISCLAIMER, research_spark
from app.spark_replay import replay_turn, text_message, tool_message


async def statute_tools(name, arguments):
    if name == "ic_resolve_citation":
        return {"citations": [{"section_id": "31-16-15-25", "exists_in_latest_snapshot": True}]}
    if name == "ic_get_section":
        return {
            "found": True,
            "section_id": "31-16-15-25",
            "heading": "Income payor penalties",
            "snapshot_year": 2026,
            "text": "An income payor that discriminates…",
        }
    if name == "ic_get_versions":
        return {"versions": [{"snapshot_years": [2017, 2025]}, {"snapshot_years": [2026]}]}
    raise AssertionError(name)


@pytest.mark.asyncio
async def test_replay_statute_loop_without_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    turn = replay_turn(
        [
            tool_message("ic_resolve_citation", {"text": "IC 31-16-15-25"}, "1"),
            tool_message("ic_get_section", {"section_id": "31-16-15-25"}, "2"),
            tool_message("ic_get_versions", {"section_id": "31-16-15-25"}, "3"),
            text_message(
                "Income payor penalties from the unofficial 2026 snapshot.\n\n" + DISCLAIMER
            ),
        ]
    )
    result = await research_spark(
        "What does IC 31-16-15-25 say?",
        turn=turn,
        call_tool=statute_tools,
    )
    assert result.mode == "spark"
    assert result.found is True
    assert result.quotes_ok is True
    assert result.catch and "snapshot group" in result.catch
    assert [step["tool"] for step in result.steps] == [
        "ic_resolve_citation",
        "ic_get_section",
        "ic_get_versions",
    ]


@pytest.mark.asyncio
async def test_replay_rejects_invented_quote(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    turn = replay_turn(
        [
            tool_message("ic_resolve_citation", {"text": "IC 31-16-15-25"}, "1"),
            tool_message("ic_get_section", {"section_id": "31-16-15-25"}, "2"),
            tool_message("ic_get_versions", {"section_id": "31-16-15-25"}, "3"),
            text_message('The court relied on "999 N.E.3d 1 (Ind. 2099)".'),
        ]
    )
    result = await research_spark(
        "What does IC 31-16-15-25 say?",
        turn=turn,
        call_tool=statute_tools,
    )
    assert result.quotes_ok is False
    assert "999 N.E.3d 1" not in result.summary
    assert "quoted span was not verified" in (result.catch or "").lower()


@pytest.mark.asyncio
async def test_replay_bad_cite_does_not_fetch(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)

    async def only_resolve(name, arguments):
        if name == "ic_resolve_citation":
            return {
                "citations": [
                    {
                        "section_id": "99-1-1-1",
                        "citation": "IC 99-1-1-1",
                        "exists_in_latest_snapshot": False,
                    }
                ]
            }
        raise AssertionError(name)

    turn = replay_turn(
        [
            tool_message("ic_resolve_citation", {"text": "IC 99-1-1-1"}, "1"),
            text_message("IC 99-1-1-1 is not in the latest unofficial snapshot."),
        ]
    )
    result = await research_spark("What does IC 99-1-1-1 say?", turn=turn, call_tool=only_resolve)
    assert result.found is False
    assert result.catch and "not in the latest" in result.catch
    assert [step["tool"] for step in result.steps] == ["ic_resolve_citation"]
