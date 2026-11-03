from types import SimpleNamespace
from app.source_reader import opened_sources, MAX_BODY_CHARS, MAX_TOTAL_CHARS

def step(tool, **result):
    return SimpleNamespace(tool=tool, result=result)

def test_reader_uses_opened_bodies_only_and_keeps_raw_text():
    text='<script>not executable</script>\nActual source'
    result=opened_sources([step('case_search',found=True,text='lead'),
        step('case_get',found=False,text='missing'),
        step('case_get',found=True,cluster_id='x',case_name='Case',text=text)])
    assert len(result)==1
    assert result[0]['text']==text
    assert result[0]['title']=='Case'
    assert result[0]['truncated'] is False

def test_reader_has_per_body_and_aggregate_bounds():
    result=opened_sources([step('ic_get_section',found=True,section_id=str(i),text='a'*(MAX_BODY_CHARS+1)) for i in range(20)])
    assert sum(len(s['text']) for s in result)<=MAX_TOTAL_CHARS
    assert all(len(s['text'])<=MAX_BODY_CHARS and s['truncated'] for s in result)
    assert len({s['id'] for s in result})==len(result)
    assert all(s['characters_total']==MAX_BODY_CHARS+1 for s in result)

def test_reader_missing_or_non_string_body_is_not_a_source():
    assert opened_sources([step('case_get',found=True,text={'bad':'body'}),step('case_get',found=True,text='  ')])==[]
