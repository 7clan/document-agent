"""Local semantic embeddings, incremental SQLite cache and hybrid ranking.

Embeddings locate source passages; they never verify facts or compute BOQ totals.
Models run locally, and downloads are disabled unless explicitly enabled.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingUnavailable(RuntimeError):
    """The optional local embedding model could not be used."""


def model_id() -> str:
    name = os.getenv("DOCUMENT_AGENT_EMBEDDING_MODEL", DEFAULT_MODEL).strip()
    revision = os.getenv("DOCUMENT_AGENT_EMBEDDING_REVISION", "").strip()
    return f"{name}@{revision}" if revision else name


@lru_cache(maxsize=3)
def _load_model(name: str, revision: str, allow_download: bool) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingUnavailable('Install: pip install -e ".[embeddings]"') from exc
    options: dict[str, Any] = {
        "local_files_only": not allow_download, "trust_remote_code": False
    }
    if revision:
        options["revision"] = revision
    try:
        return SentenceTransformer(name, **options)
    except Exception as exc:
        raise EmbeddingUnavailable(
            "Model not cached locally. To download explicitly, set "
            "DOCUMENT_AGENT_EMBEDDING_ALLOW_DOWNLOAD=1 for the first run."
        ) from exc


def embedding_model() -> Any:
    return _load_model(
        os.getenv("DOCUMENT_AGENT_EMBEDDING_MODEL", DEFAULT_MODEL).strip(),
        os.getenv("DOCUMENT_AGENT_EMBEDDING_REVISION", "").strip(),
        os.getenv("DOCUMENT_AGENT_EMBEDDING_ALLOW_DOWNLOAD", "0") == "1",
    )


def source_records(conn: sqlite3.Connection, file: str = "") -> Iterator[dict[str, Any]]:
    """Read records using the same citation format as get_evidence."""
    where = " AND (?='' OR d.path=?)"
    args = (file, file)
    sql = ("SELECT d.id,d.path,p.page,p.chunk,p.text FROM passages p "
           "JOIN documents d ON d.id=p.document_id WHERE d.status='ready'"
           + where + " ORDER BY d.path,p.page,p.chunk")
    for row in conn.execute(sql, args):
        text = row["text"]
        yield {"document_id": row["id"],
               "citation": f"{row['path']} | page {row['page']} | chunk {row['chunk']}",
               "text": text, "preview": text[:650], "preview_only": len(text) > 650}

    sql = ("SELECT d.id,d.path,w.location,w.section,w.text FROM word_blocks w "
           "JOIN documents d ON d.id=w.document_id WHERE d.status='ready'"
           + where + " ORDER BY d.path,w.ordinal")
    for row in conn.execute(sql, args):
        text = f"{row['section']}: {row['text']}" if row["section"] else row["text"]
        yield {"document_id": row["id"],
               "citation": f"{row['path']} | {row['location']}",
               "text": text, "preview": text[:650], "preview_only": len(text) > 650}

    sql = ("SELECT d.id,d.path,s.sheet,s.row_num,s.cells_json FROM sheet_rows s "
           "JOIN documents d ON d.id=s.document_id WHERE d.status='ready'"
           + where + " ORDER BY d.path,s.sheet,s.row_num")
    for row in conn.execute(sql, args):
        cells = json.loads(row["cells_json"])
        values = {key: entry.get("value") for key, entry in cells.items()}
        text = " ".join(f"{key}: {value}" for key, value in values.items()
                        if value is not None)
        if text.strip():
            yield {"document_id": row["id"],
                   "citation": f"{row['path']} | {row['sheet']} | row {row['row_num']}",
                   "text": text[:3000], "preview": values, "preview_only": False}


def _normalized(values: Any) -> list[float]:
    vector = [float(value) for value in values]
    if not vector or not all(math.isfinite(x) for x in vector):
        raise ValueError("Invalid embedding vector")
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise ValueError("Zero-magnitude embedding vector")
    return [x / norm for x in vector]


def _encode(encoder: Any, texts: list[str]) -> list[list[float]]:
    vectors = encoder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    if len(vectors) != len(texts):
        raise ValueError("Embedding count mismatch")
    return [_normalized(v) for v in vectors]


def sync_embeddings(
    conn: sqlite3.Connection, *, encoder: Any | None = None,
    embedding_id: str | None = None, batch_size: int = 32,
) -> dict[str, int]:
    """Reuse unchanged vectors; update altered content and prune deleted citations."""
    encoder = embedding_model() if encoder is None else encoder
    embedding_id = model_id() if embedding_id is None else embedding_id
    if not embedding_id:
        raise ValueError("Embedding model ID is empty")
    batch_size = min(max(int(batch_size), 1), 128)
    cached = {row["citation"]: row["content_sha256"] for row in conn.execute(
        "SELECT citation,content_sha256 FROM source_embeddings WHERE model_id=?",
        (embedding_id,),
    )}
    sources = list(source_records(conn))
    seen = {source["citation"] for source in sources}
    changed = []
    for source in sources:
        digest = hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
        if cached.get(source["citation"]) != digest:
            changed.append((source, digest))
    indexed = 0
    for start in range(0, len(changed), batch_size):
        batch = changed[start:start + batch_size]
        vectors = _encode(encoder, [source["text"] for source, _ in batch])
        with conn:
            for (source, digest), vector in zip(batch, vectors):
                conn.execute(
                    "INSERT INTO source_embeddings"
                    "(document_id,citation,content_sha256,model_id,dimensions,vector_json) "
                    "VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(citation,model_id) DO UPDATE SET "
                    "document_id=excluded.document_id,"
                    "content_sha256=excluded.content_sha256,"
                    "dimensions=excluded.dimensions,vector_json=excluded.vector_json",
                    (source["document_id"], source["citation"], digest,
                     embedding_id, len(vector), json.dumps(vector)),
                )
        indexed += len(batch)
    removed = 0
    with conn:
        for citation in cached:
            if citation not in seen:
                conn.execute("DELETE FROM source_embeddings WHERE citation=? AND model_id=?",
                             (citation, embedding_id))
                removed += 1
    return {"indexed": indexed, "unchanged": len(sources) - indexed, "removed": removed}


def semantic_search(
    conn: sqlite3.Connection, query: str, *, limit: int = 20, file: str = "",
    encoder: Any | None = None, embedding_id: str | None = None,
    min_similarity: float = 0.22,
) -> list[dict[str, Any]]:
    """Retrieve similar, citation-backed records; never fabricate source locations."""
    if not query.strip():
        return []
    encoder = embedding_model() if encoder is None else encoder
    embedding_id = model_id() if embedding_id is None else embedding_id
    sync_embeddings(conn, encoder=encoder, embedding_id=embedding_id)
    question = _encode(encoder, [query])[0]
    sources = {source["citation"]: source for source in source_records(conn, file)}
    sql = (
        "SELECT e.citation,e.dimensions,e.vector_json FROM source_embeddings e "
        "JOIN documents d ON d.id=e.document_id WHERE e.model_id=? AND d.status='ready' "
        "AND (?='' OR d.path=?) ORDER BY e.citation"
    )
    scored = []
    for row in conn.execute(sql, (embedding_id, file, file)):
        if row["citation"] not in sources or row["dimensions"] != len(question):
            continue
        vector = json.loads(row["vector_json"])
        if len(vector) != len(question):
            continue
        similarity = sum(float(a) * b for a, b in zip(vector, question))
        if math.isfinite(similarity) and similarity >= min_similarity:
            scored.append((similarity, row["citation"]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    output = []
    for similarity, citation in scored[:min(max(int(limit), 1), 100)]:
        source = sources[citation]
        output.append({
            "citation": citation, "preview": source["preview"],
            "score": round(similarity, 5), "preview_only": source["preview_only"],
            "semantic_similarity": round(similarity, 5),
        })
    return output


def fuse_results(
    lexical: list[dict[str, Any]],
    semantic: list[dict[str, Any]], limit: int,
) -> list[dict[str, Any]]:
    """Reciprocal rank fusion; exact keyword results receive double weight."""
    hits: dict[str, dict[str, Any]] = {}
    ranks: dict[str, float] = {}
    for weight, results in ((2.0, lexical), (1.0, semantic)):
        for rank, hit in enumerate(results, start=1):
            citation = hit["citation"]
            hits.setdefault(citation, dict(hit))
            ranks[citation] = ranks.get(citation, 0.0) + weight / (60 + rank)
            if "semantic_similarity" in hit:
                hits[citation]["semantic_similarity"] = hit["semantic_similarity"]
    for citation, hit in hits.items():
        hit["fusion_score"] = round(ranks[citation], 8)
    ordered = sorted(hits.values(),
                     key=lambda hit: (-ranks[hit["citation"]], hit["citation"]))
    return ordered[:limit]
