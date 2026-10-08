"""
The spend holes (docs/tasks/task-spend-holes-and-credits.md, 1c and 1d).

What each test guards:
- a call not priced per token (Whisper, Serper) stores the price it was
  given, and `reprice` leaves it alone instead of nulling it
- every embed batch is a priced `embed` row, from the API's token count
  when it reports one and from the text's length when it does not
- the story judge's two raw calls meter themselves
- a Serper search is a priced `image_search` row (2 credits past 10 results)
- a Nano still marks its hold submitted BEFORE the image model is asked,
  so the reaper never releases a still the provider was asked for
"""
from types import SimpleNamespace

import pytest

from src import accounts, db, imagesearch, ledger, nano_banana, rag, spend, story_judge

REAL_SERPER = imagesearch.serper_images


@pytest.fixture
def tmp_db(pg, monkeypatch):
    spend.init(pg)
    accounts.init(pg)
    # calls that pass no dsn (every one under test) land on this schema
    monkeypatch.setenv("DATABASE_URL", pg)
    return pg


def rows(dsn, stage=None):
    sql, args = "SELECT * FROM llm_calls ORDER BY id", ()
    if stage:
        sql, args = "SELECT * FROM llm_calls WHERE stage = %s ORDER BY id", (stage,)
    with db.connect(dsn) as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def answering(text, prompt=200, output=40):
    return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(
        prompt_token_count=prompt, candidates_token_count=output,
        cached_content_token_count=None, thoughts_token_count=None))


# --- the explicit price -------------------------------------------------------

def test_an_explicit_price_is_stored_and_reprice_leaves_it(tmp_db):
    spend.record_call(stage="transcribe", model_asked="fal-ai/whisper", usage={},
                      cost_usd=0.0123, dsn=tmp_db)
    spend.record_call(stage="transcribe", model_asked="fal-ai/whisper", usage={},
                      cost_usd=0.0123, ok=False, dsn=tmp_db)
    good, failed = rows(tmp_db)
    assert good["cost_usd"] == pytest.approx(0.0123) and good["prompt_tokens"] is None
    assert failed["cost_usd"] is None                  # a failed call bills nothing
    assert spend.reprice(tmp_db, account_id=None) == 0
    assert rows(tmp_db)[0]["cost_usd"] == pytest.approx(0.0123)


# --- the embedder ---------------------------------------------------------------

class FakeEmbedder:
    def __init__(self, token_counts=None):
        self.token_counts = token_counts
        self.models = self

    def embed_content(self, model, contents, config):
        stats = (self.token_counts or [None] * len(contents))
        return SimpleNamespace(embeddings=[
            SimpleNamespace(values=[0.0] * rag.EMBED_DIM,
                            statistics=(SimpleNamespace(token_count=n) if n is not None
                                        else None))
            for n in stats])


def test_an_embed_batch_is_a_priced_row_estimated_from_its_text(tmp_db):
    rag.embed_texts(["a" * 40, "bb"], FakeEmbedder())
    [call] = rows(tmp_db, "embed")
    assert call["model_used"] == rag.EMBED_MODEL
    assert call["prompt_tokens"] == 11                   # 42 characters, four a token
    # priced at $0.15 per 1M input tokens (rounded to the micro-dollar, like
    # every estimate) -- a price, never NULL
    assert call["cost_usd"] == spend.estimate_cost(rag.EMBED_MODEL, prompt_tokens=11) > 0
    assert spend.estimate_cost(rag.EMBED_MODEL, prompt_tokens=1_000_000) == pytest.approx(0.15)


def test_an_embed_batch_uses_the_apis_token_count_when_it_has_one(tmp_db):
    rag.embed_texts(["one", "two"], FakeEmbedder(token_counts=[7, 5]))
    [call] = rows(tmp_db, "embed")
    assert call["prompt_tokens"] == 12


# --- the story judge -------------------------------------------------------------

def test_the_story_judge_meters_both_of_its_calls(tmp_db, monkeypatch):
    monkeypatch.setattr(story_judge, "_grounding", lambda *a, **k: ([], []))
    verdict = '{"score": 0.6, "verdict": "fine", "missing": []}'
    client = SimpleNamespace(models=SimpleNamespace(
        generate_content=lambda model, contents: answering(verdict)))
    assert story_judge.judge_spark("a spark", "why", client, "gemini-3-flash-preview")["ok"]
    assert story_judge.judge_ad("an ad", "the turn", client, "gemini-3-flash-preview")["ok"]
    calls = rows(tmp_db, "story_judge")
    assert len(calls) == 2
    assert all(c["cost_usd"] == pytest.approx((200 * 0.50 + 40 * 3.00) / 1e6) for c in calls)


# --- Serper -------------------------------------------------------------------------

def test_a_serper_search_is_a_priced_row(tmp_db, monkeypatch):
    import requests

    monkeypatch.setattr(imagesearch, "serper_images", REAL_SERPER)
    monkeypatch.setenv("SERPER_API_KEY", "k")

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"images": []}

    monkeypatch.setattr(requests, "post", lambda *a, **k: _R())
    imagesearch.serper_images("ghost can", limit=3)        # asks for 6 results: 1 credit
    imagesearch.serper_images("ghost can", limit=8)        # asks for 16: 2 credits
    calls = rows(tmp_db, "image_search")
    assert [c["cost_usd"] for c in calls] == [pytest.approx(0.001), pytest.approx(0.002)]


def test_a_failed_serper_search_is_not_billed(tmp_db, monkeypatch):
    import requests

    monkeypatch.setattr(imagesearch, "serper_images", REAL_SERPER)
    monkeypatch.setenv("SERPER_API_KEY", "k")

    def down(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "post", down)
    assert imagesearch.serper_images("ghost can") == []
    assert rows(tmp_db, "image_search") == []


# --- Nano marks its hold submitted -------------------------------------------------

def test_a_still_is_marked_submitted_before_the_image_model(pg, monkeypatch, tmp_path):
    import src.storage as storage
    from src import generative, preprod

    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    generative.init(pg)
    preprod.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"])
    ledger.grant(account_id, 1000, "purchase", dsn=pg)
    seen = {}

    def fake_image(prompt, out_path, **kw):
        holds = [e for e in ledger.entries(account_id, pg) if e["kind"] == "hold"]
        seen["submitted"] = [e["submitted_at"] for e in holds]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG")
        return out_path

    monkeypatch.setattr(nano_banana, "generate_image", fake_image)
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr(storage, "configured", lambda: False)
    monkeypatch.setattr(nano_banana.render_assets, "record_best_effort",
                        lambda **kw: {"id": None, "rag": None})
    result = nano_banana.generate_from_prompt(
        "a rider suits up", db_path=pg, account_id=account_id,
        model="gemini-2.5-flash-image")
    assert result["ok"], result["error"]
    assert len(seen["submitted"]) == 1 and seen["submitted"][0]
