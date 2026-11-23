# Full interview A/B evidence log — 23 November 2026

## Objective and controls
Requested: record **both complete 44-question live Streamlit interviews**, using the same unseen nine-file fictional corpus, identical question order, same real provider/model and separately pinned original code versions.

- Old `main`: `b4bfc744583060b5854184d7628fbd354e694771`
- New candidate `feature/claim-evidence-hardening` (PR #9): `360a8afdb77710da56d5b06f2ae204f018c4a8fc`
- Harness lives only in `experiment/final-paired-interview-2026-11-23`. Neither original app's code was changed or merged.
- Browser interactions, original generated answers, source IDs and uncut WebM videos are written into GitHub Actions artifacts.
- GitHub workflow `.github/workflows/full-paired-interview.yml` enforces a **44/44 per-version completion gate**. Incomplete videos are explicitly marked as failures rather than edited to appear complete.
- Ground truth source/answer labels are unchanged. A cited source's existence is not necessarily evidence that the answer is factually correct.

## Actual completed attempts, not simulated

| Provider/model | GitHub Actions run | Original main | Candidate | Observed limiting event |
|---|---|---|---|---|
| OpenRouter Nemotron 3.5 Lightning (first recorder) | [45102066270](https://github.com/7clan/document-agent/actions/runs/45102066270) | 15 real displayed answers; interrupted on Q16 | Q1 failed | HTTP 402 `openrouter_in_flight_budget`; original citation scraper undercounted Streamlit sources |
| Gemini 2.5 Flash | [45102991426](https://github.com/7clan/document-agent/actions/runs/45102991426) | Q1 blocked | Q1 blocked | HTTP 429 rate limit |
| OpenRouter Nemotron 3.5 Lightning (fixed scraper, bounded retry) | [45103510896](https://github.com/7clan/document-agent/actions/runs/45103510896) | 2 genuine answers, one with 5 extracted citation IDs; Q3 blocked | Q1 blocked | HTTP 402, candidate diagnostic `openrouter_credits` |
| Gemini 2.5 Flash-Lite one-question availability check | [45104022186](https://github.com/7clan/document-agent/actions/runs/45104022186) | Not run | Not run | HTTP 404 on one model-backed question; cannot use model |
| OpenRouter `google/gemma-4-31b-it:free` one-question availability check | [45104193030](https://github.com/7clan/document-agent/actions/runs/45104193030) | Not run | Not run | HTTP 429 rate limit before a model-backed result |

**Result: neither a complete 44-question video pair nor an end-to-end winner has been established.** Partial real video artifacts are attached to the referenced workflow runs, with raw per-question JSON; they must not be presented as full or successful acceptance.

## Verified engineering comparison, separate from live QA

- `main`: [309 passing automated tests](https://github.com/7clan/document-agent/actions/runs/44981519419).
- PR #9: [375 passing tests](https://github.com/7clan/document-agent/actions/runs/45097246828).
- In a separate 11-claim held-out evaluation, [original A/B](https://github.com/7clan/document-agent/actions/runs/45097242679), the newer verifier improved correct semantic judgments **5/11 → 8/11**, reduced false acceptance of unsupported claims **5 → 2**, and preserved 15/15 hybrid source Hit@5. This is not the same as full question-answer correctness.
- The source-grounding and offline deterministic benchmarks show positive engineering changes, but **do not prove that the newer full assistant beats the merged main on actual user questions**.

## Unblocking completion

At least one compatible model account must allow **88 actual multi-turn document/tool questions** and browser session recording (two versions × 44). The OpenRouter account must have an adequate credit/spending allowance and concurrency budget, or Gemini per-model rate quotas must recover. Once credentials/quota are available, rerun the pinned paired GitHub workflow. Retain the uncut videos and exact raw answers, then manually grade factual accuracy and citations for all 44 pairs.

**Do not merge PR #8 or PR #9 solely on the old 92.5% Hit@5 metric or on offline application-owned coverage.**
