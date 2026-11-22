"""One genuine, bounded Gemini authentication request before browser/video setup."""
from __future__ import annotations

import os
import sys

from google import genai
from google.genai import types

from document_agent.agent import provider_error_diagnostic


def main() -> int:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    if not key or not model:
        print("Gemini preflight blocked: API key or model ID not configured.",
              file=sys.stderr)
        return 2
    try:
        client = genai.Client(
            api_key=key, http_options=types.HttpOptions(timeout=12000))
        result = client.models.generate_content(
            model=model, contents="Reply with OK.")
    except Exception as exc:  # noqa: BLE001 - never print arbitrary provider exceptions
        diagnostic = provider_error_diagnostic(exc)
        print("Gemini preflight failed: HTTP status " +
              str(diagnostic["http_status"]) +
              ", provider code " + str(diagnostic["code"]) +
              ". Check that the Google AI Studio key is active and valid for the model.",
              file=sys.stderr)
        return 1
    if not (result.text or "").strip():
        print("Gemini preflight returned no usable text.", file=sys.stderr)
        return 1
    print("Gemini preflight passed: a real authenticated model response was received.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
