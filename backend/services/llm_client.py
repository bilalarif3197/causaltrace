"""The single seam between CausalTrace and any LLM provider.

Every pipeline stage calls `ModelClient.complete_json(...)` and nothing else.
No service module imports a vendor SDK.

Two implementations ship today:
  OpenAIClient  any OpenAI-compatible endpoint (OpenAI, Groq, OpenRouter,
                Together, DeepSeek, local Ollama/llama.cpp, ...)
  MockClient    replays recorded per-stage responses from backend/fixtures

MockClient deliberately replays *stage-level model output*, not a finished
analysis. The real extraction, span-locating, verification and deterministic
scoring code all still execute in mock mode, so the offline demo exercises the
actual pipeline rather than a screenshot of one.

## Structured output portability

We want strict JSON schema enforcement, but most OpenAI-compatible providers
only implement part of that API. So `OpenAIClient` negotiates downward on first
use and then remembers what worked:

  strict       response_format=json_schema with strict=true  (OpenAI)
  json_object  response_format=json_object + schema in prompt (Groq, others)
  prompt       no response_format at all, schema in prompt     (everything)

Negotiation is driven by the provider actually rejecting a request (HTTP 400),
not by sniffing model names -- which go stale. Auth and rate-limit failures are
re-raised untouched, because degrading the output format would not fix them.

The pipeline stages read model output defensively (`.get(...)` with defaults),
so a weaker mode yields more UNKNOWNs rather than a crash. That is the correct
failure direction for this product.
"""

from __future__ import annotations

import json
import os
import re
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures"

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-2024-08-06")

#: Tried in order when OPENAI_JSON_MODE is "auto".
FALLBACK_CHAIN = ("strict", "json_object", "prompt")


class MockUnavailable(RuntimeError):
    """Raised when mock mode is asked for a case it has no recording of."""


def harden_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a JSON schema satisfy OpenAI strict structured-output rules.

    Strict mode requires every object to set additionalProperties=false and to
    list *all* of its properties in `required`. Optionality is expressed by
    unioning with "null" instead. Applying this recursively means the
    hand-written schemas in the service modules stay readable.
    """
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"].keys())
        out["properties"] = {k: harden_schema(v) for k, v in out["properties"].items()}
    if "items" in out:
        out["items"] = harden_schema(out["items"])
    return out


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object out of model text.

    Providers without real structured-output support wrap JSON in markdown
    fences or add a sentence of preamble. Raises json.JSONDecodeError if no
    object can be recovered, which the caller treats as "this mode did not
    work" rather than as a hard failure.
    """
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = _FENCE.search(text)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # Last resort: the outermost {...} span.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise json.JSONDecodeError("No JSON object found in model output", text or "", 0)


def schema_instruction(schema: dict[str, Any]) -> str:
    """Prompt text describing the required shape, for non-strict modes."""
    return (
        "\n\nRespond with a single JSON object and nothing else -- no prose, no markdown "
        "fences. It must conform exactly to this JSON Schema, including every key:\n"
        f"{json.dumps(harden_schema(schema), indent=2)}"
    )


class ModelClient(ABC):
    name: str = "abstract"
    mode: str = "mock"

    @abstractmethod
    def complete_json(
        self,
        *,
        stage: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        """Return a parsed JSON object conforming to `schema`."""


class OpenAIClient(ModelClient):
    mode = "live"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        json_mode: str = "auto",
        temperature: float = 0.0,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ):
        from openai import OpenAI  # imported lazily so mock mode needs no SDK

        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.model = model
        self.base_url = base_url
        self.name = f"{model} @ {base_url}" if base_url else model
        # Deterministic-as-possible: this is an assessment tool, not a writing aid.
        self.temperature = temperature
        # Some providers truncate long structured output at a low default cap;
        # the extraction stage is the one that hurts.
        self.max_tokens = max_tokens
        # Provider-specific passthrough, so vendor quirks live in config rather
        # than in this file. E.g. DeepSeek disables chain-of-thought with
        # {"thinking": {"type": "disabled"}} -- which also makes `temperature`
        # take effect, since DeepSeek silently ignores it in thinking mode.
        self.extra_body = extra_body or None

        if json_mode not in ("auto", *FALLBACK_CHAIN):
            raise ValueError(
                f"OPENAI_JSON_MODE must be 'auto' or one of {FALLBACK_CHAIN}, got {json_mode!r}"
            )
        self._candidates = FALLBACK_CHAIN if json_mode == "auto" else (json_mode,)
        #: Discovered on first success, then reused for every later call.
        self.active_json_mode: str | None = None
        #: Some models reject an explicit temperature; drop it if told so.
        self._send_temperature = True
        self.notes: list[str] = []
        # Stages can be dispatched concurrently. Negotiation mutates shared
        # state, so exactly one caller may probe; the rest wait for the answer
        # and then run in parallel on the fast path. Without this, six threads
        # would each independently probe and fight over `active_json_mode`.
        self._negotiate_lock = threading.Lock()

    # -- request construction -------------------------------------------------

    def _build(self, mode: str, system: str, user: str, schema: dict, schema_name: str) -> dict:
        kwargs: dict[str, Any] = {"model": self.model}
        if self._send_temperature:
            kwargs["temperature"] = self.temperature
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body

        if mode == "strict":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": harden_schema(schema)},
            }
        elif mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
            system = system + schema_instruction(schema)
        else:  # prompt
            system = system + schema_instruction(schema)

        kwargs["messages"] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return kwargs

    def _attempt(self, mode: str, system: str, user: str, schema: dict, schema_name: str) -> dict:
        response = self._client.chat.completions.create(
            **self._build(mode, system, user, schema, schema_name)
        )
        return extract_json(response.choices[0].message.content or "")

    # -- public API -----------------------------------------------------------

    def complete_json(
        self,
        *,
        stage: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        # Fast path: the mode is already known, so run without any locking.
        if self.active_json_mode is not None:
            return self._complete_with(
                self.active_json_mode, stage=stage, system=system, user=user,
                schema=schema, schema_name=schema_name,
            )

        # Negotiate under the lock so concurrent callers do not each probe.
        # Double-checked: another thread may have finished while we waited.
        with self._negotiate_lock:
            if self.active_json_mode is not None:
                mode = self.active_json_mode
            else:
                return self._negotiate(
                    stage=stage, system=system, user=user, schema=schema, schema_name=schema_name
                )
        return self._complete_with(
            mode, stage=stage, system=system, user=user, schema=schema, schema_name=schema_name
        )

    def _complete_with(
        self, mode: str, *, stage: str, system: str, user: str, schema: dict, schema_name: str
    ) -> dict[str, Any]:
        """One attempt in a known-good mode, with the transient-empty retry."""
        empty_retries = 1
        while True:
            try:
                return self._attempt(mode, system, user, schema, schema_name)
            except json.JSONDecodeError:
                if empty_retries:
                    empty_retries -= 1
                    continue
                raise RuntimeError(
                    f"Provider returned unparseable JSON twice at stage '{stage}' in "
                    f"'{mode}' mode."
                ) from None

    def _negotiate(
        self, *, stage: str, system: str, user: str, schema: dict, schema_name: str
    ) -> dict[str, Any]:
        from openai import BadRequestError, NotFoundError, UnprocessableEntityError

        # Unsupported-parameter errors; anything else (401/429/5xx) propagates.
        negotiable = (BadRequestError, NotFoundError, UnprocessableEntityError)

        candidates = self._candidates
        failures: list[str] = []

        for mode in candidates:
            # Attempt budget per mode. Extra attempts are spent only on two
            # recoverable conditions: dropping an unsupported `temperature`,
            # and one retry for a transiently empty response.
            budget = 3
            empty_retries = 1
            while budget > 0:
                budget -= 1
                try:
                    data = self._attempt(mode, system, user, schema, schema_name)
                except negotiable as exc:
                    message = str(exc)
                    if self._send_temperature and "temperature" in message.lower():
                        # Reasoning-style models reject a non-default temperature.
                        self._send_temperature = False
                        self.notes.append("provider rejected `temperature`; omitting it")
                        continue
                    failures.append(f"{mode}: {message[:160]}")
                    break
                except json.JSONDecodeError as exc:
                    # An empty or malformed body is usually transient, not a
                    # capability signal -- DeepSeek documents occasional empty
                    # content in JSON mode. Retry the same mode once before
                    # concluding the provider cannot honour this format.
                    if empty_retries:
                        empty_retries -= 1
                        continue
                    failures.append(f"{mode}: model did not return parseable JSON ({exc.msg})")
                    break
                else:
                    if self.active_json_mode != mode:
                        self.active_json_mode = mode
                        if mode != "strict":
                            self.notes.append(
                                f"provider does not support strict JSON schema; "
                                f"using '{mode}' mode (output is not schema-enforced)"
                            )
                    return data

        raise RuntimeError(
            "Could not obtain structured JSON from the provider at stage "
            f"'{stage}'. Attempts:\n  " + "\n  ".join(failures) +
            "\nSet OPENAI_JSON_MODE=prompt to force the most permissive mode."
        )


class MockClient(ModelClient):
    mode = "mock"
    name = "mock-fixtures"

    def __init__(self, fixture_root: Path = FIXTURE_ROOT):
        self.fixture_root = fixture_root

    def available_cases(self) -> list[str]:
        if not self.fixture_root.is_dir():
            return []
        return sorted(p.name for p in self.fixture_root.iterdir() if p.is_dir())

    def complete_json(
        self,
        *,
        stage: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        if not case_id:
            raise MockUnavailable(
                "Mock mode can only replay the built-in example cases. "
                "Set OPENAI_API_KEY to analyze a custom narrative."
            )
        path = self.fixture_root / case_id / f"{stage}.json"
        if not path.is_file():
            raise MockUnavailable(
                f"No recorded '{stage}' response for case '{case_id}'. "
                f"Available cases: {', '.join(self.available_cases()) or 'none'}. "
                "Set OPENAI_API_KEY to analyze this narrative for real."
            )
        return json.loads(path.read_text())


def build_client() -> ModelClient:
    """Pick a client from the environment. Falls back to mock, loudly.

    Env:
      OPENAI_API_KEY     required for live mode
      OPENAI_BASE_URL    any OpenAI-compatible endpoint
      OPENAI_MODEL       model id
      OPENAI_JSON_MODE   auto (default) | strict | json_object | prompt
      OPENAI_TEMPERATURE
      OPENAI_MAX_TOKENS  guards against truncated structured output
      OPENAI_EXTRA_BODY  JSON object merged into every request, for provider
                         quirks (e.g. '{"thinking": {"type": "disabled"}}')
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return MockClient()

    raw_extra = os.environ.get("OPENAI_EXTRA_BODY", "").strip()
    try:
        extra_body = json.loads(raw_extra) if raw_extra else None
    except json.JSONDecodeError as exc:
        raise ValueError(f"OPENAI_EXTRA_BODY is not valid JSON: {exc}") from exc
    if extra_body is not None and not isinstance(extra_body, dict):
        raise ValueError("OPENAI_EXTRA_BODY must be a JSON object.")

    max_tokens = os.environ.get("OPENAI_MAX_TOKENS", "").strip()

    return OpenAIClient(
        api_key=api_key,
        model=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        base_url=os.environ.get("OPENAI_BASE_URL", "").strip() or None,
        json_mode=os.environ.get("OPENAI_JSON_MODE", "auto").strip() or "auto",
        temperature=float(os.environ.get("OPENAI_TEMPERATURE", "0") or 0),
        max_tokens=int(max_tokens) if max_tokens else None,
        extra_body=extra_body,
    )
