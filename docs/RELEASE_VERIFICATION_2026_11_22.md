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
3. The first complete 44-case **Gemma 4/OpenRouter keyword retrieval** acceptance
   run [finished and recorded](https://github.com/7clan/document-agent/actions/runs/45062930786):
   **44/44 attempted, zero provider errors**, 24/44 answers included all expected
   original-source labels, 12/15 critical cases included all labeled sources,
   20/44 were marked unverified, and 37/44 had actual model tool calls (the
   remaining seven include deterministic host results and cautious absences).
   Those are exact-citation coverage and verification-status metrics, **not** a
   24/44 factual accuracy score. Several uncited answers contain correct facts;
   some responses were partial or had indirect answers. The PR is not ready
   to merge on this result.

   **Generic citation-recovery improvement** was evaluated separately on 11
   previously uncited cases: [11-case real Gemma regression](https://github.com/7clan/document-agent/actions/runs/45063766376).
   All eleven were attempted with zero provider errors; **10/11 became
   evidence-linked, 9/11 contained every labeled source, and both critical
   cases had all labeled citations**. This is real provider evidence, not an
   offline simulated response. One date claim remained uncited.

   **Full post-fix keyword Gemma replay:** [run and preserved original answers](https://github.com/7clan/document-agent/actions/runs/45064021986).
   44 cases were attempted; **34 completed without provider errors** and
   **10 returned OpenRouter HTTP 402**, consistent with depleted account
   usage/billing access. Of those 34, 27 contained every labeled expected
   source, 24 were labeled evidence-linked, five were cautious/unverified, and
   five were deterministic. This is *incomplete* as an entire 44-case semantic
   acceptance measure, and 27 expected-label hits must not be misrepresented
   as a 27/34 factual accuracy score. The unfinished cases are not scored as
   model reasoning failures.

   **Full hybrid Gemma A/B:** [run and original answers](https://github.com/7clan/document-agent/actions/runs/45063695738)
   attempted the frozen 44 with real MiniLM, but **six OpenRouter HTTP 402**
   prevented a complete model comparison. Hybrid retrieval itself separately
   passed the independent 40-label test (37/40 Hit@5 with zero fallback).
   Do not infer that using hybrid improved full-answer accuracy from the
   billing-blocked comparison.

   Both full Gemini and full OpenRouter runs lack sufficient provider quota
   for an uninterrupted *current-code* acceptance. Additional expensive
   acceptance workflows were changed to **manual dispatch only** to avoid
   re-triggering charges on routine source pushes; the benchmark script now
   halts immediately on HTTP 402 or after two consecutive HTTP 429 errors.
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

**NOT MERGED; DRAFT.** Security, Linux and Windows CI, real hybrid retrieval,
and both providers' live smoke tests pass. The two complete-model 44-question
acceptance attempts on the latest general citation-recovery change were
interrupted by quota/billing restrictions, and original-source correctness
still requires independent review. Keep draft until a funded/provider-quota
window permits an uninterrupted post-fix replay and remaining citation errors
are assessed. No claim of 100% answer accuracy or zero residual risks is made.

