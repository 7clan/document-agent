# Release assessment notes — 22 November 2026

This feature branch improves hybrid retrieval and evidence presentation without
changing the provider adapters, read-only tool list or deterministic BOQ arithmetic.

- Excel embeddings now include original workbook, worksheet and column headings.
  The authentic source row and exact cell references remain unchanged.
- Hybrid fusion preserves two leading fused results while allowing a strong
  semantic candidate into the top three.
- Exhaustive schedule comparisons receive original dated status rows and clauses.
  Missing dates, or uncited model claims, are shown as application-retrieved
  original evidence for manual review rather than silently certified.
- Month-only approval questions receive bounded original date and status context.
- Starting a new Streamlit question clears the previous answer and source panel.
- A wholly fictional nine-file corpus, 44 frozen labels and reproduction script
  accompany the [evaluation report](RELEASE_CANDIDATE_EVALUATION.md).

**Status: interview-demo prototype, not release ready under the specified
acceptance gate.** An earlier uncut Gemini interview showed a false absence;
the bounded context change corrected that question in a fresh six-question
browser replay. The replay still gave correct milestone facts without usable
model citations, and the exact-ID answer was partial. Broader answer reliability
and critical-case completeness are unproven. Review the report and original
sources before using the app for consequential decisions.
