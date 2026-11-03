"""Pre-record checks. No Muse call."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.law_gateway import ALLOWED_TOOLS, DEFAULT_MCP_URL, live_list_tools
from app.muse_client import spark_ready
from app.research import classify, research_fixture

GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden.json"


def inspect_tools(names: list[str]) -> dict[str, Any]:
    missing = [name for name in ALLOWED_TOOLS if name not in names]
    extra = [name for name in names if name not in ALLOWED_TOOLS]
    return {
        "ok": not missing,
        "tool_count": len(names),
        "missing": missing,
        "extra": extra,
        "spark_ready": spark_ready(),
    }


async def preflight(url: str = DEFAULT_MCP_URL) -> dict[str, Any]:
    names = await live_list_tools(url)
    report = inspect_tools(names)
    report["mcp_url"] = url
    report["keys_in_response"] = False
    return report


async def eval_golden(url: str = DEFAULT_MCP_URL) -> dict[str, Any]:
    items = json.loads(GOLDEN.read_text())
    rows = []
    for item in items:
        result = await research_fixture(item["question"], url=url)
        rows.append(
            {
                "id": item["id"],
                "planner": result.planner,
                "expect_planner": item["planner"],
                "found": result.found,
                "expect_found": item["expect_found"],
                "quotes_ok": result.quotes_ok,
                "catch": bool(result.catch),
                "ok": (
                    result.planner == item["planner"]
                    and result.found is item["expect_found"]
                    and result.quotes_ok
                    and classify(item["question"]) == item["planner"]
                ),
            }
        )
    return {
        "ok": all(row["ok"] for row in rows),
        "rows": rows,
        "spark_ready": spark_ready(),
        "keys_in_response": False,
    }
