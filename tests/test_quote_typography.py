import pytest

from app.research import quote_failures


@pytest.mark.parametrize(('source', 'answer'), [
    ('We reverse the small claims court’s judgment.', '“We reverse the small claims court\'s judgment.”'),
    ("We reverse the small claims court's judgment.", '“We reverse the small claims court’s judgment.”'),
])
def test_quote_check_accepts_straight_or_curly_apostrophe_without_changing_words(source, answer):
    assert quote_failures(answer, [{'text': source}]) == []


def test_quote_check_still_rejects_a_changed_disposition():
    failures = quote_failures('“We affirm the small claims court\'s judgment.”', [
        {'text': 'We reverse the small claims court’s judgment.'},
    ])
    assert failures == ["We affirm the small claims court's judgment."]

@pytest.mark.parametrize('marks', [('"', '"'), ('“', '”'), ("'", "'"), ('‘', '’')])
def test_markdown_blockquote_accepts_matching_outer_quote_markers(marks):
    passage = "allow a defendant to dispute a plaintiff's claim for immediate possession"
    answer = '> ' + marks[0] + passage + marks[1]
    assert quote_failures(answer, [{'text': 'A hearing to ' + passage + ' is required.'}]) == []


def test_quoted_blockquote_still_rejects_a_changed_word():
    assert quote_failures('> "allow a defendant to win immediately"', [
        {'text': 'allow a defendant to dispute immediate possession'},
    ])
