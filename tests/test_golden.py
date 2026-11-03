import json
from pathlib import Path

from app.research import classify

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "golden.json").read_text())


def test_golden_questions_classify():
    for item in GOLDEN:
        assert classify(item["question"]) == item["planner"], item["id"]
