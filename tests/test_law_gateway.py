import pytest

from app.law_gateway import ALLOWED_TOOLS, LawGateway


@pytest.mark.asyncio
async def test_resolve_and_fetch_records_trace():
    calls = []

    async def fake(name, arguments):
        calls.append((name, arguments))
        if name == "ic_resolve_citation":
            return {"citations": [{"section_id": "31-16-15-25"}]}
        if name == "ic_get_section":
            return {"found": True, "section_id": "31-16-15-25", "heading": "Income withholding"}
        raise AssertionError(name)

    gateway = LawGateway(call_tool=fake)
    packet = await gateway.resolve_and_fetch_section("IC 31-16-15-25", as_of="2026-07-01")
    assert packet["found"] is True
    assert [step.tool for step in gateway.steps] == ["ic_resolve_citation", "ic_get_section"]
    assert calls[1][1] == {"section_id": "31-16-15-25", "as_of": "2026-07-01"}


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected():
    async def fake(name, arguments):
        return {}

    gateway = LawGateway(call_tool=fake)
    with pytest.raises(ValueError, match="not allowlisted"):
        await gateway.invoke("shell", {"cmd": "id"})


def test_allowlist_covers_hosted_sixteen():
    assert "ic_get_section" in ALLOWED_TOOLS
    assert "case_resolve" not in ALLOWED_TOOLS
    assert len(ALLOWED_TOOLS) == 16
