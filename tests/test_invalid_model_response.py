import json

import pytest

from app.research import research_spark
from app.spark_replay import tool_message


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['json', 'shape', 'tool'])
async def test_invalid_model_response_preserves_opened_source_without_retry(failure):
    calls = 0

    async def turn(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            return tool_message('case_get', {'cluster_id': 'synthetic'})
        if failure == 'json':
            raise json.JSONDecodeError('synthetic malformed response', '', 0)
        if failure == 'shape':
            return {'choices': ['not a choice object']}
        return tool_message('not_an_allowed_tool', {})

    async def source(*_):
        return {'found': True, 'text': 'A source body remains available.',
                'cluster_id': 'synthetic'}

    result = await research_spark('Read the opinion.', turn=turn, call_tool=source)
    assert result.completion_state == 'invalid_response'
    assert not result.complete
    assert result.found and len(result.steps) == 1
    assert result.steps[0]['result']['cluster_id'] == 'synthetic'
    assert 'Research incomplete.' in result.summary
    assert calls == 2
