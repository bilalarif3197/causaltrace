"""The single seam between CausalTrace and any LLM provider.

Every pipeline stage calls `ModelClient.complete_json(...)` and nothing else.
Swapping providers means adding one subclass here; no service module imports a
vendor SDK directly.

Two implementations ship today:
  OpenAIClient  structured outputs via strict JSON schema
  MockClient    replays recorded per-stage responses from backend/fixtures

MockClient deliberately replays *stage-level model output*, not a finished
analysis. The real extraction, span-locating, verification and deterministic
scoring code all still execute in mock mode, so the offline demo exercises the
actual pipeline rather than a screenshot of one.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures"

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-2024-08-06")


class MockUnavailable(RuntimeError):
    """Raised when mock mode is asked for a case it has no recording of."""


def harden_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a JSON schema satisfy OpenAI strict structured-output rules.

    Strict mode requires every object to set additionalProperties=false and to
    list *all* of its properties in `required`. Optionality is expressed by
    unioning with "null" instead. Applying this recursively means the
    hand-written schemas below stay readable.
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

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, temperature: float = 0.0):
        from openai import OpenAI  # imported lazily so mock mode needs no SDK

        self._client = OpenAI(api_key=api_key)
        self.model = model
        self.name = model
        # Deterministic-as-possible: this is an assessment tool, not a writing aid.
        self.temperature = temperature

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
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": harden_schema(schema),
                },
            },
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)


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
    """Pick a client from the environment. Falls back to mock, loudly."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        return OpenAIClient(api_key=api_key)
    return MockClient()
