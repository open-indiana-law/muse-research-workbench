from app.muse_params import (
    KEYWORDS,
    LANGUAGE_BIAS,
    REASONING_EFFORT,
    SPARK_MODEL,
    VOICE_MODE,
    spark_request_body,
    voice_handshake,
    voice_request_json,
)


def test_spark_body_matches_leverage_sheet():
    body = spark_request_body([{"role": "user", "content": "x"}], tools=[{"type": "function"}])
    assert body["model"] == SPARK_MODEL
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is False
    assert body["reasoning_effort"] == REASONING_EFFORT == "low"
    assert body["max_tokens"] == 4000
    assert body["prompt_cache_key"] == "open-indiana-research-v1"


def test_voice_builders_bias_indiana_terms():
    request = voice_request_json()
    handshake = voice_handshake(access_token="test-key")
    assert request["mode"] == VOICE_MODE == "PUSH_TO_TALK"
    assert request["languageBias"] == LANGUAGE_BIAS == ["English"]
    assert "Indiana Code" in request["keywords"]
    assert "Horton" in KEYWORDS
    assert handshake["authorization"]["accessToken"] == "Bearer test-key"
    assert handshake["keywords"] == request["keywords"]
