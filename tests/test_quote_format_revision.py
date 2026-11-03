import pytest
from app.research import research_spark
from tests.test_research_state import call, answer

@pytest.mark.asyncio
async def test_unverified_blockquote_gets_one_source_preserving_revision():
    seen=[]
    turns=iter([call('ic_get_section',{'section_id':'public-test'}),
                answer('> A useful explanation, written as a paraphrase.'),
                answer('A useful explanation, written as a paraphrase.')])
    async def turn(messages):
        seen.append(messages)
        return next(turns)
    async def source(name,args):
        return {'found':True,'section_id':'public-test','text':'A public statutory body supports inspection.'}
    result=await research_spark('Explain the statutory text.',turn=turn,call_tool=source,source_call_limit=1)
    assert result.complete and result.quotes_ok
    assert len(result.steps)==1
    assert len(result.research_state['attempted_finals'])==2
    assert result.research_state['attempted_finals'][0]['text'].startswith('> ')
    assert any('blockquote' in m.get('content','').lower() for m in seen[-1] if m['role']=='developer')

@pytest.mark.asyncio
async def test_repeated_unverified_blockquote_still_fails_closed():
    turns=iter([call('ic_get_section',{'section_id':'public-test'}),
                answer('> Unsupported paraphrase.'),answer('> Still not source wording.')])
    async def turn(messages):return next(turns)
    async def source(name,args):return {'found':True,'section_id':'public-test','text':'Public statutory body.'}
    result=await research_spark('Explain the statutory text.',turn=turn,call_tool=source,source_call_limit=1)
    assert not result.complete and not result.quotes_ok
    assert result.completion_state=='quote_failed'
    assert len(result.research_state['attempted_finals'])==2

@pytest.mark.asyncio
async def test_format_revision_cannot_dispatch_another_source_call():
    calls=[]
    turns=iter([call('ic_get_section',{'section_id':'public-test'}),
                answer('> An unverified explanatory blockquote.'),
                call('ic_get_section',{'section_id':'another-source'})])
    async def turn(messages):return next(turns)
    async def source(name,args):
        calls.append((name,args))
        return {'found':True,'section_id':'public-test','text':'Public statutory body.'}
    result=await research_spark('Explain the statutory text.',turn=turn,call_tool=source,source_call_limit=3)
    assert not result.complete and result.completion_state=='model_incomplete'
    assert len(calls)==1 and len(result.steps)==1
