"""
Copy rag_documents from the local pgvector Postgres into Supabase.

    venv/bin/python ops/migrate_rag_to_supabase.py \
        --from "$RAG_DATABASE_URL" \
        --to   "postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres"

Runs from the Mac, because the source is localhost. Idempotent: rows are
upserted on (source, chunk_index), so re-running after a partial copy just
fills the gap. Ids are preserved and the sequence is bumped past them so
the app's next insert does not collide. Nothing is written to --from.

Backlog #14, move one: after this succeeds, RAG_DATABASE_URL in .env points
at Supabase and the docker-compose / port-5433 Postgres can be stopped.
"""
import argparse
import sys

import psycopg
from pgvector.psycopg import register_vector

sys.path.insert(0, ".")
from src import rag  # noqa: E402  -- one schema, defined in exactly one place

BATCH = 200
COLS = ("id", "created_at", "source", "chunk_index", "chunk",
        "embedding", "domain", "project", "source_ref")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="local RAG url")
    ap.add_argument("--to", dest="dst", required=True, help="Supabase url")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = psycopg.connect(args.src)
    register_vector(src)
    dst = rag.connect(args.dst)
    rag.init_store(dst)          # CREATE EXTENSION vector + table + indexes
    register_vector(dst)

    total = src.execute("SELECT count(*) FROM rag_documents").fetchone()[0]
    before = dst.execute("SELECT count(*) FROM rag_documents").fetchone()[0]
    print(f"source rows: {total}   target rows before: {before}")
    if args.dry_run:
        return

    sel = f"SELECT {', '.join(COLS)} FROM rag_documents ORDER BY id"
    ins = (f"INSERT INTO rag_documents ({', '.join(COLS)}) "
           f"VALUES ({', '.join('%s' for _ in COLS)}) "
           "ON CONFLICT (source, chunk_index) DO UPDATE SET "
           "chunk = EXCLUDED.chunk, embedding = EXCLUDED.embedding, "
           "domain = EXCLUDED.domain, project = EXCLUDED.project, "
           "source_ref = EXCLUDED.source_ref")
    done = 0
    with src.cursor(name="rag_copy") as cur:   # server-side: don't load 768-d vectors all at once
        cur.itersize = BATCH
        cur.execute(sel)
        batch = []
        for row in cur:
            batch.append(row)
            if len(batch) >= BATCH:
                dst.cursor().executemany(ins, batch)
                dst.commit()
                done += len(batch)
                print(f"  {done}/{total}", end="\r", flush=True)
                batch = []
        if batch:
            dst.cursor().executemany(ins, batch)
            dst.commit()
            done += len(batch)
    dst.execute("SELECT setval('rag_documents_id_seq', "
                "(SELECT COALESCE(max(id), 1) FROM rag_documents))")
    dst.commit()

    after = dst.execute("SELECT count(*) FROM rag_documents").fetchone()[0]
    print(f"\ncopied {done}; target rows after: {after}")
    if after < total:
        print("target has fewer rows than source -- rerun", file=sys.stderr)
        sys.exit(1)
    for d, n in dst.execute("SELECT domain, count(*) FROM rag_documents "
                            "GROUP BY 1 ORDER BY 1"):
        print(f"  {d:<20} {n}")


if __name__ == "__main__":
    main()
