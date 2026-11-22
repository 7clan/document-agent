"""Diagnose genuine Gemini connectivity, declared tools, and app tool cycles.

No provider stubs. Prints only sanitized exception messages; no keys, request
headers, document contents, or full API response dumps.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from google import genai
from google.genai import types

from document_agent.agent import _system_prompt, ask, provider_error_diagnostic
from document_agent.db import connect
from document_agent.ingest import ingest_folder
from document_agent.tools import TOOL_SCHEMAS


def safe_exception(exc: Exception) -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    raw = str(getattr(exc, "message", "") or str(exc))
    if key:
        raw = raw.replace(key, "[REDACTED]")
    raw = re.sub(r"(?i)(?:key|token|secret|authorization)[=:][^\s,}]+",
                 "[REDACTED_FIELD]", raw)
    raw = re.sub(r"https?://\S+", "[URL]", raw)
    return " ".join(raw.split())[:700]


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("Missing GEMINI_API_KEY environment secret")
        return 2
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30000))
    def check(name: str, fn) -> bool:
        try:
            result = fn()
            print(f"{name}: OK " + str(result))
            return True
        except Exception as exc:  # noqa: BLE001 - API compatibility diagnostic
            print(f"{name}: FAILED ({type(exc).__name__}) "
                  f"{provider_error_diagnostic(exc)}: {safe_exception(exc)}")
            return False

    plain_ok = check("plain_generate", lambda: "text"
          if client.models.generate_content(model=model, contents="Say OK").text else "empty")

    def tools_initial() -> str:
        declarations = [
            types.FunctionDeclaration(
                name=t["name"], description=t["description"],
                parameters_json_schema=t["parameters"])
            for t in TOOL_SCHEMAS
        ]
        response = client.models.generate_content(
            model=model, contents="Which electrical cabinets must be brought into service?",
            config=types.GenerateContentConfig(
                system_instruction=_system_prompt(model),
                tools=[types.Tool(function_declarations=declarations)],
                temperature=0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        return ("calls=" + str(len(response.function_calls or [])) +
                " text_present=" + str(bool(response.text)))
    tools_ok = check("all_six_declared_tools_initial", tools_initial)
    app_ok = False

    with tempfile.TemporaryDirectory(prefix="gemini_real_probe_") as temp:
        corpus = Path(temp) / "corpus"
        subprocess.run([sys.executable, "scripts/create_release_corpus.py",
                        "--output", str(corpus)], check=True)
        db = connect(Path(temp) / "index.db")
        indexed = ingest_folder(db, str(corpus))
        print("real_ingested=" + str(indexed.get("total") or indexed.get("indexed")
                                     or indexed.get("success") or "see ready count"))
        print("ready_files=" + str(db.execute(
            "SELECT COUNT(*) FROM documents WHERE status='ready'").fetchone()[0]))
        try:
            a = ask(db, "Which electrical cabinets must be brought into service?",
                    provider="gemini", model=model)
            app_ok = True
            print("full_app_answer_status=" + a.verification_status)
            print("full_app_tool_call_count=" + str(len(a.tool_calls)))
            print("full_app_source_count=" + str(len(a.sources)))
            print("full_app_answer=" + a.text[:1000])
        except Exception as exc:  # noqa: BLE001
            print("full_app_FAILED: " + str(provider_error_diagnostic(exc)) +
                  " " + safe_exception(exc))
        finally:
            db.close()
    return 0 if plain_ok and tools_ok and app_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
