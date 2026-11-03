import pytest


@pytest.mark.asyncio
async def test_rehearsal_is_explicit_and_visits_all_four_source_types():
    from app.eviction_demo import DEMO_QUESTION, rehearse_eviction

    async def sources(name, args):
        return {"found": True, "text": "Public source for routing test only.", **args,
                "source_page": "https://iga.in.gov/laws/ic/downloads"}

    result = await rehearse_eviction(DEMO_QUESTION, call_tool=sources)
    assert result.mode == "rehearsal"
    assert result.planner == "scripted rehearsal; no Muse inference"
    assert result.complete
    assert len(result.steps) == 10
    assert {s["tool"] for s in result.steps} == {"ic_get_companion", "ic_get_section", "case_get"}
    assert "Rehearsal" in result.summary
    assert result.spark_ready is False


@pytest.mark.asyncio
async def test_missing_rehearsal_source_does_not_present_prepared_conclusion():
    from app.eviction_demo import DEMO_QUESTION, rehearse_eviction
    async def missing(*_):
        return {"found": False}
    with pytest.raises(ValueError, match="source"):
        await rehearse_eviction(DEMO_QUESTION, call_tool=missing)


@pytest.mark.asyncio
async def test_missing_johnson_body_withholds_the_updated_rehearsal():
    from app.eviction_demo import DEMO_QUESTION, rehearse_eviction
    async def source(name, args):
        if args.get("cluster_id") == "incourts-1106156996":
            return {"found": False}
        return {"found": True, "text": "Public test source.", **args}
    with pytest.raises(ValueError, match="source"):
        await rehearse_eviction(DEMO_QUESTION, call_tool=source)
