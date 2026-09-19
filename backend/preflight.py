"""Check provider configuration with one cheap call before running the app.

Reports which structured-output mode the provider actually accepted, so a
misconfigured endpoint is diagnosed in seconds rather than halfway through an
analysis.

Run: python preflight.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

from services.llm_client import MockClient, build_client  # noqa: E402

PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "echo": {"type": "string", "description": "Echo the word 'ready'."},
    },
}


def main() -> int:
    try:
        client = build_client()
    except ValueError as exc:
        print(f"FAIL  configuration error: {exc}")
        return 1

    print(f"client : {client.mode}")
    print(f"model  : {client.name}")

    if isinstance(client, MockClient):
        print(f"cases  : {', '.join(client.available_cases()) or 'none'}")
        print()
        print("Mock mode: no OPENAI_API_KEY set. The app is fully demonstrable on the")
        print("built-in cases; custom narratives will return HTTP 422.")
        return 0

    print(f"max_tokens : {client.max_tokens or 'provider default'}")
    print(f"extra_body : {client.extra_body or 'none'}")
    print()
    print("Probing structured-output support...")

    try:
        data = client.complete_json(
            stage="preflight",
            system="You are a connectivity probe. Reply with JSON only.",
            user="Set ok to true and echo to the word 'ready'.",
            schema=PROBE_SCHEMA,
            schema_name="preflight",
            case_id=None,
        )
    except Exception as exc:  # noqa: BLE001 - surface whatever the provider said
        print(f"\nFAIL  {type(exc).__name__}: {exc}")
        print("\nCommon causes:")
        print("  401 - bad or missing key")
        print("  402 - insufficient balance (DeepSeek returns this when out of credit)")
        print("  404 - wrong OPENAI_BASE_URL or unknown OPENAI_MODEL")
        return 1

    mode = client.active_json_mode
    print(f"  negotiated mode : {mode}")
    print(f"  response        : {data}")
    for note in client.notes:
        print(f"  note            : {note}")

    print()
    if mode == "strict":
        print("PASS  Strict JSON schema enforced by the provider. Best case.")
    else:
        print(f"PASS  Using '{mode}' mode. Output is NOT schema-enforced by the provider,")
        print("      so malformed fields degrade to UNKNOWN rather than failing loudly.")
        print("      This is expected on DeepSeek, Groq and most compatible endpoints.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
