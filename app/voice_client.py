"""Muse Voice Transcribe. Live calls stay closed until MODEL_API_KEY is set."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.muse_client import CreditNotReady, require_spark_key
from app.muse_params import DEFAULT_BASE_URL, voice_request_json


def _encoding_for(content_type: str | None, filename: str) -> str:
    lowered = f"{content_type or ''} {filename}".lower()
    if "wav" in lowered:
        return "WAV"
    if "webm" in lowered:
        return "WEBM"
    if "mpeg" in lowered or "mp3" in lowered:
        return "MP3"
    return "WAV"


async def transcribe_file(
    audio: bytes,
    *,
    filename: str = "clip.wav",
    content_type: str = "audio/wav",
    base_url: str | None = None,
) -> dict[str, Any]:
    require_spark_key()
    raise CreditNotReady(
        "Voice is closed for this typed demo until separate duration/pricing accounting is qualified."
    )


def transcript_text(payload: dict[str, Any]) -> str:
    if payload.get("transcript"):
        return str(payload["transcript"]).strip()
    turns = payload.get("turns") or []
    parts = [str(turn.get("transcript") or "").strip() for turn in turns]
    return " ".join(part for part in parts if part).strip()
