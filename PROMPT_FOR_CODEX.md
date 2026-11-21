# Document Intelligence Agent — development brief

## Project identity
An independent, source-grounded AI assistant for analyzing PDF, Word, and Excel project documents, with deterministic BOQ queries and a Streamlit UI/CLI.

## Current architecture
- `app.py`: web UI and document management
- `src/document_agent/ingest.py`: ingestion into a local SQLite database
- `src/document_agent/db.py`: document/passage/row storage
- `src/document_agent/tools.py`: read-only retrieval, evidence lookup and dates
- `src/document_agent/spreadsheet.py`: deterministic BOQ comparisons and totals across Excel and eligible PDF tables
- `src/document_agent/agent.py`: LLM provider integrations and tool orchestration
- `tests/`: regression and integration tests

## Hybrid retrieval — implemented opt-in v1; next: evaluate and scale
The initial hybrid retrieval implementation lives in `src/document_agent/hybrid.py` and is configured through `DOCUMENT_AGENT_RETRIEVAL_MODE=hybrid`. It provides local sentence embeddings, citation-based SQLite caching, cosine ranking and reciprocal rank fusion, with keyword fallback. The next objectives are real-model held-out retrieval evaluation, better exact identifier coverage, profiling and scalable vector indexing. Do not equate semantic similarity with answer verification. See `docs/HYBRID_RETRIEVAL_PLAN.md`.

## Engineering rules
- Work on feature branches; avoid breaking `main`.
- Do not change or expose user documents, secrets, or `.env` files.
- Keep the LLM limited to declared read-only tools. Calculations and evidence checks must remain deterministic in Python.
- Do not invent benchmark results, test outcomes, or provider abilities.
- Run tests and lint when a runnable checkout is available, and report what was actually verified.
- Favor clear code that the owner can explain and maintain.
