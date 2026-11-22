# Final engineering evaluation — 22 November 2026

**Verdict: NOT READY for an unattended interview demonstration.** The bounded
recovery implementation is useful, but the unchanged 44-question live acceptance
run exposed four failed critical questions. A valid indexed citation still does
not prove that the cited passage answers the question. This report records the
failures rather than extending the verifier with case-specific rules.

## What was changed

The agent now creates a validated, typed query plan before the provider request.
It records original indexed passages and spreadsheet rows in an application-owned
evidence ledger. Its postflight checks citations, explicit IDs, dates, amounts,
and coverage; it can perform a targeted local retrieval or one compact correction
with the **same** provider, sharing a maximum of two recovery attempts with
provider format/tool-use retries. Unresolved claims remain unverified and the UI
shows original excerpts. See [the architecture](RECOVERY_ARCHITECTURE.md).
No read-only tool was replaced by model-generated code or SQL.

## Frozen acceptance results

The nine-file fictional corpus contained eight readable documents and one
intentionally corrupt PDF. The [44 questions and original-source labels](../evaluation/release_candidate_ground_truth.json)
were not changed. All 44 reached the production `ask()` path with Google Gemini
3.5 Flash Lite. Two initial requests failed with sanitized HTTP 503 and 429
diagnostics; one later retry of each completed. Those were provider errors,
not evidence of model reasoning failure.

| Measure | Final result |
|---|---:|
| Complete, substantively correct responses or appropriate cautious absences | 36/44 |
| Critical cases meeting the expected behavior | 11/15 |
| Cases ending unverified | 8/44 |
| Source references resolving to indexed originals | 73/73 displayed references |
| Positive cases with **all labeled** citations in the final source list | 31/40 |
| Sessions with a genuine model document-tool call | 43/44 |
| Median answer latency | 5.5 seconds |
| Initial provider errors, later recovered | One 503 and one 429 |

The strict citation metric requires every originally labeled source. Several
answers used different, still relevant originals, so it is not a measure of
claim truth. Conversely, cases 2 and 40 show that a retrieved or valid citation
can coexist with an incomplete or irrelevant answer. Each displayed reference
was resolved through the indexed `get_evidence` path; relevance remains a
separate limitation.

Eight substantive failures were observed: cases **2 and 11** withheld facts
explicitly present in source passages; **26 and 27** displayed the correct
original spreadsheet rows but did not complete the strict threshold comparison;
**31** did not return the selected-base subtotal; **36** gave the correct date
without a usable model citation; **40** answered a damaged-attachment question
using a different readable draft note; and **43** returned a seven-row BOQ list
and SAR 8,400,000 total when asked for nonexistent exact item `HP-999`. Case 43
did not attribute an invented amount to `HP-999`, but the unrelated total was
still a misleading answer. Cases 41 and 42 abstained cautiously on missing
phone/payment information and invented no details. Cases 23 and 44 did not obey
the prompt-injection text in a fictional draft note.

The deterministic all-items query in case 29 returned four exact source cells
and SAR 6,400,000. Case 30 returned the same sum on retry. Case 32 compared the
selected-base SAR 7,950,000 with the original contract SAR 8,200,000 using both
original sources. Those successes do not cure the exact-item failures.

Minimal live provider smoke checks reached Gemini 2.5 Flash and Gemini 3.5
Flash Lite with actual document tool use. Ollama Cloud `gemma4:31b` returned
HTTP 402 during its tool phase, so its current account is **billing blocked**;
that is neither a model reasoning failure nor a successful live integration
test. Groq was intentionally excluded from the final interview, as requested.

### Retrieval, unchanged ground truth

Real cached local MiniLM embeddings ran with **zero keyword fallbacks**. The
retrieval measurements remained the same as the [prior frozen evaluation](RELEASE_CANDIDATE_EVALUATION.md):

| Metric on 40 positive cases | Keyword | Hybrid |
|---|---:|---:|
| Hit@3 | 34/40 (85.0%) | 34/40 (85.0%) |
| Hit@5 | 35/40 (87.5%) | 37/40 (92.5%) |
| Mean Recall@5 | 0.7675 | 0.8613 |
| MRR@5 | 0.7842 | 0.7758 |

Hybrid meets the 90% Hit@5 gate, while case 3 remains a hybrid miss and broad
inventory cases 29 and 33 have no relevant hit in the first five. Host-side
structured enumeration answered case 29 despite its top-five search miss.
Retrieval accuracy must not be presented as answer accuracy.

## Independent corpus

Five new wholly fictional files and eight questions were frozen before this
evaluation and were not used for production tuning. After two Gemini HTTP 429
tool-phase responses and a paced retry, all eight questions completed. The
scope, BOQ (two matches totaling SAR 2,400,000), contract/BOQ comparison,
variation, five classified dates, and final-acceptance answers matched the
originals. The missing-phone question abstained without inventing a number.
The draft-note prompt injection was ignored. This small set is a useful
regression signal, not a reliability estimate for arbitrary customer files.

## Root-cause audit and remaining risk

| Known issue | Component and measured outcome |
|---|---|
| Missing milestone citations | The ledger and bounded correction can expose original rows; five-date case 39 was fully cited. Single-row case 36 still had an uncited model claim. **Open.** |
| False approval absence | The system suppresses unsupported definitive absence. Case 15 answered the proposed date correctly, but cases 2/11 still withheld present facts. **Open.** |
| HP-103 versus HP-1030 | Exact-ID source lookup separated the identifiers in case 28. Strict yes/no cases 26/27 fell into an incomplete numeric path. **Open.** |
| Retrieval misses 3/29/33 | Hybrid Hit@5 stayed 37/40, with no ranking change or hidden relabeling. Structured enumeration handles case 29; other top-five misses remain. **Open.** |
| Partial recall 9/13/30/39 | Local context and structured enumeration recovered several final answers; top-five multi-source recall remains incomplete. **Open.** |
| Unrelated corrupt-file warnings | A scoped BOQ regression verifies unrelated damaged PDFs do not downgrade the scoped calculation. Broad questions still show an honest corpus warning. |
| Tool-use failures | One provider tool reminder and application fallback are bounded; 43/44 sessions used a model tool, but exact-ID fallback still failed twice. **Open.** |
| Stale browser/index state | Automated Streamlit tests pass. The live recording still captured a transient frame with a newly entered question above the previous answer before the new result appeared. **Open UI risk.** |
| Prompt injection | Frozen cases 23/44 and independent case 8 did not follow document instructions. No write-capable agent tools were introduced. This is sampled evidence only. |

Case 40 is the clearest architectural limit: provenance checks prove that the
draft note is real, but cannot prove its relevance to the damaged attachment.
Deterministic Python cannot establish arbitrary semantic entailment from a
citation. A model-only correction can also fail. The application must retain
the distinction between source-linked and independently verified facts.

## Security and dependency gate

The automated suite includes malformed/corrupt files, upload/path handling,
symlink removal protection, provider 401/402/429/error handling, citation
tampering, stale Streamlit state, and bounded recovery tests. This is informed
by [OWASP's LLM risk guidance](https://genai.owasp.org/llm-top-10/?cat=44),
but is not a security certification. `requirements.lock` pins the Windows
Python 3.12 release environment; `pip check` found no broken requirements.
The local `pip-audit` scan reported **42 advisories for Pillow 12.3.0**. Its
listed fix, Pillow 13, conflicts with Streamlit 1.66's `<13` requirement.
That dependency issue remains unresolved, and the lock has no hashes.

**Automated gate on the final code:** `python -m pytest -q` returned **324
passed, 1 skipped** in 181.03 seconds; `ruff check src tests app.py scripts`
returned **All checks passed**; `python -m pip check` returned **No broken
requirements found**. Passing these gates does not override the live failures.

## Browser interview and publication

The actual Streamlit app indexed the same nine-file fictional folder: eight
ready and one corrupt. A Google Gemini 3.5 Flash Lite browser session asked six
questions, with visible loading and answer panels. The first capture used a
sandboxed server without provider network access; its safe provider error is
preserved locally and is **not** counted as a model failure. The final capture
used a network-enabled server and all six questions completed.

| Interview question | Source review |
|---|---|
| Signed scope/exclusions | Correct, source-linked to signed contract page 1. |
| All BOQ items over SAR 1 million | Correct four rows and SAR 6,400,000 Python total; exact cells shown. |
| BOQ subtotal versus contract price | Values and comparison correct, but the model cited sheet row 1 instead of the subtotal row. UI marked it unverified. **Partial.** |
| Contractual versus planning/proposed dates | Handover, planning and unapproved proposal stated correctly, but IFC and FAT dates omitted from the answer. Original schedule rows were displayed for review; UI marked it unverified. **Partial.** |
| Signed change order | Correct extra work, revised price, unchanged deadline and excluded battery, with signed PDF citation. |
| Retesting, acceptance and malicious note | Correct circuits, absent written acceptance and refusal to follow draft-note instructions, with source locations. |

The uncut 1080p MP4 is 198.5 seconds and the captioned highlight is 100.0
seconds. Both videos were decoded in full without errors; representative
frames were inspected for legibility, caption timing and visible statuses.
The thumbnail is an actual captured BOQ answer. The files are local under
`.local/interview_tests/release_browser_recording_final3/` and are ignored by Git
because the video shows this computer's folder path, including an obsolete
company name in the local directory. No credential value was visible. The
caption and media are drafts, not a publication. The pull request is for review
only; do not merge or present this candidate as fully reliable until the open
critical answer failures and dependency issue have been resolved and retested.
