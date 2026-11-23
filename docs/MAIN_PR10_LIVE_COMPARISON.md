# Pinned original main versus patched PR #10: MQ-46 live interview audit

**Status: partial paired comparison; no valid full 18-question winner.**
The provider interrupted multiple complete runs, including bounded retries.
Missing responses were never labeled incorrect or treated as evidence of regression.

## Frozen implementation and data

- Original main: `b4bfc744583060b5854184d7628fbd354e694771`.
- Patched PR #10: `3c2496fde498e7e4a886533d5f1b171591be47d1` (contains the Q4 addendum-intent guard).
- Original MQ-46 generator and 18-question rubric frozen at
  `7c5f6dff98e0d76d1b5a09813e6c8e822684148c`.
- Each paired run generated one shared nine-document fictional PDF/DOCX/XLSX
  corpus and used exact same documents for both pinned applications within
  that run. Python and Streamlit UI answered with actual provider calls.
- Main versus PR #10 comparison on the useful run uses
  `gemini-3.5-flash-lite`, `GEMINI_API_KEY_2`, hybrid retrieval, with
  runtime extra semantic verification **off for both** (normal default).
- Answers were independently regraded by OpenRouter
  `google/gemma-4-31b-it`; citation integrity measured separately.

## Most informative real paired run

[Recorded 3.5 Flash-Lite run and uncut browser-video segments](https://github.com/7clan/document-agent/actions/runs/45194940348).

The provider returned HTTP 503 despite three bounded retries:
original main at Q14, patched PR #10 at Q11. There were 13 completed main
answers and 10 completed PR #10 answers, so overall `12/13` vs `10/10`
among captured answers is **not a fair full-interview ranking**.

The 10 overlapping question IDs are exactly **Q1–Q10**. Every answer in
this intersection was independently semantically reviewed:

| Matched metric: Q1–Q10 only | Original main | Patched PR #10 |
|---|---:|---:|
| Actual answers captured | 10/10 | 10/10 |
| Semantically correct | **9/10** | **10/10** |
| Incorrect | 1 | 0 |
| Correct AND fully covered by required document citations | 7/10 | 8/10 |

**Material case:** Q8 asks whether partial quality inspections establish
final contractual handover and which signed certificate is required.
Original main incorrectly returned an indexed file inventory.
Patched PR #10 correctly identified the written acceptance certificate
signed by the client Quality Assurance Director and explained that
inspections alone do not establish contractual acceptance.

**Other corrected case:** Q4 asks about the signed A-06 piping addition
and its approved cost. Patched PR #10 now gives the 25-metre East Service
Bay stainless piping addition at AED 600,000. The preceding PR #10 attempt
[before the exact-item intent fix](https://github.com/7clan/document-agent/actions/runs/45191918136)
had incorrectly treated `A-06` as a financial line-item identifier.

## Other attempts and exact infrastructure findings

- [Gemini 3.5 Flash-Lite initial paired attempt](https://github.com/7clan/document-agent/actions/runs/45191918136):
  HTTP 503 on Q6 for both engines; incomplete, no winner.
- [Gemini 2.5 Flash with newer key](https://github.com/7clan/document-agent/actions/runs/45200227891):
  HTTP 404 on Q1 for both engines; no answers captured.
- [Credential/model access probe](https://github.com/7clan/document-agent/actions/runs/45201736824):
  original Gemini key successfully returned HTTP 200 for one trivial
  `gemini-2.5-flash` inference; the newer key returned HTTP 404 for
  that model. Both credentials supported a trivial `gemini-3.5-flash-lite`
  inference. A successful tiny inference is **not** sufficient evidence
  of multi-round agent quota.
- [Gemini 2.5 Flash with original key](https://github.com/7clan/document-agent/actions/runs/45202009729):
  2 main answers captured, no PR #10 answers; provider repeatedly returned
  HTTP 429 after three retries. Again not a valid comparison.

## Interpretation and rollout

The original main previously scored 17/18 and *PR #9* 15/18 on the complete
earlier 3.5 Flash-Lite semantic regrade. That historical PR #9 comparison
**does not establish that main beats patched PR #10**.

The matched 10-question subset in the newer run actually favors patched
PR #10 (10/10 vs 9/10), but is a *targeted regression replay* of questions
used to motivate PR #10 fixes; it is not a fresh prospective holdout.

**Full 18-question release verdict: unproven.** Do not merge or declare PR #10
the winner on this partial evidence. To complete the evaluation, obtain a
working provider budget that supports at least 36 actual multi-round agent
questions plus 36 grading calls, or use a separately pre-verified provider
with comparable function-calling support. Preserve any frozen raw recordings,
question hashes, source evidence, and incomplete-case flags.

[Final CI for the patch and resilience regression tests](https://github.com/7clan/document-agent/actions/runs/45195067681):
397 pytest tests passed and Ruff passed (the project had subsequent
workflow/report-only commits; check the current branch CI before merging).
