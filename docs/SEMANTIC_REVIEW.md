# Semantic verification and MQ-46 regrading

The original regex scorer is preserved for reproducibility. It is NOT a
meaning-based accuracy measurement; it can reject a correct paraphrase when the
question did not ask for all identifiers in the reference answer.

## Runtime (experimental opt-in)

With the application configured for its ordinary LLM provider, set:

```bash
DOCUMENT_AGENT_SEMANTIC_VERIFY=1
# Optional: use a different review model/provider:
# DOCUMENT_AGENT_SEMANTIC_PROVIDER=compatible
# DOCUMENT_AGENT_SEMANTIC_MODEL=google/gemma-4-31b-it
```

An eligible *source-linked* answer gets one additional provider call. Its
original cited passages are supplied to the independent entailment prompt.
A positive model judgment is promoted to **semantic support** only if the
selected literal supporting quotes exist at the exact indexed citations and
numeric anchors in the answer appear in those quotes. If the judgment fails or
is unavailable, the source-linked answer remains visible with its original
status. Missing sources, failed retrieval, or deterministic answers cannot be
silently upgraded. This is not a substitute for human contract/legal review,
and costs an extra inference call. It is disabled by default to avoid unexpected
API spending or 429s.

## Independent MQ-46 semantic regrade

`scripts/semantic_review_unseen.py` regrades frozen, *already recorded*
main-versus-PR9 answers with a question-aware model or explicitly documented
human labels. It never changes the input answers, question text or existing
regex scores. The expected answer is a meaning reference, not a list of tokens
that must be echoed. If the question asks for count and rating only, failing
to repeat compressor IDs is not a mistake.

### Using a separate reviewer model

```bash
python scripts/semantic_review_unseen.py \
  --baseline recordings/main/browser_results.json \
  --candidate recordings/candidate/browser_results.json \
  --rubric evaluation/unseen_coldchain_interview.json \
  --output evaluation-results/semantic \
  --judge-provider openrouter \
  --judge-model google/gemma-4-31b-it
```

Set `OPENROUTER2` or `COMPATIBLE_API_KEY` locally. The provider model
evaluates the question, verified reference answer, and unmodified candidate
answer; separate deterministic metrics track citation source integrity and
reference-document coverage. Judge failures are **unreviewed**, provider
failures are **provider_blocked**; neither is added to the incorrect-answer
count. Results include JSON, CSV, Markdown, and judge identity. An independent
human audit of contentious or high-impact semantic verdicts is still required.

For human-reviewed labels, use
`--human-labels reviewed.json` instead of the provider/model flags. The JSON
structure is `{"main":{"1":{"label":"correct","reason":"..."}},
"candidate":{"1":{"label":"partial","reason":"..."}}}`.

### Limitations

- A language-model judge can itself introduce false negatives or positives;
  report its identity and keep original answers and citations available.
- A positive semantic judgment is not proof of comprehensive document search,
  signed authorization, or exhaustive absence.
- `semantic_accuracy_among_judged` excludes incomplete/error cases and must
  be accompanied by capture and judgment rates. Compare matched model, input
  documents and question-hash pairs only.
- Re-running the answer model can vary answers. Regrading the same frozen
  recordings avoids that source of experimental noise.
