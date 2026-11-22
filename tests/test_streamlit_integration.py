"""Headless Streamlit smoke test for indexing and a structured BOQ result."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from reportlab.pdfgen.canvas import Canvas
from streamlit.testing.v1 import AppTest

from document_agent.agent import Answer
from document_agent.db import connect
from document_agent.tools import extract_dates, query_spreadsheet


def test_switching_folders_clears_answer_and_blocks_stale_index(tmp_path, monkeypatch):
    old_folder = tmp_path / "prior_folder"
    demo_folder = tmp_path / "demo"
    old_folder.mkdir()
    demo_folder.mkdir()
    db_path = tmp_path / "app.db"
    conn = connect(db_path)
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Old.pdf','pdf','ready')")
    conn.execute("INSERT INTO metadata(key,value) VALUES('active_folder',?)",
                 (str(old_folder),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("DOCUMENT_AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-not-a-real-key")
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=10).run()
    folder_field = next(field for field in page.sidebar.text_input
                        if field.label == "Folder path on this computer")
    folder_field.set_value(str(old_folder)).run()
    page.text_area[0].set_value("What is in this folder?").run()
    assert not next(button for button in page.button
                    if button.label == "Ask agent").disabled
    page.session_state["last_answer"] = Answer("Old answer", ["Old.pdf | document"], [])
    page.run()
    next(field for field in page.sidebar.text_input
         if field.label == "Folder path on this computer").set_value(str(demo_folder)).run()
    assert not page.exception
    assert "last_answer" not in page.session_state
    assert next(button for button in page.button if button.label == "Ask agent").disabled
    assert any("isn't the active index" in item.value for item in page.sidebar.info)
    next(button for button in page.sidebar.button
         if button.label == "Index folder").click().run()
    assert not page.exception
    assert not next(button for button in page.button
                    if button.label == "Ask agent").disabled
    (demo_folder / "pending.pdf").write_bytes(b"waiting for indexing")
    page.run()
    assert any("waiting for indexing" in item.value for item in page.sidebar.info)


def test_streamlit_indexes_and_displays_verified_boq(tmp_path, monkeypatch):
    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ SAR"
    sheet.append(["Item", "Total Amount (SAR)", "Due"])
    sheet.append(["Transformer", 1_500_000, "2026-11-15"])
    book.save(tmp_path / "BOQ.xlsx")
    pdf = Canvas(str(tmp_path / "Contract.pdf"))
    pdf.drawString(72, 700, "Submit design drawings by 15 November 2026.")
    pdf.save()
    db_path = tmp_path / "app.db"
    monkeypatch.setenv("DOCUMENT_AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-test-only")
    # UI behavior is independent of the optional embedding model's cold load.
    monkeypatch.setenv("DOCUMENT_AGENT_RETRIEVAL_MODE", "keyword")
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=20).run()
    assert not page.exception
    next(field for field in page.sidebar.text_input
         if field.label == "Folder path on this computer").set_value(str(tmp_path)).run()
    next(button for button in page.sidebar.button
         if button.label == "Index folder").click().run()
    assert not page.exception
    conn = connect(db_path)
    result = query_spreadsheet(conn, currency="SAR", value=1_000_000)
    assert result["total_matches"] == 1
    page.session_state["last_answer"] = Answer(
        "Verified match", ["BOQ.xlsx | BOQ SAR!B2"],
        [{"name": "query_spreadsheet", "args": {"value": 1_000_000, "currency": "SAR"},
          "ok": True}], {**result, "verified_args": {"value": 1_000_000, "currency": "SAR"}},
    )
    page.run()
    assert not page.exception
    assert page.dataframe
    assert any("Spreadsheet matches" in title.value for title in page.subheader)
    date_result = extract_dates(conn)
    assert any(isinstance(row["context"], dict) for row in date_result["dates"])
    assert any(isinstance(row["context"], str) for row in date_result["dates"])
    page.session_state["last_answer"] = Answer(
        "Candidate date", [date_result["dates"][0]["citation"]],
        [{"name": "extract_dates", "args": {}, "ok": True}], date_result,
    )
    page.run()
    assert not page.exception
    assert any("Candidate dates" in title.value for title in page.subheader)
    page.session_state["last_answer"] = Answer(
        "- Drawings are due — Contract.pdf | page 1 | chunk 0",
        ["Contract.pdf | page 1 | chunk 0"],
        [{"name": "search_documents", "ok": True}],
        verification_status="evidence_linked",
        claims=[{"text": "Drawings are due", "status": "evidence_linked",
                 "sources": ["Contract.pdf | page 1 | chunk 0"],
                 "reason": "Interpretation is not independently proven",
                 "quotes": [{"citation": "Contract.pdf | page 1 | chunk 0",
                             "quote": "Submit design drawings by 15 November 2026."}]}],
    )
    page.run()
    assert not page.exception
    assert any("AI answer with checked source references" in item.value
               for item in page.caption)
    page.session_state["last_answer"] = Answer(
        "Source-linked answer", ["Contract.pdf | page 1 | chunk 0"],
        [{"name": "search_documents", "ok": True, "retrieval_mode": "hybrid",
          "semantic_matches": 2}], verification_status="evidence_linked",
    )
    page.run()
    assert any("Retrieval used hybrid keyword + semantic search" in item.value
               for item in page.caption)
    page.session_state["last_answer"] = Answer(
        "Fallback answer", ["Contract.pdf | page 1 | chunk 0"],
        [{"name": "search_documents", "ok": True, "retrieval_mode": "keyword",
          "retrieval_warning": "Semantic retrieval unavailable (EmbeddingUnavailable); "
                               "using keyword search."}], verification_status="evidence_linked",
    )
    page.run()
    assert any("keyword fallback was used" in item.value for item in page.warning)
    source_button = next(button for button in page.button
                         if button.label == "Open source")
    source_button.click().run()
    assert not page.exception
    assert any("Indexed source location" in title.value for title in page.markdown)
    assert any("Submit design drawings" in item.value for item in page.text)
    page.session_state["last_answer"] = Answer(
        "Transformer amount", ["BOQ.xlsx | BOQ SAR!B2"],
        [{"name": "query_spreadsheet", "args": {"value": 1_000_000,
                                                 "currency": "SAR"}, "ok": True}],
        verification_status="evidence_linked",
    )
    page.run()
    next(button for button in page.button if button.label == "Open source").click().run()
    assert not page.exception
    assert any("Cited cell value: 1500000" in item.value for item in page.caption)
    page.session_state["last_answer"] = Answer(
        "The model reported insufficient evidence.", [],
        [{"name": "search_documents", "ok": True}],
        structured={"candidate_sources": ["Contract.pdf | page 1 | chunk 0"]},
        verification_status="unverified",
    )
    page.run()
    assert not page.exception
    assert any("Retrieved locations for manual review" in item.value
               for item in page.caption)
    next(button for button in page.button if button.label == "Open source").click().run()
    assert any("Submit design drawings" in item.value for item in page.text)
    monkeypatch.setattr("document_agent.agent.ask", lambda *_args, **_kwargs: Answer(
        "New independent answer", [], [], verification_status="unverified"))
    page.text_area[0].set_value("A new independent question").run()
    next(button for button in page.button if button.label == "Ask agent").click().run()
    assert not page.exception
    assert "open_source" not in page.session_state
    assert any("New independent answer" in item.value for item in page.markdown)
    assert not any("Indexed source location" in item.value for item in page.markdown)
    conn.close()
