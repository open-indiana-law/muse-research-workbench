"""Bounded, unmodified source text already retrieved during this request.

Reader identity is local to a result, not a citation or relevance attribution.
Rendering must use textContent; bodies are untrusted source data.
"""
MAX_BODY_CHARS = 60_000
MAX_TOTAL_CHARS = 180_000
OPEN_TOOLS = {'case_get', 'ic_get_section', 'ic_get_companion'}

def opened_sources(steps: list) -> list[dict]:
    sources=[]
    remaining=MAX_TOTAL_CHARS
    for index, step in enumerate(steps):
        data=step.result if isinstance(step.result,dict) else {}
        body=data.get('text') or data.get('body')
        if step.tool not in OPEN_TOOLS or data.get('found') is not True or not isinstance(body,str) or not body.strip():
            continue
        if remaining<=0:
            break
        text=body[:min(MAX_BODY_CHARS,remaining)]
        title=next((data[k] for k in ('case_name','heading','title','section_id','cluster_id','doc_id') if isinstance(data.get(k),str) and data[k]), 'Retrieved source')
        sources.append({'id':f'local-source-{index+1}','title':title[:300],
                        'tool':step.tool,'text':text,'truncated':len(text)<len(body),
                        'characters_total':len(body)})
        remaining-=len(text)
    return sources
