import pytest

from app.research import quote_failures, research_spark
from app.spark_replay import replay_turn, text_message, tool_message


@pytest.mark.asyncio
async def test_user_suggested_quote_cannot_certify_a_court_holding():
    async def source(*_):
        return {'found': True, 'text': 'The court reverses because a defense was not heard.'}
    result = await research_spark(
        'Did the court hold "A jury demand stays all eviction orders"?',
        turn=replay_turn([
            tool_message('case_get', {'cluster_id': 'public-test'}),
            text_message('The court held "A jury demand stays all eviction orders".'),
        ]), call_tool=source,
    )
    assert not result.complete
    assert not result.quotes_ok
    assert 'A jury demand stays all eviction orders' not in result.summary


@pytest.mark.parametrize('quoted', [
    '"' + 'Unsupported legal holding. ' * 25 + '"',
    "'The judgment is affirmed.'",
    '‘The judgment is affirmed.’',
])
def test_fabricated_long_or_single_quoted_passages_are_checked(quoted):
    assert quote_failures(quoted, [{'text': 'The judgment is reversed.'}])


def test_quote_cannot_be_spliced_from_separate_source_fields():
    assert quote_failures('"We affirm the judgment."', [
        {'heading': 'We affirm', 'text': 'the judgment.'},
    ])


@pytest.mark.parametrize('answer', [
    "'The tenant's invented right is absolute.'",
    '‘The tenant’s invented right is absolute.’',
])
def test_single_quoted_invented_text_with_internal_apostrophe_is_checked(answer):
    assert quote_failures(answer, [{'text': 'The court reverses.'}])


@pytest.mark.parametrize('answer', [
    "'The tenant's defense was not heard.'",
    '‘The tenant’s defense was not heard.’',
])
def test_single_quoted_source_with_internal_apostrophe_still_passes(answer):
    assert quote_failures(answer, [{'text': 'The tenant’s defense was not heard.'}]) == []


@pytest.mark.parametrize('answer', [
    "'The tenants' invented rights are absolute.'",
    '‘The tenants’ invented rights are absolute.’',
    "'The tenants have\nan invented absolute right.'",
    '‘The tenants have\nan invented absolute right.’',
])
def test_possessive_or_multiline_single_quotation_cannot_hide_its_remainder(answer):
    assert quote_failures(answer, [{'text': 'The tenants have a procedural defense.'}])
