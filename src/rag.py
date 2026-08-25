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

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS rag_documents (
    id          serial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    source      text NOT NULL,
    chunk_index integer NOT NULL,
    chunk       text NOT NULL,
    embedding   vector({EMBED_DIM}) NOT NULL,
    domain      text NOT NULL,
    project     text,
    source_ref  text,
    UNIQUE (source, chunk_index)
);
CREATE INDEX IF NOT EXISTS rag_documents_embedding_idx
    ON rag_documents USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS rag_documents_domain_idx ON rag_documents (domain);
CREATE INDEX IF NOT EXISTS rag_documents_project_idx ON rag_documents (project);
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

    conn = psycopg.connect(
        db_url
        or os.environ.get("RAG_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DB_URL
    )
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        # extension not created yet; init_store will, then re-register
        pass
    return conn


def init_store(conn) -> None:
    conn.execute(SCHEMA)
    conn.commit()
    # on a fresh database the adapter registration in connect() found no
    # vector type to register against -- now the extension exists, redo it
    from pgvector.psycopg import register_vector
    register_vector(conn)


def source_key(path) -> str:
    """
    The stable identity of a reference file: its path relative to the
    project root, POSIX-style, independent of the cwd you ran from.

    This has to be the *path* and not the basename. ingest_records
    deletes by source before inserting, so with basenames
    references/editing/notes.txt and references/lighting/notes.txt are
    one source that silently overwrites itself rather than two
    references -- which is exactly what a folder tree of references
    would produce. A file outside the project keeps its absolute path.
    """
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def ingest_records(records: list, client, conn) -> int:
    """
    records: [{"source": name, "text": full text, "domain": shelf,
    "project": optional, "source_ref": optional url/timestamp}]. domain
    is required -- it's the shelf label that keeps retrieval scoped,
    and nothing lands untagged. Each source's old chunks are deleted
    first, so re-ingesting an edited file replaces it instead of
    accumulating stale copies. Returns chunks written.
    """
    for record in records:
        if not record.get("domain"):
            raise ValueError(
                f"record '{record.get('source')}' has no domain -- "
                "every reference needs a shelf label"
            )
    written = 0
    for record in records:
        chunks = chunk_text(record["text"])
        if not chunks:
            continue
        vectors = embed_texts(chunks, client, task_type="RETRIEVAL_DOCUMENT")
        conn.execute("DELETE FROM rag_documents WHERE source = %s", (record["source"],))
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            conn.execute(
                "INSERT INTO rag_documents "
                "(source, chunk_index, chunk, embedding, domain, project, source_ref) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (record["source"], index, chunk, vector, record["domain"],
                 record.get("project"), record.get("source_ref")),
            )
            written += 1
    conn.commit()
    return written


def query(text: str, client, conn, k: int = 5,
          domain=None, project: Optional[str] = None) -> list:
    """
    Top-k chunks by cosine similarity, optionally scoped to one or more
    shelves (domain) or one project. This pairing is the pgvector payoff:
    semantic similarity and hard SQL filters in a single query.

    domain accepts a single string (one shelf) or a list/tuple/set of
    strings (any of several shelves) -- a caller like pitch.py grounds
    against both its brand and cinematography shelves in one query
    rather than needing two round trips whose results it would then
    have to merge and re-rank itself.
    """
    [vector] = embed_texts([text], client, task_type="RETRIEVAL_QUERY")
    filters, params = [], [vector]
    if isinstance(domain, (list, tuple, set)):
        if domain:
            filters.append("domain = ANY(%s)")
            params.append(list(domain))
    elif domain:
        filters.append("domain = %s")
        params.append(domain)
    if project:
        filters.append("project = %s")
        params.append(project)
    where_sql = (" WHERE " + " AND ".join(filters)) if filters else ""
    params.append(k)
    cursor = conn.execute(
        "SELECT source, chunk, domain, project, source_ref, "
        "embedding <=> %s::vector AS distance "
        f"FROM rag_documents{where_sql} ORDER BY distance LIMIT %s",
        params,
    )
    return [
        {"source": source, "chunk": chunk, "domain": row_domain,
         "project": row_project, "source_ref": source_ref,
         "score": round(1.0 - distance, 4)}
        for source, chunk, row_domain, row_project, source_ref, distance
        in cursor.fetchall()
    ]


def retrieve_references(text: str, k: int = 5, db_url: Optional[str] = None,
                        domain=None,
                        project: Optional[str] = None) -> dict:
    """
    Never raises. {"ok": True, "references": [...]} or
    {"ok": False, "references": [], "error": "..."} -- a missing key,
    package, or database degrades to an ungrounded pitch run, same
    contract as youtube.refresh_metrics_for_video. Deliberately does
    not load .env itself: the entry points do, and a library function
    that re-reads .env would un-do a test's environment on purpose.

    domain: same str | list/tuple/set | None contract as query().
    """
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        return {"ok": False, "references": [],
                "error": "GEMINI_API_KEY (or GOOGLE_API_KEY) not set"}
    try:
        conn = client = None
        conn = connect(db_url)
        client = make_client()
        return {"ok": True, "references": query(
            text, client, conn, k=k, domain=domain, project=project)}
    except Exception as e:
        return {"ok": False, "references": [], "error": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def list_sources(conn) -> list:
    """What's on the shelves: one row per ingested source."""
    cursor = conn.execute(
        "SELECT source, domain, project, COUNT(*), MAX(created_at) "
        "FROM rag_documents GROUP BY source, domain, project "
        "ORDER BY MAX(created_at) DESC"
    )
    return [
        {"source": source, "domain": domain, "project": project,
         "chunks": chunks, "added": added}
        for source, domain, project, chunks, added in cursor.fetchall()
    ]


def delete_source(conn, source: str) -> int:
    """Remove every chunk of one source. Returns rows removed."""
    cursor = conn.execute(
        "DELETE FROM rag_documents WHERE source = %s", (source,)
    )
    conn.commit()
    return cursor.rowcount


def fetch_by_sources(sources: list, db_url: Optional[str] = None) -> dict:
    """
    Exact-selection retrieval: every chunk of the given sources, in
    order -- no embedding call, no similarity ranking, because the
    selection already happened (a human picked these sources by name,
    e.g. off the /library list). This is the opt-in counterpart to
    query(): nothing grounds a run just by existing on a shelf anymore,
    only what's explicitly picked does.

    Never raises -- same contract as retrieve_references: a missing
    key, package, or database degrades to an ungrounded run, not a
    crash. Unknown/typo'd source names are silently absent from the
    result (not an error) -- the caller can't tell "wrong name" from
    "nothing on that shelf yet" without listing sources itself.
    """
    if not sources:
        return {"ok": True, "references": []}
    conn = None
    try:
        conn = connect(db_url)
        cursor = conn.execute(
            "SELECT source, chunk, domain, project, source_ref "
            "FROM rag_documents WHERE source = ANY(%s) "
            "ORDER BY source, chunk_index",
            (list(sources),),
        )
        references = [
            {"source": source, "chunk": chunk, "domain": domain,
             "project": project, "source_ref": source_ref}
            for source, chunk, domain, project, source_ref in cursor.fetchall()
        ]
        return {"ok": True, "references": references}
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


def load_manifest_records(manifest_path: Path) -> list:
    """
    Turn a checked-in {path, domain, project?, source_ref?} manifest
    (see evals/reference_library.json) into ingest_records() input.

    This is the single versioned source of truth for "what's on the
    shelves" -- one file both a human re-running an ingest by hand and
    CI's ephemeral eval-gate database read from, so the two can't drift
    out of sync with each other the way remembering N separate `rag
    ingest --domain ...` commands eventually would.
    """
    entries = json.loads(manifest_path.read_text())
    records = []
    for entry in entries:
        path = Path(entry["path"])
        records.append({
            "source": source_key(path), "text": path.read_text(),
            "domain": entry["domain"], "project": entry.get("project"),
            "source_ref": entry.get("source_ref"),
        })
    return records


def main(argv=None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="rag", description="pgvector reference library: ingest and query"
    )
    sub = parser.add_subparsers(dest="verb", required=True)
    ingest_p = sub.add_parser("ingest", help="(re-)ingest text files as references")
    ingest_p.add_argument("paths", nargs="+", type=Path)
    ingest_p.add_argument("--domain", required=True,
                          help="shelf label: cinematography, client_work, ...")
    ingest_p.add_argument("--project")
    ingest_p.add_argument("--source-ref", help="url / path / timestamp range")
    manifest_p = sub.add_parser(
        "ingest-manifest",
        help="(re-)ingest every file listed in a {path, domain} manifest, e.g. evals/reference_library.json",
    )
    manifest_p.add_argument("manifest", type=Path)
    query_p = sub.add_parser("query", help="retrieve the closest reference chunks")
    query_p.add_argument("text")
    query_p.add_argument("--k", type=int, default=5)
    query_p.add_argument("--domain")
    query_p.add_argument("--project")
    args = parser.parse_args(argv)

    # loud on purpose: when you run this command, the store is the point
    client = make_client()
    conn = connect()
    init_store(conn)

    if args.verb == "ingest":
        records = [
            {"source": source_key(p), "text": p.read_text(), "domain": args.domain,
             "project": args.project, "source_ref": args.source_ref}
            for p in args.paths
        ]
        written = ingest_records(records, client, conn)
        print(f"Ingested {len(records)} source(s), {written} chunk(s) "
              f"under domain '{args.domain}'")
    elif args.verb == "ingest-manifest":
        records = load_manifest_records(args.manifest)
        written = ingest_records(records, client, conn)
        by_domain: dict = {}
        for r in records:
            by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
        breakdown = ", ".join(f"{n} {d}" for d, n in sorted(by_domain.items()))
        print(f"Ingested {len(records)} source(s) ({breakdown}), {written} chunk(s) total")
    else:
        results = query(args.text, client, conn, k=args.k,
                        domain=args.domain, project=args.project)
        print(json.dumps(results, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
