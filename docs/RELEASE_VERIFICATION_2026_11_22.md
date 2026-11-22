# Release verification — 22 November 2026

This is a post-fix evidence report for `feature/bounded-self-recovery`.
It does **not** overwrite the historical pre-fix assessment
[`FINAL_RELEASE_EVALUATION.md`](FINAL_RELEASE_EVALUATION.md).

## Verified gates

| Gate | Measured result | Primary evidence |
|---|---|---|
| Real Gemini API and document tool calling | Passed; six tool schemas, original cited facts | [Gemini compatibility](https://github.com/7clan/document-agent/actions/runs/45059517212) |
| Real Streamlit Chromium interview | **6/6 completed**; two real Gemini/tool cases, four Python guards, recorded uncut video | [Browser run and artifact](https://github.com/7clan/document-agent/actions/runs/45060267223) |
| Exact BOQ ID safety | HP-103 SAR 950,000 below threshold; HP-1030 SAR 1,050,000 above; missing HP-999 never gets an unrelated total | [Browser run](https://github.com/7clan/document-agent/actions/runs/45060267223) |
| Corrupt-attachment approvals | Correctly refuses to use unrelated indexed documents to establish approval from failed file | [Browser run](https://github.com/7clan/document-agent/actions/runs/45060267223) |
| Genuine MiniLM semantic retrieval | Keyword Hit@5 **35/40** versus hybrid **37/40 (92.5%)**, no fallback; 3 model-backed hybrid queries passed | [Hybrid run and ranks artifact](https://github.com/7clan/document-agent/actions/runs/45062311080) |
| Gemma 4 31B through OpenRouter | **3/3 smoke cases completed**, of which 2 used real Gemma function calls and original citations, 1 was deterministic | [Gemma provider run](https://github.com/7clan/document-agent/actions/runs/45062669060) |
| Python 3.11 and Windows lock dependency vulnerability audit | **No known findings** using pip-audit against installed Python 3.11 environment and upgraded pinned Windows snapshot; pip check passed | [Dependency security run](https://github.com/7clan/document-agent/actions/runs/45062802160) |
| CI test/lint | Offline tests, retrieval smoke and Ruff passed after the dependency fixes | [Checks](https://github.com/7clan/document-agent/actions/runs/45062802144) |
| Actual Windows Python 3.12 execution | **330 tests passed**, Pillow 13.0.0 and Streamlit 1.67.0 installed, no broken requirements | [Windows compatibility](https://github.com/7clan/document-agent/actions/runs/45063157350) |

## Limitations and unattended-release gates

1. The historical **44-case Gemini 3.5 Flash Lite** assessment (36/44 and
   11/15 critical) is *pre-fix*. It is not an assessment of the latest branch.
2. Attempts to replay the new branch using **Gemini 2.5 Flash** in bulk returned
   repeated provider **HTTP 429**. One initial job had 37 provider errors; the
   later runner stops after two consecutive 429s and preserves partial results.
   These responses are **rate/quota failures**, not measured semantic failures.
   The full Gemini replay is **not complete**.
3. A separate 44-case **Gemma 4/OpenRouter** full acceptance run is available.
   Its observed answers and exact citations are saved in a machine-readable
   artifact for individual comparison against unchanged human-created labels.
   No result should be claimed before independently inspecting that artifact.
4. Source-link validity is NOT claim entailment. A correct answer can cite a
   different relevant source from the frozen label, and a syntactically valid
   citation can be irrelevant. Independent source-level factual review must
   precede a claim of full accuracy.
5. The nine-file corpus can be regenerated from
   `scripts/create_release_corpus.py`. Spreadsheet and Word containers can
   change byte hashes with fresh ZIP metadata; the acceptance runner reports
   per-file SHA256 comparisons rather than silently asserting byte identity.
6. Pinned Windows dependencies are audited as a *list of versions*. In addition,
   a separate real Windows 3.12 runner installed the application runtime,
   checked Pillow and Streamlit versions and ran all 330 tests successfully.
   This checks the runtime resolver; it is not a byte-for-byte installation
   of every optional package in the 100-package Windows lock.
7. The project has read-only model tools and does not provide a general
   unrestricted security guarantee. Never submit confidential data to an
   external provider without appropriate data-processing authorization.
8. Workflows only access provider keys through encrypted repository secrets.
   Test output contains only fictitious source documents and measured answers.

## Merge decision

Do **not** mark the PR ready or merge into `main` merely because the six-question
smoke interview passed. Require at minimum a complete 44-case source-review,
a passing security audit, and passing CI on the final commit. If a provider
rate-limits or the corpus score is low, keep the draft PR and record the
unresolved result instead of claiming an unconditional release.

