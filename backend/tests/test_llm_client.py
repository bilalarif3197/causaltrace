"""Tests for provider negotiation and tolerant JSON parsing.

The fallback chain exists so CausalTrace runs on free OpenAI-compatible
endpoints (Groq, OpenRouter, Ollama, ...) that implement only part of the
structured-output API. Two properties matter most:

  * degrading is driven by the provider rejecting the request, and an auth or
    rate-limit failure must NOT be mistaken for "unsupported format";
  * when we do degrade, the user is told, because the output is then no longer
    schema-enforced.
"""

from __future__ import annotations

import json

import httpx
import pytest
from openai import AuthenticationError, BadRequestError, RateLimitError

from services.llm_client import (
    FALLBACK_CHAIN,
    MockClient,
    MockUnavailable,
    OpenAIClient,
    extract_json,
    harden_schema,
    schema_instruction,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": {"type": "string"}},
        "note": {"type": ["string", "null"]},
    },
}
PAYLOAD = {"items": ["a"], "note": None}


def _api_error(cls, status: int, message: str):
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    return cls(message, response=httpx.Response(status, request=request), body=None)


class FakeCompletions:
    """Scripted `chat.completions.create`. Each script entry is either an
    exception to raise or a string to return as message content."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0) if self.script else PAYLOAD
        if isinstance(item, Exception):
            raise item
        content = item if isinstance(item, str) else json.dumps(item)
        message = type("M", (), {"content": content})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"choices": [choice]})()


def make_client(script, **kwargs) -> tuple[OpenAIClient, FakeCompletions]:
    client = OpenAIClient(api_key="sk-test", model="test-model", **kwargs)
    fake = FakeCompletions(script)
    client._client = type("X", (), {"chat": type("Y", (), {"completions": fake})()})()
    return client, fake


def call(client):
    return client.complete_json(
        stage="extraction", system="sys", user="usr", schema=SCHEMA, schema_name="s", case_id=None
    )


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def test_extract_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_from_markdown_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_with_prose_preamble():
    assert extract_json('Here is the result:\n{"a": 1}\nHope that helps.') == {"a": 1}


def test_extract_nested_braces_survive():
    assert extract_json('text {"a": {"b": [1,2]}} tail') == {"a": {"b": [1, 2]}}


def test_extract_raises_without_json():
    with pytest.raises(json.JSONDecodeError):
        extract_json("no object here at all")
    with pytest.raises(json.JSONDecodeError):
        extract_json("")


# ---------------------------------------------------------------------------
# Schema hardening
# ---------------------------------------------------------------------------


def test_harden_schema_requires_all_keys_and_forbids_extras():
    hardened = harden_schema(SCHEMA)
    assert hardened["additionalProperties"] is False
    assert set(hardened["required"]) == {"items", "note"}


def test_harden_schema_recurses_into_nested_objects():
    nested = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {"type": "object", "properties": {"x": {"type": "string"}}},
            }
        },
    }
    inner = harden_schema(nested)["properties"]["rows"]["items"]
    assert inner["additionalProperties"] is False
    assert inner["required"] == ["x"]


def test_schema_instruction_embeds_the_schema():
    text = schema_instruction(SCHEMA)
    assert "JSON Schema" in text
    assert '"items"' in text


# ---------------------------------------------------------------------------
# Negotiation
# ---------------------------------------------------------------------------


def test_strict_is_tried_first_and_remembered():
    client, fake = make_client([PAYLOAD, PAYLOAD])
    assert call(client) == PAYLOAD
    assert client.active_json_mode == "strict"
    assert fake.calls[0]["response_format"]["type"] == "json_schema"
    assert fake.calls[0]["response_format"]["json_schema"]["strict"] is True
    assert client.notes == []

    # Second call must not re-probe the chain.
    call(client)
    assert len(fake.calls) == 2
    assert fake.calls[1]["response_format"]["type"] == "json_schema"


def test_falls_back_to_json_object_when_strict_rejected():
    client, fake = make_client(
        [_api_error(BadRequestError, 400, "response_format.json_schema is not supported"), PAYLOAD]
    )
    assert call(client) == PAYLOAD
    assert client.active_json_mode == "json_object"
    assert fake.calls[1]["response_format"] == {"type": "json_object"}
    # The schema must move into the prompt once it is no longer enforced.
    assert "JSON Schema" in fake.calls[1]["messages"][0]["content"]
    assert any("not schema-enforced" in n for n in client.notes)


def test_falls_back_to_prompt_when_response_format_unsupported():
    client, fake = make_client(
        [
            _api_error(BadRequestError, 400, "json_schema unsupported"),
            _api_error(BadRequestError, 400, "response_format unsupported"),
            PAYLOAD,
        ]
    )
    assert call(client) == PAYLOAD
    assert client.active_json_mode == "prompt"
    assert "response_format" not in fake.calls[2]
    assert "JSON Schema" in fake.calls[2]["messages"][0]["content"]


def test_transient_empty_response_retries_same_mode():
    """DeepSeek documents occasional empty content in JSON mode. That is a
    transient fault, so it must not be read as "format unsupported"."""
    client, fake = make_client(["", PAYLOAD])
    assert call(client) == PAYLOAD
    assert client.active_json_mode == "strict"
    assert len(fake.calls) == 2
    assert fake.calls[1]["response_format"]["type"] == "json_schema"
    assert client.notes == []


def test_persistently_unparseable_output_degrades_to_next_mode():
    """A provider that accepts json_schema but ignores it still gets caught --
    after the transient retry is exhausted."""
    client, fake = make_client(["not json", "still not json", PAYLOAD])
    assert call(client) == PAYLOAD
    assert client.active_json_mode == "json_object"
    assert len(fake.calls) == 3


def test_all_modes_failing_raises_with_diagnostics():
    client, _ = make_client([_api_error(BadRequestError, 400, f"nope {m}") for m in FALLBACK_CHAIN])
    with pytest.raises(RuntimeError) as exc:
        call(client)
    message = str(exc.value)
    assert "extraction" in message
    assert "OPENAI_JSON_MODE=prompt" in message
    for mode in FALLBACK_CHAIN:
        assert mode in message


@pytest.mark.parametrize(
    "error",
    [
        _api_error(AuthenticationError, 401, "invalid api key"),
        _api_error(RateLimitError, 429, "rate limit exceeded"),
    ],
)
def test_auth_and_rate_limit_errors_propagate_without_fallback(error):
    """Degrading the output format cannot fix a bad key or a quota wall, so
    these must surface immediately rather than burning three retries."""
    client, fake = make_client([error, PAYLOAD])
    with pytest.raises(type(error)):
        call(client)
    assert len(fake.calls) == 1
    assert client.active_json_mode is None


def test_temperature_rejection_retries_without_it():
    client, fake = make_client(
        [_api_error(BadRequestError, 400, "Unsupported value: 'temperature' does not support 0"), PAYLOAD]
    )
    assert call(client) == PAYLOAD
    assert "temperature" in fake.calls[0]
    assert "temperature" not in fake.calls[1]
    # Still strict: only the temperature was at fault, not the format.
    assert client.active_json_mode == "strict"
    assert any("temperature" in n for n in client.notes)


def test_explicit_mode_skips_negotiation():
    client, fake = make_client([PAYLOAD], json_mode="prompt")
    call(client)
    assert client.active_json_mode == "prompt"
    assert "response_format" not in fake.calls[0]


def test_invalid_mode_rejected_at_construction():
    with pytest.raises(ValueError, match="OPENAI_JSON_MODE"):
        OpenAIClient(api_key="sk-test", json_mode="wishful")


def test_base_url_is_reflected_in_client_name():
    client, _ = make_client([PAYLOAD], base_url="https://api.groq.com/openai/v1")
    assert "groq" in client.name
    assert client.mode == "live"


def test_max_tokens_and_extra_body_are_passed_through():
    """`extra_body` is how provider quirks stay in config instead of in code --
    e.g. DeepSeek's {"thinking": {"type": "disabled"}}."""
    client, fake = make_client(
        [PAYLOAD], max_tokens=8192, extra_body={"thinking": {"type": "disabled"}}
    )
    call(client)
    assert fake.calls[0]["max_tokens"] == 8192
    assert fake.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_max_tokens_and_extra_body_omitted_when_unset():
    client, fake = make_client([PAYLOAD])
    call(client)
    assert "max_tokens" not in fake.calls[0]
    assert "extra_body" not in fake.calls[0]


def test_build_client_rejects_malformed_extra_body(monkeypatch):
    from services.llm_client import build_client

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_EXTRA_BODY", "{not json}")
    with pytest.raises(ValueError, match="OPENAI_EXTRA_BODY"):
        build_client()

    monkeypatch.setenv("OPENAI_EXTRA_BODY", '["a", "list"]')
    with pytest.raises(ValueError, match="must be a JSON object"):
        build_client()


def test_build_client_returns_mock_without_key(monkeypatch):
    from services.llm_client import build_client

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert isinstance(build_client(), MockClient)


def test_build_client_wires_deepseek_style_config(monkeypatch):
    from services.llm_client import build_client

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("OPENAI_MODEL", "deepseek-flash")
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "8192")
    monkeypatch.setenv("OPENAI_EXTRA_BODY", '{"thinking": {"type": "disabled"}}')

    client = build_client()
    assert isinstance(client, OpenAIClient)
    assert client.model == "deepseek-flash"
    assert client.base_url == "https://api.deepseek.com"
    assert client.max_tokens == 8192
    assert client.extra_body == {"thinking": {"type": "disabled"}}
    # DeepSeek does not implement json_schema, so negotiation should land on
    # json_object -- but only after actually being told no.
    assert client.active_json_mode is None
    assert client._candidates == FALLBACK_CHAIN


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------


def test_mock_requires_a_known_case():
    mock = MockClient()
    with pytest.raises(MockUnavailable, match="built-in example cases"):
        mock.complete_json(stage="extraction", system="", user="", schema={}, schema_name="s")


def test_mock_reports_available_cases_on_miss():
    mock = MockClient()
    with pytest.raises(MockUnavailable) as exc:
        mock.complete_json(
            stage="extraction", system="", user="", schema={}, schema_name="s", case_id="nope"
        )
    assert "dili-ambiguous-001" in str(exc.value)


def test_mock_replays_recorded_stage():
    data = MockClient().complete_json(
        stage="naranjo", system="", user="", schema={}, schema_name="s",
        case_id="dili-ambiguous-001",
    )
    assert len(data["items"]) == 10
