# Release candidate evaluation — 22 November 2026

**Verdict: NOT READY under the stated release criteria.** The application is
demonstrable on fictional documents, but the latest uncut interview still contained
one answer whose correct milestone facts had no usable model citations. An earlier
uncut run also produced a false absence on the approval question. A general,
bounded month-only date-context change corrected that question in both a direct
Gemini retest and a fresh six-question browser replay. The earlier failure remains
part of the record; one improved replay does not establish provider reliability.
The 44-question dataset was measured for retrieval; only six questions received
final answers in the recorded interview, so 100% critical answer completeness has
not been established.

## Frozen, reproducible assessment

The wholly fictional HB-28 corpus contains a signed contract PDF, an approved
change-order PDF, a pending request PDF, a commissioning PDF, a malicious-note PDF,
one deliberately damaged PDF, a Word minutes file, and two Excel workbooks: nine
files in all, eight readable and one failed. The [generator](../scripts/create_release_corpus.py) creates
the same extracted source contents in a new local folder. The
[44 labeled questions and exact citations](../evaluation/release_candidate_ground_truth.json)
were frozen after inspecting the source PDFs, Word paragraphs and tables, and Excel
cells, before evaluating retrieval. Forty cases have expected citations; four
test absence or coverage without a positive source. The
[retrieval case file](../evaluation/release_candidate_retrieval_cases.json) excludes
only those four zero-citation cases. The local original-source SHA-256 manifest is in
the ground-truth file; regenerated PDF/ZIP bytes can differ in metadata even though
all nine extracted source contents were checked to match.

**Automated quality gates:** `python -m pytest -q` returned **308 passed, 1
skipped** in 151.37 seconds. `ruff check src tests app.py scripts` returned
**All checks passed**. `python -m pip check` found no broken requirements.
These gates verify code behavior, not live model accuracy on all 44 questions.

This is an intentionally small synthetic challenge. Its labels were not edited to
make retrieval or answers pass. Previous six-question hard-paraphrase results remain
in the ignored local interview folder; the earlier hybrid result was 5/6 Hit@3 and
keyword was 3/6 Hit@3.

## Retrieval on the frozen corpus

Real cached `sentence-transformers/all-MiniLM-L6-v2` embeddings were used locally.
No semantic request fell back to keyword search. The improved Excel embeddings use
source-derived document, sheet and column labels; displayed evidence remains the
unchanged original cells. Fusion reserves one top-three place for a strong semantic
candidate. No separate reranker was implemented.

| Metric | Keyword | Hybrid |
|---|---:|---:|
| Hit@3 (40 positive cases) | 34/40, 85.0% | 34/40, 85.0% |
| Hit@5 (40 positive cases) | 35/40, 87.5% | 37/40, 92.5% |
| Mean Recall@5 | 0.7675 | 0.8613 |
| MRR@5 | 0.7842 | 0.7758 |
| Keyword fallback in hybrid | N/A | 0/40 |

Hybrid met the specified 90% Hit@5 threshold, but its MRR@5 was slightly worse
than keyword alone and it did not improve Hit@3 on this held-out set. A top-five
search is not an exhaustive BOQ query. The deterministic spreadsheet tool found
all four qualifying rows, exact cells and SAR 6,400,000 sum on the same corpus.

### Individual retrieval outcomes

The table below reports each of the forty positive-citation cases. `H3/H5` means
whether at least one expected citation appeared by rank 3/5; `R5` is the fraction
of all expected citations retrieved by rank 5. Multi-source completeness requires
more than one hit. All expected citations and question wording are in the frozen
ground-truth JSON.

| ID | Category | Keyword H3/H5 | Keyword R5 | Hybrid H3/H5 | Hybrid R5 |
|---:|---|:---:|---:|:---:|---:|
| 1 | semantic | Y/Y | 1.00 | Y/Y | 1.00 |
| 2 | semantic | Y/Y | 1.00 | Y/Y | 1.00 |
| 3 | scope | Y/Y | 1.00 | N/N | 0.00 |
| 4 | scope | Y/Y | 1.00 | Y/Y | 1.00 |
| 5 | contract | Y/Y | 1.00 | N/Y | 1.00 |
| 6 | semantic | Y/Y | 0.50 | Y/Y | 1.00 |
| 7 | contract | Y/Y | 0.50 | Y/Y | 1.00 |
| 8 | semantic | Y/Y | 0.50 | Y/Y | 1.00 |
| 9 | approval | Y/Y | 0.50 | Y/Y | 0.50 |
| 10 | change | Y/Y | 0.50 | Y/Y | 1.00 |
| 11 | change | Y/Y | 1.00 | Y/Y | 1.00 |
| 12 | financial | Y/Y | 1.00 | Y/Y | 1.00 |
| 13 | approval | Y/Y | 1.00 | N/Y | 0.50 |
| 14 | approval | Y/Y | 1.00 | Y/Y | 1.00 |
| 15 | approval | Y/Y | 1.00 | Y/Y | 1.00 |
| 16 | meeting | Y/Y | 1.00 | Y/Y | 1.00 |
| 17 | cross_document | Y/Y | 1.00 | Y/Y | 1.00 |
| 18 | planning | N/N | 0.00 | Y/Y | 1.00 |
| 19 | planning | Y/Y | 0.50 | Y/Y | 1.00 |
| 20 | inspection | Y/Y | 1.00 | Y/Y | 1.00 |
| 21 | inspection | Y/Y | 1.00 | Y/Y | 1.00 |
| 22 | inspection | Y/Y | 1.00 | N/Y | 1.00 |
| 23 | security | Y/Y | 1.00 | Y/Y | 1.00 |
| 24 | financial | Y/Y | 1.00 | Y/Y | 1.00 |
| 25 | financial | Y/Y | 1.00 | Y/Y | 1.00 |
| 26 | exact_id | Y/Y | 1.00 | Y/Y | 1.00 |
| 27 | exact_id | Y/Y | 1.00 | Y/Y | 1.00 |
| 28 | exact_id | Y/Y | 1.00 | Y/Y | 1.00 |
| 29 | completeness | N/N | 0.00 | N/N | 0.00 |
| 30 | completeness | N/N | 0.00 | Y/Y | 0.25 |
| 31 | financial | N/N | 0.00 | Y/Y | 1.00 |
| 32 | cross_document | Y/Y | 0.50 | Y/Y | 1.00 |
| 33 | financial | N/N | 0.00 | N/N | 0.00 |
| 34 | dates | Y/Y | 1.00 | Y/Y | 1.00 |
| 35 | dates | Y/Y | 1.00 | Y/Y | 1.00 |
| 36 | dates | Y/Y | 1.00 | Y/Y | 1.00 |
| 37 | planning | Y/Y | 1.00 | Y/Y | 1.00 |
| 38 | approval | Y/Y | 1.00 | Y/Y | 1.00 |
| 39 | completeness | N/Y | 0.20 | Y/Y | 0.20 |
| 44 | security | Y/Y | 1.00 | Y/Y | 1.00 |

Hybrid's full misses at rank five were cases **3** (original cable-tray scope),
**29** (all BOQ rows over the threshold), and **33** (CO-12 priced row). Its partial
rank-five recalls were **9**, **13**, **30**, and **39**. Keyword's full rank-five
misses were **18**, **29**, **30**, **31**, and **33**; its partial cases are visible
in the table. Case 39 retrieved only one of five schedule rows by generic search,
which is why an exhaustive date answer must use a separate structured inventory.

## Real Streamlit interview

The browser interacted with the running Streamlit app at 1920x1080 and a separate
SQLite index. The folder was indexed in the app, with eight files ready and the
damaged PDF visibly failed. All six frozen questions were submitted independently
and waited for a fresh spinner-completed response. The latest uncut recording
retains the missing-citation failure. No provider HTTP error occurred in that
six-question run; an earlier development run encountered Gemini HTTP 429 and was
not scored as success. A separate attempted replay had a stale browser/index
connection and was discarded before provider answers were scored; the corrected
replay used a fresh absolute database path and checked the ready count in both
SQLite and Streamlit.

| # | Category | Observed result | Verdict | Elapsed |
|---:|---|---|---|---:|
| 1 | Indirect semantic scope | Three 250 kW pumps in Hall A, cited to signed PDF; hybrid search and original page visible | Pass | 14.5 s |
| 2 | Exact Excel IDs | HP-103 SAR 950,000 and HP-1030 SAR 1,050,000, exact cells F6/F10; did not explicitly say they are different items | Partial | 10.9 s |
| 3 | Strict multi-row threshold | Four correct items, exact F4/F5/F8/F10, SAR 6,400,000 Python sum; original row opened | Pass | 11.4 s |
| 4 | Cross-document approval | Correctly distinguished unapproved 5 December proposal from binding 20 November deadline, citing PDF, Word and Excel | Pass | 7.3 s |
| 5 | Milestone status | Five IDs, dates and statuses factually correct, but model provided no usable supporting citations; original dated rows shown for manual review, not claim verification | Fail | 13.2 s |
| 6 | Missing phone/payment terms | No invented contact or payment schedule; coverage warning for damaged file and unverified absence conclusion | Pass with coverage caveat | 10.6 s |

Mean answer latency was **11.3 seconds** (six questions); indexing time is
separate. Numerically checked interview amounts were correct in both spreadsheet
cases. Exact ID matching distinguished HP-103 from HP-1030. The output status for
the BOQ was conservatively reduced because an unrelated PDF failed indexing;
the calculation itself was checked on the readable workbook. The browser displayed
source excerpts and exact cells, but a cited passage is provenance, not proof of
every model interpretation.

The previous uncut run, on the code before the month-only context adjustment,
**failed question 4** with a false absence. A single direct Gemini retest and the
latest browser replay then returned the correct 5 December 2028 unapproved
proposal and 20 November 2028 signed deadline with PDF, Word and Excel citations.
These were evidence-linked, not deterministically fact-verified. The latest
uncut video is 5:32 at 1920x1080; an older 5:48 uncut video containing the false
absence is retained locally. The improvement remains unproven across unseen
documents and repeated provider runs.

## Security and reliability review

- **Untrusted documents:** Source text cannot create tools or execute Python, SQL,
  or shell commands. The system prompt treats embedded instructions as data. The
  malicious-note case is present in the frozen corpus, but its final-answer defense
  was not live-tested in the six-question interview.
- **Excessive agency:** Model-dispatched tools are an explicit read-only allowlist.
  Tool rounds and retries are bounded; HTTP 402/429 display safe messages.
- **Provenance and misinformation:** Citations must resolve to retrieved indexed
  locations. Deterministic BOQ arithmetic uses original cells. Arbitrary semantic
  claims can still be wrong even with a valid citation; the UI labels them as not
  fact-verified. Missing model citations remain unverified and original schedule
  rows are presented separately for manual review.
- **Paths and uploads:** Filename validation blocks traversal, unsupported types,
  empty and oversized uploads; duplicate uploads do not silently replace files.
  Indexing is folder-scoped and corrupt files are reported.
- **Secrets and supply chain:** A scan of 63 tracked files found no credential
  values. `.env`, databases, test documents and videos are ignored. `pip check`
  found no broken installed requirements. Dependencies have version ranges but
  no lockfile or vulnerability-audit result; that remains a release risk.

These checks address relevant risks in the
[OWASP Top 10 for LLM Applications](https://owasp.github.io/www-project-top-10-for-large-language-model-applications/);
they are not a security certification. Cloud LLM questions and retrieved excerpts
still leave this computer for the selected provider. Use only documents whose owner
permits that processing.

## Reproduce the source and retrieval measurement

```powershell
python -m pip install -e ".[openai,embeddings,dev]"
python scripts/create_release_corpus.py
$env:DOCUMENT_AGENT_DB_PATH = ".local/release_candidate_reproduction.db"
$env:DOCUMENT_AGENT_RETRIEVAL_MODE = "hybrid"
$env:DOCUMENT_AGENT_EMBEDDING_ALLOW_DOWNLOAD = "0"
python -m document_agent.cli ingest .local/release_candidate_reproduction
python scripts/evaluate_retrieval.py --db .local/release_candidate_reproduction.db --cases evaluation/release_candidate_retrieval_cases.json --mode both --k 3
python scripts/evaluate_retrieval.py --db .local/release_candidate_reproduction.db --cases evaluation/release_candidate_retrieval_cases.json --mode both --k 5
```

The local videos and provider response JSON files are intentionally excluded from
Git. Review instructions are saved in the ignored local LinkedIn package and the
exact paths are provided in the final handoff. No LinkedIn post was published.
