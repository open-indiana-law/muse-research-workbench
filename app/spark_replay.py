"""Recorded Spark completions for tests. Never calls Meta."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any


def tool_message(name: str, arguments: dict[str, Any], call_id: str = "c1") -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                }
            }
        ]
    }


def text_message(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def replay_turn(script: Sequence[dict[str, Any]]):
    remaining = list(script)

    async def turn(_messages: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        if not remaining:
            raise AssertionError("spark replay script exhausted")
        return remaining.pop(0)

    return turn
