# Hybrid retrieval — v1 implementation and remaining work

**Status: implemented as an optional local mode.** Direct Python calls to
`search_documents` support `mode="keyword"` and `mode="hybrid"`;
`DOCUMENT_AGENT_RETRIEVAL_MODE` controls searches made by the agent. The
existing `semantic_verifier.py` is about answer
validation, not retrieval.

## Implemented

1. **Local embeddings:** Optional `sentence-transformers` dependency with a configurable
   model ID and optional revision. Model downloads require an explicit opt-in;
   document contents are embedded locally rather than sent to a remote embedding API.
2. **Citation-based cache:** `source_embeddings` in SQLite contains document foreign
   keys, exact source citations, content SHA-256 fingerprints, embedding-model identity,
   dimensionality and normalized vectors. Deleting/reindexing a document removes its
   stale vectors; unchanged records are reused.
3. **Retrieval:** PDF page chunks, Word blocks and Excel rows are independently embedded.
   Semantic top-k is merged with lexical top-k using reciprocal rank fusion, with a
   2:1 weight favoring lexical matches. Common question words are omitted from the
   lexical side so they cannot bury a relevant semantic match. Exact item IDs and
   file filters remain enforced.
4. **Agent integration:** The existing `search_documents` tool uses the
   configured retrieval mode and returns the same source citations; the model
   does not choose the mode. `get_evidence` still resolves the original indexed
   text or structured cells.
5. **Resilience:** If optional dependencies, weights or encoding fail, the search
   falls back to the keyword baseline and reports `retrieval_warning`.
6. **Tests:** Offline deterministic fake-model tests cover paraphrase matching,
   duplicate elimination, incremental index updates, document deletion, file
   scoping, and missing-model fallback. The existing project regression suite
   tests the original parsing, evidence and numeric behavior.

## Setup

See [README](../README.md#hybrid-retrieval-optional-local).
Install the optional dependency with `pip install -e ".[embeddings]"` and
enable `DOCUMENT_AGENT_RETRIEVAL_MODE=hybrid` in local `.env`.
Opt in to the model download once if needed by setting
`DOCUMENT_AGENT_EMBEDDING_ALLOW_DOWNLOAD=1`; restore `0` for offline use.

## Measured fictional retrieval benchmark (21 November 2026)

A real local `sentence-transformers/all-MiniLM-L6-v2` embedding model was
downloaded and tested in GitHub Actions. On **14 manually labeled fictional
queries**, including six harder paraphrases, with the top-three cutoff:

| Measure | Keyword only | Hybrid |
|---|---:|---:|
| Hit@3 / mean Recall@3 | 0.9286 (13/14) | 1.0000 (14/14) |
| MRR@3 | 0.8571 | 0.9643 |
| Semantic fallback | Not applicable | 0 queries |

This demonstrates a limited retrieval improvement on the test fixture;
it **does not establish answer accuracy**, performance on unknown real documents,
or statistically reliable generalization. See the
[real-model workflow run](https://github.com/7clan/document-agent/actions/runs/44930561640)
and its saved report for the exact questions, expected citations and ranks.
The benchmark CLI also supports a separate local indexed corpus with
independently labeled `expected_citations`.

## Limitations and future improvements

- **Limited evaluation:** Offline fake-vector tests validate integration, while the
  real MiniLM benchmark measures retrieval on a small fictional corpus. Larger,
  independently labeled collections of unfamiliar documents are needed before
  claiming reliable gains in real-world answer accuracy.
- **Scalability:** SQLite stores vectors as JSON, and the initial semantic
  implementation performs a linear cosine scan. Migrate to an ANN/vector
  extension for very large corpora after profiling real workloads.
- **Exact IDs:** Whole structured identifiers such as `EL-103` and `EL-1030`
  are now distinguished in both keyword and semantic results. However, strict
  reference filtering can omit related records that do not repeat the ID;
  issue a separate, broader question when cross-document context is needed.
  More evaluation is required for unusual PDF hyphens and broken OCR text.
- **Multilingual:** The default all-MiniLM-L6-v2 model is primarily English.
  Choose and evaluate a multilingual embedding model for cross-language retrieval.
- **Revision tracking:** Pin `DOCUMENT_AGENT_EMBEDDING_REVISION` for reproducible
  cache identity when using downloadable models.
- **Relevance is not truth:** Semantic similarity is only a search heuristic;
  verify source context, amounts, and interpretive claims independently.

## Engineering constraints

- The LLM can call only the declared read-only tools. It cannot execute arbitrary SQL.
- BOQ filtering and totals stay in `spreadsheet.py` using deterministic logic
  and `Decimal`, not embedding similarity or LLM arithmetic.
- `get_evidence` continues resolving exact source records; model-derived
  vectors are not source evidence.
