# Document Intelligence Agent — developer instructions

This is an independent document-analysis project. Read `README.md` and `PROMPT_FOR_CODEX.md` before editing.

Make small, testable changes. Run `python -m pytest -q` and `ruff check src tests app.py scripts` before merging. Do not claim tests ran unless they actually did.
Never commit `.env`, API secrets, indexed databases, uploads, or confidential source documents. Preserve read-only LLM tools and source citations. Do not allow the model to execute arbitrary code, SQL, or shell commands.
Maintain provider portability, deterministic financial calculations, and explicit uncertainty when extraction fails. Hybrid keyword + local semantic retrieval is implemented as an opt-in mode; the base keyword search remains available. Do not claim real-world semantic accuracy without held-out real-model evaluation.
Prefer readable Python over excessively compressed expressions, with comments explaining non-obvious logic.
