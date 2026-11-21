"""Hybrid indexing and retrieval tests run offline with a deterministic fake model."""
import json

from document_agent import hybrid
from document_agent.agent import _retrieval_audit
from document_agent.db import connect
from document_agent.tools import get_evidence, search_documents


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
