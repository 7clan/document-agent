# Document Intelligence Agent

**Ask questions across PDF, Word, and Excel files — with traceable answers.**

A Python-based document analysis tool that indexes a local folder, retrieves relevant evidence, and uses LLM tool calling to answer questions with references back to the original documents.

[Watch a real, edited demo](https://github.com/7clan/document-agent/blob/experiment/final-unseen-main-vs-citation-linkedin-2026-11-25/media/tx94_main_linkedin_reel.mp4) · [Browse the source](src/document_agent) · [See automated tests](https://github.com/7clan/document-agent/actions/workflows/ci.yml)

## What it does

- **Reads multiple formats:** PDFs, Word (`.docx`), and Excel (`.xlsx`, `.xlsm`, `.xls`).
- **Finds relevant evidence:** keyword search by default; optional local hybrid keyword + semantic retrieval.
- **Calls real document tools:** search, inspect, extract dates, query spreadsheets, and resolve sources.
- **Handles structured calculations:** Python-based financial/BOQ filters, comparisons, and arithmetic instead of relying on model estimates alone.
- **Shows where answers came from:** PDF pages, Word paragraphs/tables, and Excel rows/cells.
- **Supports multiple AI providers:** Google Gemini, Groq, Ollama Cloud, OpenAI, and compatible APIs.

The application includes a **Streamlit interface**, a **CLI**, and a **local SQLite index**. Your source documents and index are not automatically uploaded to GitHub. When using a cloud AI provider, relevant document content may be sent to that provider.

## How it works

```text
PDF / Word / Excel
       ↓
Parse & index locally (SQLite)
       ↓
Search / retrieve evidence
       ↓
LLM + read-only tools / Python calculations
       ↓
Answer + source references
```

## Quick start

Requires **Python 3.11+** and an API key for your chosen model provider.

```bash
git clone https://github.com/7clan/document-agent.git
cd document-agent
python -m pip install -e ".[openai,dev]"
cp .env.example .env
# Set your provider API key in .env
python -m streamlit run app.py
```

On Windows PowerShell, replace `cp .env.example .env` with `Copy-Item .env.example .env`. Select a folder in the sidebar, click **Index folder**, and ask a question. You can also use the **Select one or more PDF, Excel, or Word files** uploader.

To enable optional local semantic retrieval, install `.[openai,embeddings,dev]`, set `DOCUMENT_AGENT_RETRIEVAL_MODE=hybrid`, and configure the embedding model as described in [hybrid retrieval setup](docs/HYBRID_RETRIEVAL_PLAN.md).

## Demonstration and tests

The project is tested with fictional document collections, including an unseen eight-question interview recorded through the actual Streamlit app.

| Check | Result |
| --- | --- |
| Automated `main` tests | **309 passed**, Ruff passed |
| Unseen interview questions answered | **8/8** |
| Answers independently judged correct | **7/8** |
| Answers with resolvable source references | **7/8** |

The interview is a **small synthetic evaluation**, and model-based correctness judgments are provisional; it does not establish production accuracy.

[CI results](https://github.com/7clan/document-agent/actions/runs/44981519419) · [Uncut interview and evidence](https://github.com/7clan/document-agent/actions/runs/45608813595)

## Project notes

This README describes **original `main`**. The [citation-assist PR #11](https://github.com/7clan/document-agent/pull/11) is an unmerged experiment, not a shipped feature.

**Tech stack:** Python · Streamlit · SQLite · pdfplumber · python-docx · openpyxl · local sentence embeddings (optional) · LLM APIs

