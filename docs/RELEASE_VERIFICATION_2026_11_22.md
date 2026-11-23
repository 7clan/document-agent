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

## Follow-up: account limits and evaluator integrity

The user's OpenRouter Activity view reports about **$0.10 spent across 409
requests** over the prior month. This does **not** establish the remaining
credit balance, nor is all historical usage attributable to this project.

A direct **read-only GET /api/v1/key**, executed by
[GitHub Actions](https://github.com/7clan/document-agent/actions/runs/45071104326),
authenticated successfully and reported **no configured key spending cap**.
It made **zero inference calls** and printed no key, account identifiers, exact
balance or raw response. Thus the earlier **HTTP 402** was not explained by a
configured per-key limit; likely remaining causes include account credits or an
in-flight spending budget. The endpoint does not expose the account credit
balance; this is still **unconfirmed**.

The previous release replay tracked a misleading boolean: Python's
`all([])` returned true for an answer with no citations. The replay reporter
now separates:

- `answers_with_citations` — actual nonempty source lists;
- `verified_source_citations` — cited cases for which every cited source
  resolves (never counts an empty list);
- `answers_without_citations` — answered/abstained cases with no source list;
- `expected_sources_covered` — labels covered by cited locations, **not**
  an answer-accuracy score;
- `provider_http_402` and `provider_http_429` — external access errors,
  never counted as factual reasoning mistakes.

The historical artifacts are preserved unchanged; revised metrics apply to
future replay reports. The agent's provider diagnostic now records only
**allowlisted** OpenRouter `error.metadata.limit_source` categories when
present, excluding keys, prompts, URLs, full response bodies, account IDs and
other sensitive metadata. No additional paid provider requests were made.

**Controlled acceptance invocation before merge:** GitHub only exposes
`workflow_dispatch` UI triggering for workflows present on the default
branch. To run an expensive benchmark on this draft feature branch, make a
deliberate commit that **adds or edits only** its respective trigger file:

| Evaluation | Trigger path |
|---|---|
| Native Gemini 44 | `evaluation/TRIGGER_GEMINI_44.txt` |
| OpenRouter Gemma 44 (keyword) | `evaluation/TRIGGER_GEMMA_44.txt` |
| OpenRouter Gemma 44 (hybrid) | `evaluation/TRIGGER_GEMMA_HYBRID_44.txt` |
| Targeted Gemma citation cases | `evaluation/TRIGGER_GEMMA_CITATION.txt` |

These paths are **not created by this change**; routine code commits do not
match them. All paid acceptance workflows share a concurrency group so two
benchmarks cannot run simultaneously. The benchmark itself stops on its first
HTTP 402 or two consecutive HTTP 429 responses, minimizing unnecessary calls.
Do not trigger a new paid test without first establishing usable account quota.

## Targeted local reliability hardening — 23 November 2026

A close review of the **original model answer artifacts**, not a substitute
model, found repeatable gaps in three categories: similar financial item IDs,
milestone dates/statuses that models occasionally returned without citations,
and an untrusted draft note containing instructions directed at the AI.
We addressed these at the **application layer**, using exact indexed sources:

1. **Exact pairwise priced-item comparison** resolves two distinct whole IDs
   (including prefix traps like `HP-103` vs `HP-1030`), checks each amount
   against its original source cell, refuses ambiguous duplicate IDs, and
   never subtracts amounts from different currencies. If evidence is missing,
   it abstains rather than fabricating a numerical difference.
2. **Exact single-milestone register lookup** identifies date, classification,
   and approval directly from an indexed Excel register row. It distinguishes
   contractual dates from planning and unapproved proposals. A signed original
   milestone cannot be mistaken for approval of a *new contractual deadline*.
   Conflicting duplicate milestones or unsupported status values are withheld.
3. **Document instruction trust boundary** recognizes a narrow question about
   whether the AI should obey instructions printed inside a PDF. It answers
   "No", authenticates the indexed malicious-source location when present,
   and never follows or forwards the embedded commands.
4. **Explicit unique-sheet financial filters** (e.g., list/total *all*
   named-sheet items above a stated currency threshold) call the existing
   Python spreadsheet query directly, verifying every returned amount cell.
   Ambiguous worksheet names or cross-contract comparisons keep the
   normal provider/clarification path.

These guards are **generic source/schema checks**, not prewritten fixture
answers, and their tests include source-record conflicts, duplicated IDs,
different currencies, missing codes, ambiguous sheet names, and actual
end-to-end ingestion of the fictional nine-file corpus.

[Real offline 44-question host-routing benchmark](https://github.com/7clan/document-agent/actions/runs/45088426736):
**15/44** questions were answered using indexed host logic, including
**8/15 critical** cases; **13** had source locations independently
re-resolved, and **two** were conservative, uncited refusals (a corrupt
attachment and a nonexistent item). **29** still required a provider.
**Zero model API calls** were made during this test.
The earlier pre-hardening offline snapshot had 13 host-resolved cases.
This is routing/grounding coverage, **not a claim of 15/44 factual accuracy
or a completed post-fix LLM acceptance benchmark**.

[Offline Linux code CI](https://github.com/7clan/document-agent/actions/runs/45088568292)
passed **350 tests**, Ruff, and retrieval checks on the new source guards.
[Actual Windows Python 3.12 rerun](https://github.com/7clan/document-agent/actions/runs/45088560611)
also passed **350 tests** and `pip check` on the same branch.
No OpenRouter or Gemini inference costs were incurred by these changes.

## Second targeted reliability pass — 23 November 2026

Review of the archived Gemini/Gemma answer artifacts found that correct facts
could still be returned without citations, and that date comparisons sometimes
confused **internal readiness** with a **separate unapproved proposal**. The
following *general source-verified capabilities*, not fixture answer tables,
were added in `src/document_agent/structured_reporting.py`:

- **Reconciled base subtotal:** Identifies a unique signed/base worksheet,
  verifies each priced amount against its original source cell and matches
  the exact total against one independently authenticated subtotal cell.
  It excludes change-order sheets, rejects incomplete rows and inconsistent
  currencies, and declines to assert an unreconciled subtotal.
- **Original contract comparison:** Extracts the *original*, not revised,
  contract amount from an authenticated signed-contract PDF passage. Compares
  it to the complete reconciled BOQ using `Decimal`, requires the same currency,
  and refuses ambiguity or missing original evidence.
- **Complete contractual/planning/proposal register:** Inspects the whole
  uniquely identified milestone register, checks each original row and calendar
  date, ensures distinct milestone identifiers, then reports the recorded
  categories with source citations. It does not claim a proposal has become
  a signed contract change.
- **Planning versus handover contrast:** Selects uniquely identified internal
  readiness and contractual handover milestones; checks original source
  locations, independently links coordination minutes and the signed
  contract when present, computes the calendar-day difference, and
  never substitutes a later unapproved proposal for the internal forecast.

Regression tests cover the *real ingested nine-file corpus*, invalid dates,
duplicate milestone IDs, missing subtotals, original-source reconciliation
and incompatible source scopes.

[Measured offline 44-case replay](https://github.com/7clan/document-agent/actions/runs/45090153292):
**19/44 directly host-answered**, **11/15 critical handled**,
**17 answers with independently resolving original source locations**,
**two cautious evidence-absence refusals** and **25 questions requiring an
external model**. Compared with 15/44 and 8/15 critical from the previous pass,
this adds **four** safe host-resolved questions and **three** critical cases.
All tested answers retained their original document provenance; the entire
44-case evaluation used **zero LLM API calls**.

[Latest offline Linux checks](https://github.com/7clan/document-agent/actions/runs/45090184905):
**353 passing tests**, Ruff and retrieval checks. These are deterministic
grounding and test results. **The full end-to-end model accuracy has not
been remeasured** and should never be conflated with 19/44 host coverage or
92.5% hybrid source Hit@5. Provider quota/billing previously blocked that
separate live-model acceptance test.

## Merge decision

**NOT MERGED; DRAFT.** Security, Linux and Windows CI, real hybrid retrieval,
and both providers' live smoke tests pass. The two complete-model 44-question
acceptance attempts on the latest general citation-recovery change were
interrupted by quota/billing restrictions, and original-source correctness
still requires independent review. Keep draft until a funded/provider-quota
window permits an uninterrupted post-fix replay and remaining citation errors
are assessed. No claim of 100% answer accuracy or zero residual risks is made.

