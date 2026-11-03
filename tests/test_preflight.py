from app.law_gateway import ALLOWED_TOOLS
from app.preflight import inspect_tools


def test_inspect_tools_complete():
    report = inspect_tools(list(ALLOWED_TOOLS))
    assert report["ok"] is True
    assert report["missing"] == []


def test_inspect_tools_flags_gap():
    report = inspect_tools(["ic_search"])
    assert report["ok"] is False
    assert "ic_get_section" in report["missing"]
