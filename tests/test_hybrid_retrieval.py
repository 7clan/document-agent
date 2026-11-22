"""Hybrid indexing and retrieval tests run offline with a deterministic fake model."""
import json

from document_agent import hybrid
from document_agent.agent import _execute, _retrieval_audit
from document_agent.db import connect
from document_agent.tools import TOOL_SCHEMAS, get_evidence, search_documents


class FakeEncoder:
    def encode(self, texts, **kwargs):
        result = []
        for text in texts:
            t = text.casefold()
            if any(x in t for x in ("finalize", "finish", "completion", "deadline")):
                result.append([1., 0., 0.])
            elif any(x in t for x in ("electrical", "transformer", "cable")):
                result.append([0., 1., 0.])
            else:
                result.append([0., 0., 1.])
        return result


def seed():
    conn = connect(":memory:")
    for path, kind in (("Contract.pdf", "pdf"), ("BOQ.xlsx", "xlsx"),
                       ("Notes.docx", "docx")):
        conn.execute("INSERT INTO documents(path,kind,status) VALUES(?,?,'ready')",
                     (path, kind))
    ids = {row["path"]: row["id"] for row in conn.execute("SELECT id,path FROM documents")}
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES(?,?,?,?)",
                 (ids["Contract.pdf"], 1, 0, "Contractor shall finalize works on June 15."))
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES(?,?,?,?)",
                 (ids["Contract.pdf"], 2, 0, "Insurance renewed annually."))
    conn.execute("INSERT INTO word_blocks(document_id,ordinal,kind,location,section,text) "
                 "VALUES(?,?,?,?,?,?)", (ids["Notes.docx"], 1, "paragraph",
                 "paragraph 1", "", "Completion arrangements."))
    conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                 "VALUES(?,?,?,?)", (ids["BOQ.xlsx"], "Sheet1", 2,
                 json.dumps({"A": {"value": "Electrical transformer"},
                             "B": {"value": 1500000}})))
    conn.commit()
    return conn


def test_semantic_paraphrase_and_original_evidence(monkeypatch):
    conn = seed()
    monkeypatch.setenv("DOCUMENT_AGENT_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setattr(hybrid, "embedding_model", FakeEncoder)
    answer = search_documents(conn, "When is the completion deadline?", limit=4)
    assert answer["retrieval_mode"] == "hybrid"
    assert answer["semantic_matches"] >= 1
    citation = "Contract.pdf | page 1 | chunk 0"
    assert any(hit["citation"] == citation for hit in answer["results"])
    assert "June 15" in str(get_evidence(conn, citation))


def test_agent_search_uses_configured_mode_even_if_model_requests_another(monkeypatch):
    conn = seed()
    monkeypatch.setattr(hybrid, "embedding_model", FakeEncoder)
    schema = next(tool for tool in TOOL_SCHEMAS if tool["name"] == "search_documents")
    assert "mode" not in schema["parameters"]["properties"]

    monkeypatch.setenv("DOCUMENT_AGENT_RETRIEVAL_MODE", "hybrid")
    result = _execute(conn, "search_documents", {"query": "completion deadline",
                                                  "mode": "keyword"})
    assert result["retrieval_mode"] == "hybrid"
    assert result["semantic_matches"] > 0

    monkeypatch.setenv("DOCUMENT_AGENT_RETRIEVAL_MODE", "keyword")
    result = _execute(conn, "search_documents", {"query": "completion deadline",
                                                  "mode": "hybrid"})
    assert result.get("retrieval_mode", "keyword") == "keyword"


def test_incremental_updates_and_deletion():
    conn = seed()
    encoder = FakeEncoder()
    assert hybrid.sync_embeddings(conn, encoder=encoder, embedding_id="fake")["indexed"] == 4
    assert hybrid.sync_embeddings(conn, encoder=encoder, embedding_id="fake")["indexed"] == 0
    conn.execute("UPDATE passages SET text='Electrical cable' WHERE page=1")
    conn.commit()
    assert hybrid.sync_embeddings(conn, encoder=encoder, embedding_id="fake")["indexed"] == 1
    conn.execute("DELETE FROM documents WHERE path='Contract.pdf'")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM source_embeddings "
                        "WHERE citation LIKE 'Contract.pdf%'").fetchone()[0] == 0


def test_missing_model_falls_back_to_keyword(monkeypatch):
    conn = seed()
    monkeypatch.setenv("DOCUMENT_AGENT_RETRIEVAL_MODE", "hybrid")

    def unavailable():
        raise hybrid.EmbeddingUnavailable("missing offline model")

    monkeypatch.setattr(hybrid, "embedding_model", unavailable)
    output = search_documents(conn, "insurance")
    assert output["retrieval_mode"] == "keyword"
    assert output["retrieval_warning"]
    assert output["results"][0]["citation"] == "Contract.pdf | page 2 | chunk 0"


def test_retrieval_audit_distinguishes_real_hybrid_from_fallback():
    hybrid_result = {"retrieval_mode": "hybrid", "semantic_matches": 3}
    fallback_result = {"retrieval_mode": "keyword", "retrieval_warning":
                       "Semantic retrieval unavailable (EmbeddingUnavailable); using keyword search."}
    assert _retrieval_audit("search_documents", hybrid_result) == {
        "retrieval_mode": "hybrid", "semantic_matches": 3, "retrieval_warning": ""}
    assert _retrieval_audit("search_documents", fallback_result) == {
        "retrieval_mode": "keyword", "semantic_matches": 0,
        "retrieval_warning": fallback_result["retrieval_warning"]}
    assert _retrieval_audit("get_evidence", hybrid_result) == {}


def test_file_filter_preserved(monkeypatch):
    conn = seed()
    monkeypatch.setenv("DOCUMENT_AGENT_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setattr(hybrid, "embedding_model", FakeEncoder)
    output = search_documents(conn, "electrical", file="BOQ.xlsx")
    assert output["results"]
    assert all(item["citation"].startswith("BOQ.xlsx") for item in output["results"])


def test_rank_fusion_deduplicates():
    results = hybrid.fuse_results(
        [{"citation": "A", "score": 1}, {"citation": "B", "score": 1}],
        [{"citation": "B", "score": .9}, {"citation": "C", "score": .8}], 3)
    assert len(results) == 3
    assert {hit["citation"] for hit in results} == {"A", "B", "C"}


def test_spreadsheet_embedding_includes_source_headings_without_changing_evidence():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Prices.xlsx','xlsx','ready')")
    for number, values in ((1, {"A": "Reference", "B": "Work", "C": "Amount (SAR)"}),
                           (2, {"A": "DP-22", "B": "Feeder panel commissioning",
                                "C": 1100000})):
        conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                     "VALUES(1,'Base Selection',?,?)",
                     (number, json.dumps({col: {"value": value}
                                          for col, value in values.items()})))
    conn.commit()
    records = list(hybrid.source_records(conn))
    data = records[-1]
    assert "Worksheet Base Selection" in data["embedding_text"]
    assert "Work: Feeder panel commissioning" in data["embedding_text"]
    assert "Amount (SAR): 1100000" in data["embedding_text"]
    assert data["text"] == "A: DP-22 B: Feeder panel commissioning C: 1100000"
    assert get_evidence(conn, data["citation"])["row"]["B"] == "Feeder panel commissioning"


def test_strong_semantic_source_keeps_a_top_three_place():
    lexical = [{"citation": name, "score": 2} for name in ("A", "B", "C", "D")]
    semantic = [{"citation": "ROW", "score": .38, "semantic_similarity": .38}]
    output = hybrid.fuse_results(lexical, semantic, 3)
    assert [hit["citation"] for hit in output] == ["A", "B", "ROW"]
    weak = [{"citation": "ROW", "score": .25, "semantic_similarity": .25}]
    assert [hit["citation"] for hit in hybrid.fuse_results(lexical, weak, 3)] == [
        "A", "B", "C"]


def test_common_question_words_do_not_bury_semantic_spreadsheet_row(monkeypatch):
    class ConverterEncoder:
        def encode(self, texts, **kwargs):
            return [[1., 0.] if "inverter" in text.lower() or
                    "power converter" in text.lower() else [0., 1.]
                    for text in texts]

    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Items.xlsx','xlsx','ready')")
    conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                 "VALUES(1,'Costs',2,?)", (json.dumps({
                     "A": {"value": "AX-203"},
                     "B": {"value": "Power converter package"},
                     "C": {"value": 1200000},
                 }),))
    for index in range(3):
        name = f"Distractor{index}.pdf"
        conn.execute("INSERT INTO documents(path,kind,status) VALUES(?,'pdf','ready')",
                     (name,))
        conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                     "VALUES(?,?,0,'The unrelated project note.')", (index + 2, 1))
    conn.commit()
    monkeypatch.setattr(hybrid, "embedding_model", ConverterEncoder)

    query = "What did the inverter assembly cost?"
    assert not any(hit["citation"].startswith("Items.xlsx") for hit in
                   search_documents(conn, query, limit=3, mode="keyword")["results"])
    result = search_documents(conn, query, limit=3, mode="hybrid")
    assert result["retrieval_mode"] == "hybrid"
    assert result["results"][0]["citation"] == "Items.xlsx | Costs | row 2"


def test_hybrid_lexical_filter_keeps_exact_item_reference(monkeypatch):
    conn = seed()
    conn.execute("UPDATE sheet_rows SET cells_json=? WHERE row_num=2", (json.dumps({
        "A": {"value": "EL-103"}, "B": {"value": 890000},
    }),))
    conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                 "VALUES((SELECT id FROM documents WHERE path='BOQ.xlsx'),'Sheet1',3,?)",
                 (json.dumps({"A": {"value": "EL-1030"},
                              "B": {"value": 2400000}}),))
    conn.commit()
    monkeypatch.setattr(hybrid, "embedding_model", FakeEncoder)
    result = search_documents(conn, "What is the cost of EL-103?", mode="hybrid")
    assert result["results"]
    assert all(hit["citation"] != "BOQ.xlsx | Sheet1 | row 3"
               for hit in result["results"])
