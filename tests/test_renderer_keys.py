"""The Queue's Renderer keys panel — BYOK's front door (2026-09-12).

`src/account_keys.py` has held encrypted per-account credentials since
2026-09-03, and the only way to enter one was `python -m src.account_keys
set` on the server. So a pilot user could not bring a key at all, and
every render they approved billed the operator's card — backlog #10's
open item, and the reason this is the first thing a second user needs.

What these tests hold in place is mostly what the routes REFUSE to do: a
stored key is never returned, a mutation without the header is not a
mutation, and a vendor nobody registered is not a place to put a secret.
"""
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import app
from src import account_keys, accounts, db, providers

client = TestClient(app)
HEADER = {"x-zpf-renderer-key": "1"}
OWNER = None


@pytest.fixture
def keys_db(pg, monkeypatch):
    """A real account to act as: `account_keys` is an OWNED table with a
    foreign key to accounts, so conftest's default `account_id = None`
    (the unowned pool) is not a tenant that can hold a credential."""
    global OWNER
    from app import auth

    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("ACCOUNT_KEYS_SECRET", Fernet.generate_key().decode())
    accounts.seed("pilot@example.com", dsn=pg)
    account_keys.init(pg)
    with db.connect(pg) as conn:
        OWNER = conn.execute(
            "SELECT id FROM accounts WHERE slug='zeropage'").fetchone()["id"]
    monkeypatch.setattr(auth, "current_user",
                        lambda request: {"id": 1, "email": "pilot@example.com"})
    app.dependency_overrides[auth.current_account_id] = lambda: OWNER
    yield pg
    app.dependency_overrides.pop(auth.current_account_id, None)


def test_the_listing_covers_every_renderer_and_names_no_secret(keys_db):
    data = client.get("/api/renderer-keys").json()
    assert [i["provider"] for i in data["items"]] == list(providers.VIDEO_PROVIDERS)
    for item in data["items"]:
        assert item["fields"], f"{item['provider']} offers no field to type into"
        # the whole security property: nothing key-shaped comes back
        assert not any(k in item for k in ("key", "value", "values", "ciphertext"))


def test_a_stored_key_is_the_accounts_own_and_never_comes_back(keys_db, monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_API_KEY_ID", "operator-id")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_SECRET", "operator-secret")
    before = client.get("/api/renderer-keys").json()["items"]
    assert next(i for i in before if i["provider"] == "higgsfield")["source"] == "env"

    res = client.put("/api/renderer-keys/higgsfield", headers=HEADER,
                     json={"values": ["mine-id", "mine-secret"]})
    assert res.status_code == 200, res.text
    assert res.json()["source"] == "account"
    assert "mine-secret" not in res.text
    # and the render path resolves the account's key, not the operator's
    assert account_keys.key_for(OWNER, "higgsfield", keys_db) == {
        "api_key_id": "mine-id", "api_key_secret": "mine-secret"}

    listed = client.get("/api/renderer-keys").json()["items"]
    row = next(i for i in listed if i["provider"] == "higgsfield")
    assert row["source"] == "account" and row["stored_at"]


def test_removing_a_key_falls_back_to_the_operators_rather_than_to_nothing(
        keys_db, monkeypatch):
    monkeypatch.setenv("RUNWAYML_API_SECRET", "operator")
    client.put("/api/renderer-keys/runway", headers=HEADER, json={"values": ["mine"]})
    res = client.delete("/api/renderer-keys/runway", headers=HEADER)
    assert res.status_code == 200
    # the row says which — "removed" must not read as "rendering is off"
    assert res.json()["source"] == "env"
    assert account_keys.key_for(OWNER, "runway", keys_db) == {"api_secret": "operator"}


def test_a_mutation_without_the_header_is_refused(keys_db):
    """model_connections' rule. The session cookie is SameSite=None on the
    hosted deployment, so a form on another origin could POST a key onto
    somebody's account; a custom header forces a CORS preflight."""
    for call in (lambda: client.put("/api/renderer-keys/runway",
                                    json={"values": ["x"]}),
                 lambda: client.delete("/api/renderer-keys/runway")):
        assert call().status_code == 403
    assert account_keys.list_providers(OWNER, keys_db) == []


def test_the_wrong_number_of_values_is_refused_before_anything_is_stored(keys_db):
    res = client.put("/api/renderer-keys/higgsfield", headers=HEADER,
                     json={"values": ["only-the-id"]})
    assert res.status_code == 400
    assert "Key id" in res.json()["error"]["message"]
    assert client.put("/api/renderer-keys/runway", headers=HEADER,
                      json={"values": ["   "]}).status_code == 400
    assert account_keys.list_providers(OWNER, keys_db) == []


def test_only_registered_renderers_can_hold_a_key(keys_db):
    """gemini and midjourney are deliberately not on this surface: the
    cheap Gemini steps are the operator's to pay for (backlog #10's split
    by cost), and Midjourney has no API to hold a key for."""
    for provider in ("gemini", "midjourney", "../etc"):
        assert client.put(f"/api/renderer-keys/{provider}", headers=HEADER,
                          json={"values": ["x"]}).status_code in (404, 405)


def test_no_encryption_secret_says_so_instead_of_failing_as_a_500(
        keys_db, monkeypatch):
    """Storing a key in the clear is exactly what ACCOUNT_KEYS_SECRET
    exists to prevent, so with none set the answer is a refusal a person
    can act on."""
    monkeypatch.delenv("ACCOUNT_KEYS_SECRET", raising=False)
    res = client.put("/api/renderer-keys/runway", headers=HEADER,
                     json={"values": ["mine"]})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "encryption_unavailable"
    assert "ACCOUNT_KEYS_SECRET" in res.json()["error"]["message"]


def test_the_key_a_person_enters_is_what_the_queue_then_offers(keys_db, monkeypatch):
    """The point of the whole panel: entering a Higgsfield key on an
    account with no Runway key makes the Queue's default renderable —
    providers.render_default reads account_keys through has_key."""
    monkeypatch.delenv("RUNWAYML_API_SECRET", raising=False)
    for name in ("HIGGSFIELD_API_KEY_ID", "HIGGSFIELD_API_KEY_SECRET",
                 "FAL_KEY", "FAL_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert providers.renderer_for(OWNER, "runway", None) is None

    client.put("/api/renderer-keys/higgsfield", headers=HEADER,
               json={"values": ["mine-id", "mine-secret"]})
    assert providers.render_default("RUNWAY", OWNER)["provider"] == "higgsfield"


# --- Gemini is a BYOK provider too (2026-09-14) ----------------------------
#
# Every renderer resolved its credential per account through
# account_keys.key_for; Gemini did not, and read GEMINI_API_KEY -- the
# OPERATOR's key -- straight from the environment. That is invisible with one
# operator and it is the bill the moment there are users, because Gemini is
# not an occasional renderer here: it writes every scene, plans every
# timeline, draws every keyframe, and runs the scout and the judge. It fires
# on every Create, where Runway fires only when someone approves a spend.
#
# These test BOTH directions, which is the lesson from the pilot dry run: a
# stranger must not spend the operator's key, AND the operator must still
# reach their own. An inward drop fails closed and looks like nothing.

@pytest.fixture
def gemini_byok(pg, monkeypatch):
    """One account with its own stored Gemini key, a DIFFERENT operator key
    in the environment. Whichever turns up is the answer to whose bill it is."""
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("ACCOUNT_KEYS_SECRET", Fernet.generate_key().decode())
    monkeypatch.setenv("GEMINI_API_KEY", "OPERATOR-GEMINI")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        owner = conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"]
    account_keys.set_key(owner, "gemini", "TENANT-GEMINI", dsn=pg)
    return {"dsn": pg, "account_id": owner}


def test_an_account_with_a_gemini_key_does_not_spend_the_operators(gemini_byok):
    from src import gemini_utils
    assert gemini_utils.api_key_for(gemini_byok["account_id"]) == "TENANT-GEMINI"


def test_an_account_without_one_still_falls_back_to_the_installation(gemini_byok):
    """The inward direction. A tenant with no stored key must keep working on
    the operator's -- this is how it behaved before BYOK and how every
    single-operator install still behaves."""
    from src import accounts as accounts_mod
    from src import gemini_utils
    other = accounts_mod.upsert_account("nokey", "No Key", dsn=gemini_byok["dsn"])
    other_id = other["id"] if isinstance(other, dict) else other
    assert gemini_utils.api_key_for(other_id) == "OPERATOR-GEMINI"
    # and account_id=None -- the nightly walk, the scout, the CLI -- is unchanged
    assert gemini_utils.api_key_for(None) == "OPERATOR-GEMINI"


def test_the_keyframe_path_asks_for_the_accounts_key_not_the_environment(
        gemini_byok, monkeypatch):
    """nano_banana._client() used to be a bare genai.Client(), which reads
    GEMINI_API_KEY out of the ambient environment -- the one thing a second
    account must not do."""
    from src import nano_banana
    seen = []
    monkeypatch.setattr("google.genai.Client",
                        lambda api_key=None, **kw: seen.append(api_key) or object())
    nano_banana._client(gemini_byok["account_id"])
    nano_banana._client(None)
    assert seen == ["TENANT-GEMINI", "OPERATOR-GEMINI"]


def test_has_key_answers_per_account(gemini_byok, monkeypatch):
    from src import nano_banana
    assert nano_banana.has_key(gemini_byok["account_id"]) is True
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # the tenant keeps its own key when the installation has none at all
    assert nano_banana.has_key(gemini_byok["account_id"]) is True
    assert nano_banana.has_key(None) is False


def test_a_client_with_no_key_anywhere_refuses_instead_of_failing_later(
        gemini_byok, monkeypatch):
    from src import gemini_utils
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no Gemini key"):
        gemini_utils.client_for(None)


def test_the_web_surface_resolves_per_account(gemini_byok):
    """app/api._gemini_key is the chokepoint 18 routes read; if it is not
    account-aware then none of them are."""
    from app import api
    assert api._gemini_key(gemini_byok["account_id"]) == "TENANT-GEMINI"
    assert api._gemini_key(None) == "OPERATOR-GEMINI"


def test_no_route_reads_the_gemini_env_var_behind_the_chokepoint():
    """The static guard. A new route that reaches for os.environ directly
    puts the operator's key back on a tenant's call, and nothing else here
    would notice."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for name in ("app/api.py", "app/main.py"):
        for i, line in enumerate((root / name).read_text().split("\n"), 1):
            if re.search(r'environ\.get\(\s*"(GEMINI_API_KEY|GOOGLE_API_KEY)"', line):
                offenders.append(f"{name}:{i}")
    # app/main.py's library_backfill_assets takes no account at all -- it is an
    # operator-only maintenance route, and is the ONE allowed reader.
    assert len(offenders) <= 1, (
        "these read the operator's Gemini key directly instead of going "
        "through _gemini_key(account_id)/gemini_utils.api_key_for: "
        + ", ".join(offenders))
