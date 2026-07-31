#!/usr/bin/env python3
"""
Retrieval subsystem: a pgvector document store fed by Gemini embeddings.

Ingest reference material (brand notes, past scripts, writing you want
the pitches to sound like) once; at pitch time the manifest is used as
a query and the closest chunks come back as grounding references.

Storage is PostgreSQL + pgvector, deliberately separate from
data/pipeline.db: SQLite has no vector type, and the reference library
is rebuildable from its source files -- losing it costs a re-ingest,
not data. Embeddings are gemini-embedding-001 at 768 dimensions
(documents get RETRIEVAL_DOCUMENT, queries RETRIEVAL_QUERY -- the
model is trained asymmetrically and mixing them up quietly worsens
ranking).

The CLI (ingest/query) fails loudly -- there the store *is* the
deliverable. `retrieve_references` never raises -- for pitch.py the
library is an enhancement, and a missing Postgres must not stop a
pitch run.
"""
import argparse
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
EMBED_BATCH = 100
DEFAULT_DB_URL = "postgresql://localhost/zeropage"

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS rag_documents (
    id          serial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    source      text NOT NULL,
    chunk_index integer NOT NULL,
    chunk       text NOT NULL,
    embedding   vector({EMBED_DIM}) NOT NULL,
    UNIQUE (source, chunk_index)
);
CREATE INDEX IF NOT EXISTS rag_documents_embedding_idx
    ON rag_documents USING hnsw (embedding vector_cosine_ops);
"""


def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list:
    """
    Word-boundary chunks of at most max_chars, each starting with the
    tail of the previous one so a sentence cut at a seam still appears
    whole somewhere.
    """
    words = (text or "").split()
    if not words:
        return []
    chunks = []
    current: list = []
    length = 0
    for word in words:
        needed = len(word) + (1 if current else 0)
        if current and length + needed > max_chars:
            chunks.append(" ".join(current))
            # walk back whole words until the tail fits the overlap budget
            tail: list = []
            tail_len = 0
            for w in reversed(current):
                if tail_len + len(w) + (1 if tail else 0) > overlap:
                    break
                tail.insert(0, w)
                tail_len += len(w) + (1 if tail_len else 0)
            current = tail
            length = tail_len
            needed = len(word) + (1 if current else 0)
        current.append(word)
        length += needed
    if current:
        chunks.append(" ".join(current))
    return chunks


def embed_texts(texts: list, client, task_type: str = "RETRIEVAL_DOCUMENT") -> list:
    """One 768-dim vector per text, batched under the API's request cap."""
    vectors: list = []
    config = types.EmbedContentConfig(
        task_type=task_type, output_dimensionality=EMBED_DIM
    )
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        response = client.models.embed_content(
            model=EMBED_MODEL, contents=batch, config=config
        )
        vectors.extend(e.values for e in response.embeddings)
    return vectors


def make_client():
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    return genai.Client(api_key=api_key)


def connect(db_url: Optional[str] = None):
    """A psycopg connection with the pgvector adapter registered."""
    import psycopg
    from pgvector.psycopg import register_vector

    conn = psycopg.connect(db_url or os.environ.get("RAG_DATABASE_URL", DEFAULT_DB_URL))
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        # extension not created yet; init_store will, then re-register
        pass
    return conn


def init_store(conn) -> None:
    conn.execute(SCHEMA)
    conn.commit()


def ingest_records(records: list, client, conn) -> int:
    """
    records: [{"source": name, "text": full text}]. Each source's old
    chunks are deleted first, so re-ingesting an edited file replaces
    it instead of accumulating stale copies. Returns chunks written.
    """
    written = 0
    for record in records:
        chunks = chunk_text(record["text"])
        if not chunks:
            continue
        vectors = embed_texts(chunks, client, task_type="RETRIEVAL_DOCUMENT")
        conn.execute("DELETE FROM rag_documents WHERE source = %s", (record["source"],))
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            conn.execute(
                "INSERT INTO rag_documents (source, chunk_index, chunk, embedding) "
                "VALUES (%s, %s, %s, %s)",
                (record["source"], index, chunk, vector),
            )
            written += 1
    conn.commit()
    return written


def query(text: str, client, conn, k: int = 5) -> list:
    """Top-k chunks by cosine similarity: [{source, chunk, score}]."""
    [vector] = embed_texts([text], client, task_type="RETRIEVAL_QUERY")
    cursor = conn.execute(
        "SELECT source, chunk, embedding <=> %s::vector AS distance "
        "FROM rag_documents ORDER BY distance LIMIT %s",
        (vector, k),
    )
    return [
        {"source": source, "chunk": chunk, "score": round(1.0 - distance, 4)}
        for source, chunk, distance in cursor.fetchall()
    ]


def retrieve_references(text: str, k: int = 5, db_url: Optional[str] = None) -> dict:
    """
    Never raises. {"ok": True, "references": [...]} or
    {"ok": False, "references": [], "error": "..."} -- a missing key,
    package, or database degrades to an ungrounded pitch run, same
    contract as youtube.refresh_metrics_for_video. Deliberately does
    not load .env itself: the entry points do, and a library function
    that re-reads .env would un-do a test's environment on purpose.
    """
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        return {"ok": False, "references": [],
                "error": "GEMINI_API_KEY (or GOOGLE_API_KEY) not set"}
    try:
        conn = client = None
        conn = connect(db_url)
        client = make_client()
        return {"ok": True, "references": query(text, client, conn, k=k)}
    except Exception as e:
        return {"ok": False, "references": [], "error": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def format_references(references: list) -> str:
    """The numbered block pitch prompts embed. Empty in, empty out."""
    lines = []
    for number, ref in enumerate(references, start=1):
        lines.append(f"{number}. [{ref['source']}] {ref['chunk']}")
    return "\n".join(lines)


def main(argv=None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="rag", description="pgvector reference library: ingest and query"
    )
    sub = parser.add_subparsers(dest="verb", required=True)
    ingest_p = sub.add_parser("ingest", help="(re-)ingest text files as references")
    ingest_p.add_argument("paths", nargs="+", type=Path)
    query_p = sub.add_parser("query", help="retrieve the closest reference chunks")
    query_p.add_argument("text")
    query_p.add_argument("--k", type=int, default=5)
    args = parser.parse_args(argv)

    # loud on purpose: when you run this command, the store is the point
    client = make_client()
    conn = connect()
    init_store(conn)

    if args.verb == "ingest":
        records = [{"source": p.name, "text": p.read_text()} for p in args.paths]
        written = ingest_records(records, client, conn)
        print(f"Ingested {len(records)} source(s), {written} chunk(s)")
    else:
        results = query(args.text, client, conn, k=args.k)
        print(json.dumps(results, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
