"""References reaching the graph — the loop `format_cast` opens.

The cast block tells the generator that Michael and the Ducati have
"(reference photos on file)", and the scene it writes says so in as many
words. Until something attaches the files, the renderer gets the
sentence and not the face. The Studio path closed this on 2026-08-28;
the nightly graph kept the old bug until 2026-08-31, which is why its
first automated keyframes came back with nobody recognisable in them.

These cover the receiving end of the research scout's contract:
`orchestrator.run(..., reference_photos=[...])` — the same
site-relative URLs refbin hands back, whether a person dragged the photo
onto the composer or a crawl downloaded it.
"""

import pytest

from src import asset_shelf, db, entities, preprod, refbin, scene_chain, shootgen

JPEG = b"\xff\xd8\xff" + b"pretend jpeg"


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    from src import generative
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    generative.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture
def photo_bank(tmp_path, monkeypatch):
    """A throwaway asset bank on disk, wired in at the src level so the
    graph — which has no app around it — can see it."""
    roots = {}
    for kind, plural in (("character", "characters"), ("prop", "props"),
                         ("location", "locations")):
        roots[kind] = tmp_path / plural
    monkeypatch.setattr(asset_shelf, "PHOTO_DIRS", roots)
    monkeypatch.setattr(refbin, "REFS_DIR", tmp_path / "refs")

    def add(kind, slug, *names):
        d = roots[kind] / slug
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_bytes(JPEG)
    return add


def a_scene(path, prompt, title="Cold Open"):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "desc": title, "prompt": prompt}]},
        brand="antihero", prompt_template="T", path=path, account_id=None)


# --- the resolver, which is the wall as well as the lookup ------------------

def test_both_url_shapes_resolve_without_the_web_app(tmp_db, photo_bank):
    photo_bank("character", "michael", "a.jpg")
    assert asset_shelf.resolve_photo("/characters/michael/photo/a.jpg") is not None
    # ?thumb rides on every URL the media panel hands out
    assert asset_shelf.resolve_photo("/characters/michael/photo/a.jpg?thumb=1") is not None
    # a scouted image, saved by refbin, resolves through the same call
    url = refbin.save(JPEG)
    assert url.startswith("/refs/")
    assert asset_shelf.resolve_photo(url).read_bytes() == JPEG


def test_the_resolver_refuses_anything_escaping_its_root(tmp_db, photo_bank, tmp_path):
    """These URLs come off a stored shot or a crawl, so nothing has
    vouched for them."""
    photo_bank("character", "michael", "a.jpg")
    (tmp_path / "secret.jpg").write_bytes(b"x")
    assert asset_shelf.resolve_photo("/characters/../secret.jpg") is None
    assert asset_shelf.resolve_photo("/characters/michael/photo/../../secret.jpg") is None
    assert asset_shelf.resolve_photo("/refs/../secret.jpg") is None
    assert asset_shelf.resolve_photo("/nope/michael/photo/a.jpg") is None
    assert asset_shelf.resolve_photo("") is None
    assert asset_shelf.resolve_photo(None) is None


# --- what lands on the shot, and in what order ------------------------------

def test_the_scene_gets_the_photos_of_what_it_named(tmp_db, photo_bank):
    photo_bank("character", "michael", "a.jpg", "b.jpg", "c.jpg")
    photo_bank("prop", "ducati", "bike.jpg")
    photo_bank("location", "garage", "room.jpg")
    entities.add_character("Michael", path=tmp_db, account_id=None)
    entities.add_prop("Ducati", path=tmp_db, account_id=None)
    preprod.add_location(name="garage", photo_count=1,
                         description={"space": "a garage"}, path=tmp_db, account_id=None)

    scene_id = a_scene(tmp_db, "Michael wheels the Ducati into the garage.")
    refs = scene_chain.attach_refs(scene_id, db_path=tmp_db)

    # identity holds the anchor slot: Runway reads whichever is FIRST,
    # and a full-room photo there reproduces the room, not the scene
    assert refs[0] == "/characters/michael/photo/a.jpg"
    assert "/props/ducati/photo/bike.jpg" in refs
    assert refs[-1] == "/locations/garage/photo/room.jpg" or len(refs) <= 6
    # more angles of the FACE, because a three-quarter turn grounded on
    # one frontal portrait ages the subject about ten years
    assert "/characters/michael/photo/b.jpg" in refs
    assert preprod.get_concept(scene_id, path=tmp_db, account_id=None)["shots"][0]["refs"] == refs


def test_research_images_never_take_the_anchor_slot(tmp_db, photo_bank):
    """The scout's crawled material should inform a render, not become
    its subject — and the anchor frame IS the subject."""
    photo_bank("character", "michael", "a.jpg")
    entities.add_character("Michael", path=tmp_db, account_id=None)
    scouted = refbin.save(JPEG)

    scene_id = a_scene(tmp_db, "Michael zips the jacket.")
    refs = scene_chain.attach_refs(scene_id, [scouted], db_path=tmp_db)

    assert refs[0] == "/characters/michael/photo/a.jpg"
    assert refs[-1] == scouted


def test_refs_are_capped_at_what_one_generation_carries(tmp_db, photo_bank):
    photo_bank("character", "michael", *[f"{i}.jpg" for i in range(8)])
    entities.add_character("Michael", path=tmp_db, account_id=None)
    extra = [refbin.save(JPEG + bytes([i])) for i in range(6)]
    scene_id = a_scene(tmp_db, "Michael waits.")
    refs = scene_chain.attach_refs(scene_id, extra, db_path=tmp_db)
    assert len(refs) == scene_chain.MAX_REFS == 6


def test_a_scene_naming_nothing_still_renders_on_its_text(tmp_db, photo_bank):
    """Grounding shapes, it never gates."""
    scene_id = a_scene(tmp_db, "An empty hallway at 3am.")
    assert scene_chain.attach_refs(scene_id, db_path=tmp_db) == []
    assert scene_chain.attach_refs(9999, db_path=tmp_db) == []


# --- and they reach the models ----------------------------------------------

def test_urls_become_bytes_the_writer_can_see(tmp_db, photo_bank):
    """A scene written FROM a photograph beats one told a photograph
    exists — which is exactly why the cast block was not enough."""
    photo_bank("character", "michael", "a.jpg")
    triples = scene_chain.as_image_refs(["/characters/michael/photo/a.jpg",
                                         "/characters/nobody/photo/x.jpg"])
    assert len(triples) == 1                      # unresolvable dropped, not raised
    data, mime, label = triples[0]
    assert data == JPEG and mime == "image/jpeg"
    assert label == shootgen.reference_label("/characters/michael/photo/a.jpg")


def test_the_keyframe_finds_a_resolver_on_its_own(tmp_db, photo_bank, monkeypatch):
    """The graph calls keyframe_scene with no app around. Before this it
    passed no resolver, and "no resolver" silently meant "no references
    at all" while the Queue card still said the scene was grounded."""
    from src import nano_banana
    photo_bank("character", "michael", "a.jpg")
    entities.add_character("Michael", path=tmp_db, account_id=None)
    scene_id = a_scene(tmp_db, "Michael zips the jacket.")
    scene_chain.attach_refs(scene_id, db_path=tmp_db)

    seen = {}

    def fake_nano(prompt, *, reference_image=None, db_path=None, concept_id=None, **kw):
        seen["refs"] = list(reference_image or [])
        return {"ok": True, "media_url": "https://cdn/k.png", "generation_id": 1,
                "path": "x", "error": None}

    monkeypatch.setattr(nano_banana, "generate_from_prompt", fake_nano)
    assert scene_chain.keyframe_scene(scene_id, 1, db_path=tmp_db)["ok"]
    assert seen["refs"], "the keyframe rendered with no references at all"
    label, data = seen["refs"][0]
    assert data == JPEG and "michael" in label.lower()


# --- the MCP surface can bank an image, not just a direction ----------------

def test_an_agent_can_bank_a_reference_behind_its_spark(tmp_db, photo_bank,
                                                        monkeypatch):
    """bank_spark hands the graph a direction and no photographs, and the
    only writer to the bin was the crawl -- so on a night the crawl found
    none (DNS, 2026-09-01) an agent could give the run an idea and not one
    frame to render it against."""
    from src import mcp_server, refbin

    monkeypatch.setattr(refbin, "fetch", lambda url: refbin.save(JPEG))
    fid = mcp_server.bank_spark("antihero", "a hand already on the handle",
                                rationale="r", evidence="e", path=tmp_db)["id"]

    out = mcp_server.bank_reference(fid, "https://cdn.example/a.jpg",
                                    source_url="https://example.com/post",
                                    title="a post", path=tmp_db)
    assert out["ok"] and out["url"].startswith("/refs/")
    assert out["banked"] == 1

    # a hand-banked spark has no crawl pass, so it gets one of its own --
    # and spark_images, which reads through the finding, keeps working
    tiles = mcp_server.spark_images(fid, path=tmp_db)
    urls = [t["url"] for t in (tiles.get("images") or tiles.get("tiles") or [])]
    assert out["url"] in urls


def test_attribution_is_required_and_the_bin_is_capped(tmp_db, photo_bank,
                                                       monkeypatch):
    from src import mcp_server, refbin, scout

    fid = mcp_server.bank_spark("antihero", "the door that stays shut",
                                path=tmp_db)["id"]
    with pytest.raises(ValueError, match="source_url"):
        mcp_server.bank_reference(fid, "https://cdn.example/a.jpg",
                                  source_url="  ", path=tmp_db)

    seq = iter(range(50))
    monkeypatch.setattr(refbin, "fetch",
                        lambda url: refbin.save(JPEG + bytes([next(seq)])))
    for _ in range(scout.MAX_BIN_IMAGES + 3):
        mcp_server.bank_reference(fid, "https://cdn.example/x.jpg",
                                  source_url="https://example.com/p", path=tmp_db)
    banked = scout.bin_for_pass(scout.agent_pass_id(fid), path=tmp_db)
    assert len(banked) == scout.MAX_BIN_IMAGES


def test_an_agent_supplied_url_still_cannot_reach_this_machine(tmp_db, photo_bank):
    """The URL comes off whatever page the agent read, and the fetch runs
    server-side. Literal IPs, so no DNS (and no network) is needed."""
    from src import mcp_server, refbin

    for host in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1"):
        assert refbin.public_host(host) is False
    assert refbin.fetch("http://169.254.169.254/latest/meta-data") is None
    assert refbin.fetch("file:///etc/passwd") is None

    fid = mcp_server.bank_spark("antihero", "a spark", path=tmp_db)["id"]
    out = mcp_server.bank_reference(fid, "http://127.0.0.1/secret.jpg",
                                    source_url="https://example.com/p",
                                    path=tmp_db)
    assert out["ok"] is False and out["banked"] == 0
