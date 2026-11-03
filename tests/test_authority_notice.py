import pytest
from app.research import research_spark
from app.research_state import authority_notice_conflict
from app.law_gateway import TraceStep
from tests.test_research_state import call, answer
NOTICE='MEMORANDUM DECISION. This decision shall not be regarded as precedent or cited before any court except for res judicata, collateral estoppel, or law of the case.'

def test_conflict_checks_opened_notice_not_case_year_or_classifier():
    steps=[TraceStep('case_get',{}, {'found':True,'text':NOTICE})]
    assert authority_notice_conflict('The decision is persuasive only.',steps)
    assert not authority_notice_conflict('It is not persuasive authority under the supplied notice.',steps)
    assert not authority_notice_conflict('The notice restricts court citation to specified exceptions.',steps)
    assert not authority_notice_conflict('The decision is persuasive only.',[TraceStep('case_get',{}, {'found':True,'text':'This decision is not binding precedent but may be cited for persuasive value.'})])

@pytest.mark.asyncio
async def test_model_reconsiders_source_notice_conflict_without_planted_answer():
    first='The decision is persuasive only.';seen=[]
    turns=iter([call('case_get',{'cluster_id':'public-case'}),answer(first),answer('The opened notice restricts citation to specified exceptions.')])
    async def turn(messages):seen.append(messages);return next(turns)
    async def tool(name,args):return {'found':True,'cluster_id':'public-case','text':NOTICE}
    r=await research_spark('Find and open an appellate opinion.',turn=turn,call_tool=tool,source_call_limit=1)
    assert r.complete and len(seen)==3
    assert any(m['role']=='assistant' and m.get('content')==first for m in seen[-1])
    assert 'res judicata' not in seen[-1][-1]['content']

@pytest.mark.asyncio
async def test_repeated_notice_conflict_is_incomplete():
    turns=iter([call('case_get',{'cluster_id':'public-case'}),answer('The decision is persuasive only.'),answer('The decision is persuasive only.')])
    async def turn(messages):return next(turns)
    async def tool(name,args):return {'found':True,'cluster_id':'public-case','text':NOTICE}
    r=await research_spark('Find an opinion.',turn=turn,call_tool=tool)
    assert not r.complete and r.completion_state=='authority_notice_conflict'
