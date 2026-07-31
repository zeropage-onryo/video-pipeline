"""
Tests for src/rag.py -- the pgvector + Gemini retrieval subsystem.

Same split as promptgen: the pure parts (chunking, SQL parameter
shapes, result shaping, degradation) are tested directly against
fakes; the two thin edges (a real psycopg connection, a real Gemini
embedding call) are not reachable from tests -- conftest.py blocks
sockets -- so everything here runs offline.
"""
from types import SimpleNamespace

import pytest

from src import rag

# ---------- chunk_text ----------

def test_short_text_is_a_single_chunk():
    assert rag.chunk_text("a small note") == ["a small note"]


def test_empty_text_yields_no_chunks():
    assert rag.chunk_text("") == []
    assert rag.chunk_text("   \n  ") == []


def test_long_text_is_split_with_overlap():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = rag.chunk_text(text, max_chars=200, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # overlap: consecutive chunks share text, so no seam is ever lost
    for a, b in zip(chunks, chunks[1:]):
        assert a[-10:] in a and b[:10] in text
    # nothing dropped: every word survives somewhere
    joined = " ".join(chunks)
    assert all(f"word{i}" in joined for i in range(500))


# ---------- embeddings ----------

class FakeEmbedClient:
    """Records embed_content calls, returns constant-length vectors."""

    def __init__(self):
        self.calls = []
        outer = self

        class _Models:
            def embed_content(self, *, model, contents, config):
                outer.calls.append(
                    {"model": model, "contents": list(contents), "config": config}
                )
                return SimpleNamespace(
                    embeddings=[
                        SimpleNamespace(values=[0.1] * rag.EMBED_DIM)
                        for _ in contents
                    ]
                )

        self.models = _Models()


def test_embed_texts_returns_one_vector_per_text():
    client = FakeEmbedClient()
    vectors = rag.embed_texts(["one", "two"], client)
    assert len(vectors) == 2
    assert all(len(v) == rag.EMBED_DIM for v in vectors)


def test_embed_texts_sets_task_type_and_dimensionality():
    client = FakeEmbedClient()
    rag.embed_texts(["doc"], client, task_type="RETRIEVAL_QUERY")
    config = client.calls[0]["config"]
    assert config.task_type == "RETRIEVAL_QUERY"
    assert config.output_dimensionality == rag.EMBED_DIM


def test_embed_texts_batches_large_inputs():
    client = FakeEmbedClient()
    rag.embed_texts([f"t{i}" for i in range(250)], client)
    assert len(client.calls) == 3          # 100 + 100 + 50
    assert len(client.calls[0]["contents"]) == 100


# ---------- the store (fake connection) ----------

class FakeConn:
    """Captures executed SQL; serves canned rows to fetchall()."""

    def __init__(self, rows=None):
        self.executed = []
        self.rows = rows or []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        conn = self

        class _Cursor:
            def fetchall(self):
                return conn.rows

        return _Cursor()

    def commit(self):
        pass


def test_ingest_records_replaces_a_source_then_inserts_each_chunk():
    client = FakeEmbedClient()
    conn = FakeConn()
    n = rag.ingest_records(
        [{"source": "brief.txt", "text": "a small brand note",
          "domain": "personal_brand"}], client, conn
    )
    assert n == 1
    deletes = [s for s, _ in conn.executed if s.startswith("DELETE")]
    inserts = [(s, p) for s, p in conn.executed if s.startswith("INSERT")]
    assert len(deletes) == 1               # re-ingesting a file can't duplicate it
    assert len(inserts) == 1
    _, params = inserts[0]
    assert params[0] == "brief.txt"        # source
    assert params[1] == 0                  # chunk_index
    assert params[2] == "a small brand note"
    assert len(params[3]) == rag.EMBED_DIM
    assert params[4] == "personal_brand"   # domain: the shelf label
    assert params[5] is None               # project
    assert params[6] is None               # source_ref


def test_ingest_refuses_an_untagged_record():
    # domain is the shelf label; nothing lands untagged
    with pytest.raises(ValueError):
        rag.ingest_records(
            [{"source": "brief.txt", "text": "words"}], FakeEmbedClient(), FakeConn()
        )


QUERY_ROW = ("brief.txt", "the chunk", "personal_brand", None, None, 0.25)


def test_query_shapes_rows_and_converts_distance_to_score():
    client = FakeEmbedClient()
    conn = FakeConn(rows=[QUERY_ROW])
    results = rag.query("what is the brand", client, conn, k=3)
    assert results == [{"source": "brief.txt", "chunk": "the chunk",
                        "domain": "personal_brand", "project": None,
                        "source_ref": None, "score": 0.75}]
    # the query embedding must use the query task type, not the doc one
    assert client.calls[0]["config"].task_type == "RETRIEVAL_QUERY"


def test_query_without_scope_has_no_where_clause():
    conn = FakeConn(rows=[])
    rag.query("anything", FakeEmbedClient(), conn, k=3)
    sql, params = conn.executed[0]
    assert "WHERE" not in sql
    assert len(params) == 2                # vector, limit


def test_query_scopes_by_domain_and_project_with_parameters():
    conn = FakeConn(rows=[])
    rag.query("anything", FakeEmbedClient(), conn, k=3,
              domain="cinematography", project="juno_promo")
    sql, params = conn.executed[0]
    assert "WHERE" in sql
    assert "domain = %s" in sql
    assert "project = %s" in sql
    assert "cinematography" in params      # parameterized, never interpolated
    assert "juno_promo" in params


# ---------- retrieve_references never raises ----------

def test_retrieve_references_degrades_without_an_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = rag.retrieve_references("anything")
    assert result["ok"] is False
    assert result["references"] == []
    assert "key" in result["error"].lower()


def test_retrieve_references_degrades_when_postgres_is_down(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def boom(db_url=None):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(rag, "connect", boom)
    result = rag.retrieve_references("anything")
    assert result["ok"] is False
    assert result["references"] == []


def test_retrieve_references_happy_path_uses_the_store(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    conn = FakeConn(rows=[("notes.md", "a reference", "cinematography", None, None, 0.1)])
    monkeypatch.setattr(rag, "connect", lambda db_url=None: conn)
    monkeypatch.setattr(rag, "make_client", lambda: FakeEmbedClient())
    result = rag.retrieve_references("query text", k=1)
    assert result["ok"] is True
    assert result["references"][0]["source"] == "notes.md"


def test_retrieve_references_passes_the_domain_scope_through(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    conn = FakeConn(rows=[])
    monkeypatch.setattr(rag, "connect", lambda db_url=None: conn)
    monkeypatch.setattr(rag, "make_client", lambda: FakeEmbedClient())
    rag.retrieve_references("query text", k=1, domain="cinematography")
    sql, params = conn.executed[0]
    assert "domain = %s" in sql
    assert "cinematography" in params


# ---------- reference formatting for prompts ----------

def test_format_references_is_empty_safe():
    assert rag.format_references([]) == ""


def test_format_references_numbers_and_attributes():
    text = rag.format_references(
        [
            {"source": "brief.txt", "chunk": "keep it dry", "score": 0.9},
            {"source": "notes.md", "chunk": "one image, one turn", "score": 0.8},
        ]
    )
    assert "1." in text and "2." in text
    assert "brief.txt" in text and "keep it dry" in text


def test_module_rejects_unknown_cli_verbs():
    with pytest.raises(SystemExit):
        rag.main(["dance"])


def test_cli_ingest_requires_a_domain():
    with pytest.raises(SystemExit):
        rag.main(["ingest", "some.txt"])   # no --domain: refuse untagged rows
