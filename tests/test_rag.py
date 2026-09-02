"""
Tests for src/rag.py -- the pgvector + Gemini retrieval subsystem.

Same split as promptgen: the pure parts (chunking, SQL parameter
shapes, result shaping, degradation) are tested directly against
fakes; the two thin edges (a real psycopg connection, a real Gemini
embedding call) are not reachable from tests -- conftest.py blocks
sockets -- so everything here runs offline.
"""
import json
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


# ---------- a spent quota is waited out, not lost (2026-09-02) ----------
#
# gemini-embedding is limited PER MINUTE, and the nightly walk fires 16 runs
# back to back -- so the ceiling gets hit by bunching and clears in under a
# minute. Two runs in morning_prompts.log lost their grounding to a 429 that
# would have succeeded seconds later, and an ungrounded concept looks exactly
# like a grounded one from outside.

QUOTA_429 = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
             "'Quota exceeded for "
             "aiplatform.googleapis.com/global_embed_content_requests_per_"
             "minute_per_base_model', 'status': 'RESOURCE_EXHAUSTED'}}")


class FlakyEmbedClient(FakeEmbedClient):
    """Raises `error` on the first `fail_times` calls, then behaves."""

    def __init__(self, fail_times, error=QUOTA_429):
        super().__init__()
        self.remaining = fail_times
        self.attempts = 0
        outer = self
        good = self.models

        class _Models:
            def embed_content(self, **kw):
                outer.attempts += 1
                if outer.remaining > 0:
                    outer.remaining -= 1
                    raise RuntimeError(error)
                return good.embed_content(**kw)

        self.models = _Models()


def test_a_spent_embedding_quota_is_retried(monkeypatch):
    monkeypatch.setattr(rag.time, "sleep", lambda s: None)
    client = FlakyEmbedClient(fail_times=2)

    vectors = rag.embed_texts(["one", "two"], client)

    assert len(vectors) == 2               # the grounding survives
    assert client.attempts == 3            # two 429s, then the real call


def test_the_429s_own_cooldown_is_honoured(monkeypatch):
    """A 429 states how long to wait. Guessing under it earns another one."""
    waited = []
    monkeypatch.setattr(rag.time, "sleep", waited.append)
    client = FlakyEmbedClient(
        fail_times=1, error="429 RESOURCE_EXHAUSTED, retry in 31.5s")

    rag.embed_texts(["one"], client)

    assert waited and waited[0] >= 31.5


def test_a_real_failure_is_not_retried(monkeypatch):
    """Retrying a bad key just spends the same failure six times."""
    monkeypatch.setattr(rag.time, "sleep", lambda s: None)
    client = FlakyEmbedClient(fail_times=1, error="401 PERMISSION_DENIED")

    with pytest.raises(RuntimeError):
        rag.embed_texts(["one"], client)
    assert client.attempts == 1


def test_the_budget_is_finite_and_then_it_raises(monkeypatch):
    """After actually waiting, an ungrounded run is the right outcome --
    retrieve_references catches this and degrades."""
    monkeypatch.setattr(rag.time, "sleep", lambda s: None)
    client = FlakyEmbedClient(fail_times=99)

    with pytest.raises(RuntimeError):
        rag.embed_texts(["one"], client)
    assert client.attempts == rag.gemini_utils.MAX_RETRIES


def test_a_tripped_batch_does_not_re_embed_the_ones_that_landed(monkeypatch):
    """A long ingest that trips on batch three resumes at batch three."""
    monkeypatch.setattr(rag.time, "sleep", lambda s: None)
    client = FakeEmbedClient()
    calls = {"n": 0}
    real = client.models.embed_content

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 3:                # first attempt at batch 3
            raise RuntimeError(QUOTA_429)
        return real(**kw)

    client.models.embed_content = flaky

    vectors = rag.embed_texts([f"t{i}" for i in range(250)], client)

    assert len(vectors) == 250
    assert calls["n"] == 4                 # 3 batches + 1 retry, not 3 + 3


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
            rowcount = len(conn.rows)

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


# ---------- source_key: the identity ingest deletes by ----------

def test_source_key_is_the_path_relative_to_the_project_root():
    assert rag.source_key(rag.PROJECT_ROOT / "prompts" / "brief.txt") == "prompts/brief.txt"


def test_source_key_is_independent_of_how_the_path_was_written():
    """Same file, three spellings, one identity -- otherwise re-ingesting
    from a different cwd would duplicate a source instead of replacing it."""
    direct = rag.PROJECT_ROOT / "prompts" / "brief.txt"
    indirect = rag.PROJECT_ROOT / "src" / ".." / "prompts" / "brief.txt"
    assert rag.source_key(direct) == rag.source_key(indirect) == "prompts/brief.txt"


def test_source_key_distinguishes_same_name_in_different_folders():
    """The whole point: a folder tree of references must not collapse
    into one source that overwrites itself on every ingest."""
    editing = rag.source_key(rag.PROJECT_ROOT / "references" / "editing" / "notes.txt")
    lighting = rag.source_key(rag.PROJECT_ROOT / "references" / "lighting" / "notes.txt")
    assert editing != lighting
    assert editing == "references/editing/notes.txt"


def test_source_key_keeps_an_outside_file_absolute():
    key = rag.source_key("/etc/hosts")
    assert key.startswith("/")


def test_load_manifest_records_reads_paths_domains_and_text(tmp_path):
    """
    The manifest is the single versioned source of truth for what's on
    the shelves (evals/reference_library.json) -- this is the
    regression test that reading it produces exactly what
    ingest_records expects: source, text, domain, and the optional
    project/source_ref carried through untouched.
    """
    manifest_path = tmp_path / "library.json"
    manifest_path.write_text(json.dumps([
        {"path": "prompts/brief.txt", "domain": "personal_brand"},
        {"path": "prompts/settings.txt", "domain": "cinematography",
         "project": "zpf", "source_ref": "hand-written"},
    ]))

    records = rag.load_manifest_records(manifest_path)

    assert [r["source"] for r in records] == ["prompts/brief.txt", "prompts/settings.txt"]
    assert records[0]["domain"] == "personal_brand"
    assert records[0]["project"] is None
    assert records[0]["source_ref"] is None
    assert "Zero Page Films" in records[0]["text"]
    assert records[1]["domain"] == "cinematography"
    assert records[1]["project"] == "zpf"
    assert records[1]["source_ref"] == "hand-written"


def test_two_same_named_files_in_different_folders_delete_independently():
    """Regression: with basenames, ingesting the second file deleted the
    first one's chunks, because DELETE keys off source."""
    conn = FakeConn()
    rag.ingest_records(
        [{"source": "references/editing/notes.txt", "text": "cut on motion",
          "domain": "editing"},
         {"source": "references/lighting/notes.txt", "text": "one source, hard",
          "domain": "cinematography"}],
        FakeEmbedClient(), conn,
    )
    deleted = [p[0] for s, p in conn.executed if s.startswith("DELETE")]
    assert deleted == ["references/editing/notes.txt", "references/lighting/notes.txt"]
    inserted = [p[0] for s, p in conn.executed if s.startswith("INSERT")]
    assert set(inserted) == {"references/editing/notes.txt",
                             "references/lighting/notes.txt"}


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


def test_query_scopes_by_multiple_domains_with_a_single_any_call():
    """A caller like pitch.py grounds against several shelves at once
    (brand + cinematography, never marketing/ai_prompting) -- this has
    to be one query with one ranking, not several merged client-side."""
    conn = FakeConn(rows=[])
    rag.query("anything", FakeEmbedClient(), conn, k=3,
              domain=("personal_brand", "cinematography"))
    sql, params = conn.executed[0]
    assert "domain = ANY(%s)" in sql
    assert "domain = %s" not in sql        # the single-value form, not used here
    assert ["personal_brand", "cinematography"] in params


def test_query_with_an_empty_domain_list_has_no_where_clause():
    """[] and None both mean "no scope" -- an empty collection must not
    silently become a WHERE domain = ANY('{}') that matches nothing."""
    conn = FakeConn(rows=[])
    rag.query("anything", FakeEmbedClient(), conn, k=3, domain=())
    sql, params = conn.executed[0]
    assert "WHERE" not in sql
    assert len(params) == 2


# ---------- provenance: a label is not a fence ----------

def test_query_with_a_preferred_project_fetches_a_wider_pool_and_resorts():
    """Own neighbourhood first, nothing excluded: the pool is k x
    PREFER_POOL rows by plain distance (so the HNSW index still serves
    it), re-sorted with the boost off matching rows' distance, top k
    kept. The returned score stays the raw similarity."""
    conn = FakeConn(rows=[
        ("theirs.md", "a stranger's lesson", "denials", "pilot", None, 0.20),
        ("mine.md", "my own lesson", "denials", "zeropage", None, 0.22),
    ])
    results = rag.query("q", FakeEmbedClient(), conn, k=3, domain="denials",
                        prefer_project="zeropage")
    sql, params = conn.executed[0]
    assert "ORDER BY distance - CASE WHEN project = %s THEN %s ELSE 0 END" in sql
    assert "FROM (" in sql and "LIMIT %s" in sql
    assert "project = %s" not in sql.split("FROM (")[1].split(") AS pool")[0]  # no fence inside
    assert params[-3:] == ["zeropage", rag.PROJECT_BOOST, 3]
    assert 3 * rag.PREFER_POOL in params                       # the wider pool
    assert [r["own"] for r in results] == [False, True]
    assert [r["score"] for r in results] == [0.8, 0.78]         # raw, never boosted


def test_query_without_a_preference_is_the_query_it_always_was():
    conn = FakeConn(rows=[])
    rag.query("anything", FakeEmbedClient(), conn, k=3, prefer_project=None)
    sql, params = conn.executed[0]
    assert "CASE WHEN" not in sql and "FROM (" not in sql
    assert len(params) == 2


def test_the_boost_is_a_tie_break_not_a_fence():
    """A clearly better stranger's row still wins; an equal own row is
    preferred; a NULL-labelled row is retrieved like any other."""
    assert 0 < rag.PROJECT_BOOST < 0.1
    # the ordering expression, evaluated the way Postgres would
    def key(distance, project, mine="zeropage"):
        return distance - (rag.PROJECT_BOOST if project == mine else 0)
    assert key(0.30, "pilot") < key(0.40, "zeropage")          # much better stranger wins
    assert key(0.30, "zeropage") < key(0.29, "pilot")          # near-tie goes to mine
    assert key(0.30, None) == 0.30                              # unlabelled: untouched


def test_label_domains_stamps_only_unlabelled_rows_by_default():
    conn = FakeConn(rows=[])
    rag.label_domains(conn, "zeropage", ["denials", "assets"])
    sql, params = conn.executed[0]
    assert sql.startswith("UPDATE rag_documents SET project = %s WHERE domain = ANY(%s)")
    assert "project IS NULL" in sql
    assert params == ["zeropage", ["denials", "assets"]]
    conn = FakeConn(rows=[])
    rag.label_domains(conn, None, "assets", only_unlabelled=False)
    sql, params = conn.executed[0]
    assert "project IS NULL" not in sql and params == [None, ["assets"]]
    assert rag.label_domains(FakeConn(), "x", []) == 0


def test_retrieve_references_passes_the_preference_through(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    conn = FakeConn(rows=[])
    monkeypatch.setattr(rag, "connect", lambda db_url=None: conn)
    monkeypatch.setattr(rag, "make_client", lambda: FakeEmbedClient())
    rag.retrieve_references("query text", k=2, domain="denials", prefer_project="zeropage")
    sql, params = conn.executed[0]
    assert "CASE WHEN project = %s" in sql and "zeropage" in params


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


def test_retrieve_references_passes_a_multi_domain_scope_through(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    conn = FakeConn(rows=[])
    monkeypatch.setattr(rag, "connect", lambda db_url=None: conn)
    monkeypatch.setattr(rag, "make_client", lambda: FakeEmbedClient())
    rag.retrieve_references("query text", k=1, domain=("personal_brand", "cinematography"))
    sql, params = conn.executed[0]
    assert "domain = ANY(%s)" in sql
    assert ["personal_brand", "cinematography"] in params


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


# ---------- store browsing (for the /library screen) ----------

def test_list_sources_groups_and_shapes():
    conn = FakeConn(rows=[
        ("brief.txt", "personal_brand", None, 1, "2026-07-31"),
        ("edit_prompt.txt", "editing", None, 4, "2026-07-31"),
    ])
    sources = rag.list_sources(conn)
    sql, _ = conn.executed[0]
    assert "GROUP BY" in sql
    assert sources[0] == {"source": "brief.txt", "domain": "personal_brand",
                          "project": None, "chunks": 1, "added": "2026-07-31"}


def test_delete_source_is_parameterized():
    conn = FakeConn()
    rag.delete_source(conn, "brief.txt")
    sql, params = conn.executed[0]
    assert sql.startswith("DELETE FROM rag_documents")
    assert params == ("brief.txt",)


def test_module_rejects_unknown_cli_verbs():
    with pytest.raises(SystemExit):
        rag.main(["dance"])


def test_cli_ingest_requires_a_domain():
    with pytest.raises(SystemExit):
        rag.main(["ingest", "some.txt"])   # no --domain: refuse untagged rows
