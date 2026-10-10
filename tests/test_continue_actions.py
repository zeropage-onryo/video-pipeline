"""What a result can be carried on to (item 4 of docs/tasks/task-studio-agent.md).

The server half of the "continue" actions is two routes onto one render on
the Assets wall: look it up by id (the composer is handed `?on=gen:<id>`
and needs to know what it is), and save it to the person's computer. Both
are this account's renders only, and neither returns a removed one.
"""
import pytest
from fastapi.testclient import TestClient

from app import api, auth
from app.main import app
from src import accounts, generative, media, render_assets, storage

WHO = {}          # the two accounts this run made: "mine" signs in, "theirs" does not


@pytest.fixture
def client(pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg)
    accounts.init(pg)
    generative.init(pg)
    render_assets.init(pg)
    WHO["mine"] = accounts.upsert_account("c-mine", "Mine", "#fff", dsn=pg)
    WHO["theirs"] = accounts.upsert_account("c-theirs", "Theirs", "#fff", dsn=pg)
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "c-user"})
    app.dependency_overrides[auth.current_account_id] = lambda: WHO["mine"]
    yield TestClient(app)
    app.dependency_overrides.pop(auth.current_account_id, None)


def _render(pg, who="mine", *, kind="image", url="/renders/nano/a.png", path=None, n=1):
    account = WHO[who]
    return render_assets.record(generation_id=n, tool="nano" if kind == "image" else "fal",
                                model="stub", media_kind=kind, prompt="a can on wet steel",
                                media_url=url, output_path=path, dsn=pg, account_id=account)["id"]


# ---------- one render, by id ----------

def test_a_render_is_looked_up_by_id_with_the_ref_an_effect_names_it_by(client, pg, monkeypatch):
    monkeypatch.setattr(storage, "configured", lambda: False)
    still = _render(pg)
    clip = _render(pg, kind="video", url="/renders/fal/c.mp4", n=2)
    got = client.get(f"/api/assets/generated/{still}").json()
    assert got["ref"] == f"gen:{still}" and got["kind"] == "image"
    assert got["url"] == "/renders/nano/a.png" and got["thumb"]
    assert got["prompt"] == "a can on wet steel"
    assert client.get(f"/api/assets/generated/{clip}").json()["kind"] == "video"


def test_another_accounts_render_and_a_removed_one_do_not_exist(client, pg, monkeypatch):
    monkeypatch.setattr(storage, "configured", lambda: False)
    theirs = _render(pg, "theirs")
    gone = _render(pg, n=2)
    render_assets.soft_delete(gone, dsn=pg, account_id=WHO["mine"])
    for asset in (theirs, gone, 999_999):
        assert client.get(f"/api/assets/generated/{asset}").status_code == 404
        assert client.get(f"/api/assets/generated/{asset}/download",
                          follow_redirects=False).status_code == 404


# ---------- saving it ----------

def test_a_download_is_a_redirect_to_the_bucket_asking_for_an_attachment(client, pg, monkeypatch):
    """The bytes go bucket -> browser: this server answers with a 302 and
    never reads the file."""
    still = _render(pg, url="https://pub.example/m/42/renders/nano/a.png")
    asked = []
    monkeypatch.setattr(storage, "configured", lambda: True)
    monkeypatch.setattr(storage, "key_exists", lambda key: key.endswith("renders/nano/a.png"))
    monkeypatch.setattr(media, "master_key", lambda url, account_id: "m/42/renders/nano/a.png")
    monkeypatch.setattr(storage, "download_url_for_key",
                        lambda key, name: asked.append((key, name)) or f"https://s3.example/{key}?sig=1")
    got = client.get(f"/api/assets/generated/{still}/download", follow_redirects=False)
    assert got.status_code == 302
    assert got.headers["location"] == "https://s3.example/m/42/renders/nano/a.png?sig=1"
    ((key, name),) = asked
    assert key == "m/42/renders/nano/a.png"
    assert name.startswith("zeropage-") and name.endswith(f"-{still}.png")


def test_with_no_bucket_this_machines_own_copy_is_served_and_only_from_the_renders_folder(
        client, pg, monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "configured", lambda: False)
    renders = (api.Path(api.__file__).resolve().parent.parent / "data" / "renders" / "test-continue")
    renders.mkdir(parents=True, exist_ok=True)
    mine = renders / "kept.png"
    mine.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    try:
        ok = _render(pg, url="/renders/test-continue/kept.png", path=str(mine))
        got = client.get(f"/api/assets/generated/{ok}/download")
        assert got.status_code == 200 and got.content.startswith(b"\x89PNG")
        assert "attachment" in got.headers["content-disposition"]
        assert f"-{ok}.png" in got.headers["content-disposition"]
        # a row whose path points outside data/renders is never read
        outside = tmp_path / "secret.png"
        outside.write_bytes(b"not a render")
        bad = _render(pg, url="/renders/x/secret.png", path=str(outside), n=2)
        assert client.get(f"/api/assets/generated/{bad}/download").status_code == 404
    finally:
        mine.unlink(missing_ok=True)
        renders.rmdir()


def test_the_saved_name_is_plain_ascii_and_keeps_the_files_own_extension():
    name = api._download_name({"id": 7, "provider": "Kling 3 · Turbo/Pro", "media_kind": "video",
                               "media_url": "https://pub.example/m/1/renders/fal/x.webm?v=2"})
    assert name == "zeropage-kling-3-turbo-pro-7.webm"
    assert api._download_name({"id": 8, "provider": "", "media_kind": "video",
                               "media_url": "/renders/fal/no-suffix"}) == "zeropage-render-8.mp4"
    assert api._download_name({"id": 9, "provider": "FLUX", "media_kind": "image",
                               "media_url": "/renders/x.<script>"}) == "zeropage-flux-9.png"


def test_the_attachment_url_is_signed_for_the_bucket_and_the_name_cannot_break_the_header(monkeypatch):
    calls = []

    class Client:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            calls.append((op, Params, ExpiresIn))
            return "https://s3.example/signed"

    monkeypatch.setattr(storage, "configured", lambda: True)
    monkeypatch.setattr(storage, "_client", lambda: Client())
    monkeypatch.setattr(storage, "bucket", lambda: "zp")
    assert storage.download_url_for_key("m/1/x.png", 'a"b\r\n.png') == "https://s3.example/signed"
    ((op, params, ttl),) = calls
    assert op == "get_object" and params["Bucket"] == "zp" and params["Key"] == "m/1/x.png"
    assert params["ResponseContentDisposition"] == 'attachment; filename="ab.png"'
    assert ttl == storage.DOWNLOAD_TTL_SECONDS
    monkeypatch.setattr(storage, "configured", lambda: False)
    assert storage.download_url_for_key("m/1/x.png", "x.png") is None
