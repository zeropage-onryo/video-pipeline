"""
`import_file` -- a file on this computer into the studio, from a chat
(2026-10-09, docs/tasks/task-mcp-studio-v2.md step 3+4's fallback).

The studio surface runs over stdio on the person's own Mac, and Claude
Desktop cannot hand an MCP tool a file, so the tool reads one by path. What
is guarded is the fence first -- only the allow-listed folders, with every
symlink resolved; only images and mp4/mov; under the caps; the content what
the extension says -- then that the result is a real `asset:<id>` every
studio tool takes: a reference, a clip effect's source, a clip to join.
"""

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src import mcp_server, preprod, scout
from src.cut import store, uploads

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg is not installed")


def _png(path: Path, size=(64, 48)) -> Path:
    from PIL import Image
    Image.new("RGB", size, (200, 40, 40)).save(path, format="PNG")
    return path


def _mp4(path: Path, seconds=1.0) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", str(seconds), "-i",
                    "testsrc=size=160x284:rate=30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(path)], check=True, capture_output=True)
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An allowed folder (standing in for ~/Downloads) and one beside it
    that is not."""
    allowed, outside = tmp_path / "Downloads", tmp_path / "Private"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.setenv(mcp_server.IMPORT_DIRS_ENV, str(allowed))
    return {"allowed": allowed, "outside": outside}


@pytest.fixture
def db_(pg):
    from src import accounts, db, render_assets
    preprod.init(pg)
    scout.init(pg)
    render_assets.init(pg)
    store.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        acct = int(conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"])
    return {"dsn": pg, "account_id": acct}


# --------------------------------------------------------------------------
# the fence
# --------------------------------------------------------------------------

def test_the_default_folders_are_downloads_desktop_and_data(monkeypatch):
    monkeypatch.delenv(mcp_server.IMPORT_DIRS_ENV, raising=False)
    roots = mcp_server.import_roots()
    home = Path("~").expanduser().resolve()
    assert roots[:2] == [(home / "Downloads").resolve(), (home / "Desktop").resolve()]
    assert roots[2] == (mcp_server.PROJECT_ROOT / "data").resolve()


@pytest.mark.parametrize("path, match", [
    ("", "full path"),
    ("can.png", "not a full path"),
    ("{outside}/can.png", "outside the folders"),
    ("{allowed}/../Private/can.png", "outside the folders"),
    ("{allowed}/missing.png", "no file at"),
    ("{allowed}", "not a file"),
])
def test_only_files_inside_the_allowed_folders_are_read(home, path, match):
    _png(home["outside"] / "can.png")
    with pytest.raises(ValueError, match=match):
        mcp_server.run_import_file(path.format(**home), account_id=None)


def test_a_symlink_out_of_the_folder_is_refused(home):
    secret = _png(home["outside"] / "secret.png")
    link = home["allowed"] / "innocent.png"
    os.symlink(secret, link)
    with pytest.raises(ValueError, match="outside the folders"):
        mcp_server.run_import_file(str(link), account_id=None)


@pytest.mark.parametrize("name, body", [
    ("notes.txt", b"hello"), ("deck.pdf", b"%PDF-1.4"), ("clip.webm", b"x"),
    ("song.mp3", b"ID3"), ("key", b"-----BEGIN"),
])
def test_only_images_and_mp4_mov_are_taken(home, name, body):
    (home["allowed"] / name).write_bytes(body)
    with pytest.raises(ValueError, match="only images"):
        mcp_server.run_import_file(str(home["allowed"] / name), account_id=None)


def test_a_file_over_the_cap_is_refused_before_it_is_read(home, monkeypatch):
    big = _png(home["allowed"] / "big.png")
    monkeypatch.setattr(uploads, "MAX_MEDIA_BYTES", 10)
    with pytest.raises(ValueError, match="the limit is 0MB"):
        mcp_server.run_import_file(str(big), account_id=None)


def test_a_file_that_is_not_what_it_says_is_refused(home, db_):
    fake = home["allowed"] / "photo.jpg"
    fake.write_bytes(b"this is not a jpeg")
    with pytest.raises(ValueError, match="photo.jpg"):
        mcp_server.run_import_file(str(fake), dsn=db_["dsn"], account_id=db_["account_id"])
    assert store.media_bin(account_id=db_["account_id"], dsn=db_["dsn"]) == []


def test_a_signed_in_caller_never_reads_the_disk(home):
    _png(home["allowed"] / "can.png")
    token = mcp_server.CALLER_ACCOUNT.set(5)
    try:
        with pytest.raises(mcp_server.Refused, match="not offered over a connector"):
            mcp_server.run_import_file(str(home["allowed"] / "can.png"))
    finally:
        mcp_server.CALLER_ACCOUNT.reset(token)


def test_import_file_is_on_the_studio_surface_only(pg, monkeypatch):
    preprod.init(pg)
    scout.init(pg)
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")

    def names(**kw):
        return {t.name for t in asyncio.run(mcp_server.build_server(dsn=pg, **kw).list_tools())}

    assert "import_file" in names(surface="studio")
    assert "import_file" not in names()                   # the board: served over HTTP
    assert "import_file" not in names(listed=True)


# --------------------------------------------------------------------------
# what comes back is an asset:<id> every tool takes
# --------------------------------------------------------------------------

def test_an_image_comes_back_as_an_asset_id_and_is_a_reference(home, db_, monkeypatch):
    src = _png(home["allowed"] / "can.png")
    out = mcp_server.run_import_file(str(src), dsn=db_["dsn"], account_id=db_["account_id"])
    assert out["ok"] and out["id"].startswith("asset:") and out["kind"] == "image"
    assert (out["width"], out["height"]) == (64, 48) and "Nothing was spent" in out["note"]
    row = store.get_media(int(out["id"].split(":")[1]), account_id=db_["account_id"],
                          dsn=db_["dsn"])
    assert row["kind"] == "image" and Path(row["output_path"]).read_bytes() == src.read_bytes()
    # ...and it resolves as a reference (the bucket stood in for)
    monkeypatch.setattr(mcp_server, "_fetchable", lambda raw, acct: f"https://r2{raw}")
    (url,) = mcp_server.resolve_references([out["id"]], limit=4, who="X", dsn=db_["dsn"],
                                           account_id=db_["account_id"])
    assert url.startswith("https://r2/renders/cut/media/")
    listed = mcp_server.list_renders(kind="upload", dsn=db_["dsn"], account_id=db_["account_id"])
    assert [r["id"] for r in listed["renders"]] == [out["id"]]


def test_another_accounts_import_is_not_a_reference(home, db_, monkeypatch):
    out = mcp_server.run_import_file(str(_png(home["allowed"] / "can.png")),
                                     dsn=db_["dsn"], account_id=db_["account_id"])
    monkeypatch.setattr(mcp_server, "_fetchable", lambda raw, acct: f"https://r2{raw}")
    with pytest.raises(ValueError, match="no import"):
        mcp_server.resolve_references([out["id"]], limit=4, who="X", dsn=db_["dsn"],
                                      account_id=None)


@needs_ffmpeg
def test_a_clip_comes_back_as_an_asset_id_for_effects_and_joins(home, db_, monkeypatch):
    from src import effects
    from src.cut import join
    clip = mcp_server.run_import_file(str(_mp4(home["allowed"] / "take.mov", 1.0)),
                                      dsn=db_["dsn"], account_id=db_["account_id"])
    assert clip["kind"] == "video" and clip["seconds"] == pytest.approx(1.0, abs=0.1)
    with pytest.raises(ValueError, match="a reference must be an image"):
        mcp_server.resolve_references([clip["id"]], limit=4, who="X", dsn=db_["dsn"],
                                      account_id=db_["account_id"])
    # a clip effect's source: measured, made fetchable (the bucket stood in for)
    monkeypatch.setattr(effects, "fetchable_video",
                        lambda url, local="", account_id=None: f"https://r2{url}")
    urls, probe = mcp_server._video_sources([clip["id"]], db_["dsn"], db_["account_id"])
    assert urls[0].startswith("https://r2/renders/cut/media/") and probe["seconds"] > 0.9
    # ...and a clip a join takes, beside another import
    other = mcp_server.run_import_file(str(_mp4(home["allowed"] / "b.mp4", 1.0)),
                                       dsn=db_["dsn"], account_id=db_["account_id"])
    planned = join.plan([clip["id"], other["id"]], account_id=db_["account_id"], dsn=db_["dsn"])
    assert planned["seconds"] == pytest.approx(2.0, abs=0.1)


def test_the_tool_answers_typed(home, db_):
    from src import mcp_shapes
    server = mcp_server.build_server(dsn=db_["dsn"], surface="studio",
                                     account_id=db_["account_id"])
    res = asyncio.run(server.call_tool("import_file",
                                       {"path": str(_png(home["allowed"] / "can.png"))}))
    data = res.structured_content
    mcp_shapes.ImportResult.model_validate(data)
    assert res.content[0].text == f"Imported can.png as {data['id']} (image, 64x48)."


def test_the_shared_upload_body_refuses_a_picture_with_no_size(tmp_path, db_):
    """The same body the editor's upload route runs: a text file named .png
    probes as a 0x0 still, and is refused as not an image (it used to be
    filed)."""
    with pytest.raises(uploads.UploadRefused) as e:
        uploads.save(b"not a png at all", "x.png", account_id=db_["account_id"],
                     media_dir=tmp_path / "media", dsn=db_["dsn"])
    assert e.value.code == "not_an_image"
    assert list((tmp_path / "media").iterdir()) == []      # nothing left behind
