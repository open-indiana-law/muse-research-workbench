import pytest
from app.research import research_spark
from tests.test_research_state import call, answer

@pytest.mark.asyncio
async def test_one_style_revision_preserves_sources_and_original_answer():
    long=' '.join(['word']*11);seen=[]
    turns=iter([call('ic_get_section',{'section_id':'public-test'}),answer(long),answer('A concise supported note.')])
    async def turn(messages):seen.append(messages);return next(turns)
    async def tool(name,args):return {'found':True,'section_id':'public-test','text':'Public source'}
    r=await research_spark('Find statutory text. Write a 4–6 word note.',turn=turn,call_tool=tool,source_call_limit=1)
    assert r.complete and len(r.steps)==1
    assert any(m.get('content')==long and m['role']=='assistant' for m in seen[-1])
    assert len(r.research_state['attempted_finals'])==2

@pytest.mark.asyncio
async def test_repeated_length_failure_stops_and_retains_raw_attempts():
    long=' '.join(['word']*11)
    turns=iter([call('ic_get_section',{'section_id':'public-test'}),answer(long),answer(long)])
    async def turn(messages):return next(turns)
    async def tool(name,args):return {'found':True,'section_id':'public-test','text':'Public source'}
    r=await research_spark('Find statutory text. Write a 4-6 word note.',turn=turn,call_tool=tool)
    assert not r.complete and r.completion_state=='answer_length'
    assert len(r.research_state['attempted_finals'])==2


def test_note_body_count_excludes_a_standalone_heading_but_keeps_sources():
    from app.research import note_word_count
    assert note_word_count('Research Note — Test title\n\nFour words plus sources.')==4
    assert note_word_count('Research Note — Test title is itself the whole answer.')==10

@pytest.mark.asyncio
async def test_no_evidence_attempt_remains_inspectable_without_displaying_it():
    async def turn(messages):return answer('Unsupported conclusion with no opened source.')
    async def tool(name,args):raise AssertionError('No retrieval requested')
    r=await research_spark('Research this question.',turn=turn,call_tool=tool)
    assert not r.complete
    assert r.research_state['attempted_finals'][0]['text']=='Unsupported conclusion with no opened source.'
    assert 'Unsupported conclusion' not in r.summary

@pytest.mark.asyncio
async def test_quote_failure_keeps_the_primary_research_issue():
    turns=iter([call('ic_get_section',{'section_id':'public-test'}),answer('The source says "a fabricated quoted proposition".')])
    async def turn(messages):return next(turns)
    async def tool(name,args):return {'found':True,'section_id':'public-test','text':'Public statutory text.'}
    r=await research_spark('Read statutory text and an appellate opinion.',turn=turn,call_tool=tool,source_call_limit=1)
    assert r.completion_state=='quote_failed'
    assert set(r.completion_issues)=={'missing_required_sources','quote_failed'}

@pytest.mark.asyncio
async def test_equivalent_source_warning_is_not_appended_twice():
    warning='Unofficial copy — verify at official source iga.in.gov — not legal advice — not a citator.'
    turns=iter([call('ic_get_section',{'section_id':'public-test'}),answer('A supported note. '+warning)])
    async def turn(messages):return next(turns)
    async def tool(name,args):return {'found':True,'section_id':'public-test','text':'Public statutory text.'}
    r=await research_spark('Read statutory text.',turn=turn,call_tool=tool)
    assert r.summary.lower().count('not legal advice')==1
