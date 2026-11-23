# Main-based citation discovery (no extra verification model)

This branch starts directly from the unchanged `main` commit
`b4bfc744583060b5854184d7628fbd354e694771`.
It does **not** incorporate or depend on PR #10's additional semantic
verification stage, answer-blocking rules, or its changes to tool routing.

## What changed

The normal document-answer flow continues to answer the user's question once.
After model tool retrieval, the application also consults the **local SQLite
index only** to improve discoverability of original citations:

1. **Missing-reference recovery**: If the model returned a claim without any
   source references, a reference may be recovered from an indexed PDF
   passage, Word paragraph/table row, or Excel row **only when** a substantial
   literal phrase overlaps and all stated numeric/ID anchors match. Wrong or
   fabricated model-supplied references are **not** silently overwritten.
2. **Additional source locations**: Relevant indexed citations from other
   documents may be presented under the existing *Retrieved locations for
   manual review* section. They are explicitly **not** promoted to factual
   verification or silently attached as claim proof. This helps find missing
   cross-document scope, contract, addendum and proposal documents.
3. **Non-blocking behavior**: There is **no extra API call**, no semantic judge,
   no numeric-verification gate, no second answer pass, and no new reasons to
   refuse or delay a model answer. The existing answer text and deterministic
   calculations remain unchanged.
4. **Existing safety behavior remains**: All displayed citation strings come
   from indexed records and are resolvable by `get_evidence`; the application
   still treats source-linked claims as *facts not verified*.

The local lookup is limited to 3,000 indexed source records per question. Its
results are intentionally suggestions, not a claim of exhaustive coverage.

## Toggle and safe rollback

The branch enables citation assistance by default. Set:

```bash
DOCUMENT_AGENT_CITATION_ASSIST=0
```

to immediately restore original main's citation behavior without reverting
the commit or affecting the LLM, numeric calculations, or provider settings.

## Testing and interpretation

`tests/test_main_citation_assist.py` tests missing citations, wrong negation,
unavailable numeric derivations, multi-document suggestions, fake references,
PDF/Word/worksheet pointers, and the disabled path.

This is an engineering branch, **not a merge**. Offline tests do not establish
that the system is better on unseen documents. A follow-up untouched holdout
should compare first-pass answer correctness, citation precision, source
coverage, and response latency against pinned original main. Preserve full
model answers and never use model-judge output to rewrite an answer.
