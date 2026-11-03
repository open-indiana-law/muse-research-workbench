"""Documented Muse parameters for this demo. No live call lives here."""

from __future__ import annotations

from typing import Any

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
SPARK_MODEL = "muse-spark-1.3"
VOICE_MODEL = "muse-voice-transcribe-1.0"
REASONING_EFFORT = "low"
# Reasoning and visible answer share this cap. A recorded2000-token limit
# spent1770on reasoning and truncated the note; retain room for both.
MAX_OUTPUT_TOKENS = 4000
PROMPT_CACHE_KEY = "open-indiana-research-v1"
VOICE_MODE = "PUSH_TO_TALK"
LANGUAGE_BIAS = ["English"]
KEYWORDS = [
    "Indiana Code",
    "IC",
    "income withholding",
    "income payor",
    "Horton",
    "Jerry Horton",
    "snapshot",
    "unofficial",
    "Court of Appeals",
    "memorandum",
]

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "indiana_research_answer",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "catch": {"type": "string"},
                "disclaimer": {"type": "string"},
            },
            "required": ["summary", "catch", "disclaimer"],
            "additionalProperties": False,
        },
    },
}


def spark_request_body(messages: list[dict[str, Any]], *, tools: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": SPARK_MODEL,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "reasoning_effort": REASONING_EFFORT,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "prompt_cache_key": PROMPT_CACHE_KEY,
    }


def voice_request_json(*, audio_encoding: str = "WAV") -> dict[str, Any]:
    return {
        "model": VOICE_MODEL,
        "audioEncoding": audio_encoding,
        "mode": VOICE_MODE,
        "languageBias": list(LANGUAGE_BIAS),
        "keywords": list(KEYWORDS),
    }


def voice_handshake(*, access_token: str) -> dict[str, Any]:
    return {
        "authorization": {"accessToken": f"Bearer {access_token}"},
        "audioEncoding": "PCM_24KHZ",
        "model": VOICE_MODEL,
        "mode": VOICE_MODE,
        "partialMode": "CUMULATIVE",
        "emitAudioProgress": False,
        "languageBias": list(LANGUAGE_BIAS),
        "keywords": list(KEYWORDS),
    }
