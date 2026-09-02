"""References reaching the render — the loop format_cast opens.

`format_cast` tells the generator that Michael and the Ducati have
"(reference photos on file)", and the scene it writes says exactly that.
Nothing was attaching those files, so the Director graph, the keyframe
and the clip all got the sentence and never the face (fixed 2026-08-28).

These cover both halves: the assets a scene NAMES are found and
attached, and a photo uploaded on the composer is persisted so it has a
URL to ride on at all.
"""
import json
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from app import api, workflow_runner
from app.main import app
from src import db, entities, imagery, preprod, refbin, shootgen

client = TestClient(app)


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    from app import auth
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "zeropage", "display_name": "ZERO PAGE"})


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


# Mike's real assets, in the shape _assets_all() returns them.
MICHAEL = {"name": "Michael", "category": "character",
           "text": "Stills of myself the main character. I'm in a motorcycle",
           "photos": ["/characters/michael/photo/a.jpg?thumb=1"]}
CYCLOPS = {"name": "Cyclops", "category": "character",
           "text": "The One eyed cyclops monster from the odyssey",
           "photos": ["/characters/cyclops/photo/a.jpg?thumb=1"]}
BIKE = {"name": "Motorcycle", "category": "prop",
        "text": "A Ducati Panigale 959. Michael's personal vehicle. Shots of different angles",
        "photos": ["/props/motorcycle/photo/a.jpg?thumb=1"]}
ROOM = {"name": "living-room", "category": "location", "text": "a lived-in room",
        "photos": ["/locations/living-room/photo/a.jpg"]}
CAST = [MICHAEL, CYCLOPS, BIKE, ROOM]

SCENE = ("Michael (reference photos on file) fumbles a key into the ignition of the "
         "Ducati Panigale 959 in a cramped garage. The camera pans down to reveal the "
         "Cyclops polishing a silver spoon on the oily concrete.")


# --- finding the assets a scene named ---------------------------------------

def test_a_prop_is_found_by_the_name_the_scene_actually_calls_it():
    """The prop is stored as "Motorcycle"; the scene calls it a Ducati
    Panigale 959. Name matching alone would miss it, and missing it is
    how a bike the model has photos of renders as a generic bike."""
    assert shootgen.asset_aliases(BIKE) == ["Motorcycle", "Ducati Panigale"]
    names = [a["name"] for a in shootgen.named_assets(SCENE, CAST)]
    assert names == ["Michael", "Cyclops", "Motorcycle"]


def test_an_alias_never_runs_across_a_sentence_boundary():
    """"A Ducati Panigale 959. Michael's personal vehicle" must not
    yield "Ducati Panigale Michael" — an alias that matches nothing and
    silently belongs to the wrong asset."""
    assert "Ducati Panigale Michael" not in shootgen.asset_aliases(BIKE)


def test_identity_comes_first_and_the_location_comes_last():
    """Runway anchors a clip on exactly ONE frame, so whatever is first
    is what the clip looks like. A room photo in that slot reproduces
    the room instead of the scene."""
    hits = shootgen.named_assets(SCENE + " Shot in the living-room.", CAST)
    assert [a["category"] for a in hits] == ["character", "character", "prop", "location"]


def test_two_characters_are_ordered_by_who_the_scene_opens_on():
    """Not interchangeable: the anchor frame decides what the clip looks
    like, and this scene opens on Michael and meets the Cyclops later.
    Table order put the monster first."""
    assert [a["name"] for a in shootgen.named_assets(SCENE, [CYCLOPS, MICHAEL])] \
        == ["Michael", "Cyclops"]
    flipped = ("The Cyclops waits in the dark. Much later, Michael walks in.")
    assert [a["name"] for a in shootgen.named_assets(flipped, [MICHAEL, CYCLOPS])] \
        == ["Cyclops", "Michael"]


def test_a_photo_the_renderer_cannot_decode_is_not_the_one_picked():
    """IMAGE_EXTENSIONS lists .heic and the gallery shows it, but a
    reference that fails to decode is dropped SILENTLY at render — the
    worst way for one to fail. Prefer a sibling that definitely reads."""
    assert api._best_photo(["/props/motorcycle/photo/a.heic?thumb=1",
                            "/props/motorcycle/photo/b.JPG"]) \
        == "/props/motorcycle/photo/b.JPG"
    # but a HEIC-only asset still gets its reference, not nothing
    assert api._best_photo(["/props/motorcycle/photo/a.heic"]) \
        == "/props/motorcycle/photo/a.heic"
    assert api._best_photo([]) is None


def test_the_spare_slots_go_to_more_angles_of_the_face(monkeypatch):
    """The Garage Guest keyframe grounded a three-quarter head turn on a
    single frontal portrait and aged him about ten years — while the
    three-quarter frame it needed sat unused in the same folder. Every
    named asset still gets one photo first, so the bike is not starved
    and the anchor slot still holds the character the scene opens on."""
    michael = dict(MICHAEL, photos=["/characters/michael/photo/front.jpg",
                                    "/characters/michael/photo/three-quarter.jpg",
                                    "/characters/michael/photo/profile.jpg",
                                    "/characters/michael/photo/helmet.jpg"])
    monkeypatch.setattr(api, "_assets_all", lambda account_id=None: [michael, CYCLOPS, BIKE])
    refs = api._auto_refs(SCENE, [])
    assert refs[0] == "/characters/michael/photo/front.jpg"     # the anchor
    assert refs[:3] == ["/characters/michael/photo/front.jpg",
                        "/characters/cyclops/photo/a.jpg",
                        "/props/motorcycle/photo/a.jpg"]
    assert "/characters/michael/photo/three-quarter.jpg" in refs
    assert "/characters/michael/photo/profile.jpg" in refs
    # three per character, never the whole folder
    assert "/characters/michael/photo/helmet.jpg" not in refs


def test_a_prop_never_gets_a_second_angle(monkeypatch):
    """A prop gains almost nothing from another angle and an identity
    gains most of what it has, so the spare slots are not shared out."""
    bike = dict(BIKE, photos=["/props/motorcycle/photo/a.jpg",
                              "/props/motorcycle/photo/b.jpg"])
    monkeypatch.setattr(api, "_assets_all", lambda account_id=None: [bike])
    assert api._auto_refs("the Ducati Panigale 959 idles", []) \
        == ["/props/motorcycle/photo/a.jpg"]


def test_the_reference_cap_still_holds(monkeypatch):
    """MAX_IMAGE_REFS is what one call sends to Gemini, and pass two
    must not walk past it."""
    michael = dict(MICHAEL, photos=[f"/characters/michael/photo/{n}.jpg"
                                    for n in "abcd"])
    monkeypatch.setattr(api, "_assets_all", lambda account_id=None: [michael, CYCLOPS, BIKE])
    monkeypatch.setattr(api, "MAX_IMAGE_REFS", 4)
    refs = api._auto_refs(SCENE, [])
    assert len(refs) == 4
    assert refs[:3] == ["/characters/michael/photo/a.jpg",
                        "/characters/cyclops/photo/a.jpg",
                        "/props/motorcycle/photo/a.jpg"]


def test_extra_angles_prefer_the_ones_that_decode(monkeypatch):
    """Same preference _best_photo has always had, applied to a run of
    them: a HEIC that drops silently at render sorts behind the JPEGs
    rather than eating a slot."""
    assert api._asset_photos(["/characters/michael/photo/a.heic",
                              "/characters/michael/photo/b.jpg?thumb=1",
                              "/characters/michael/photo/c.JPG"], 2) \
        == ["/characters/michael/photo/b.jpg", "/characters/michael/photo/c.JPG"]
    assert api._asset_photos([], 3) == []
    assert api._asset_photos(["/characters/michael/photo/a.jpg"], 0) == []


def test_an_asset_with_no_photos_is_not_a_reference():
    unphotographed = dict(MICHAEL, photos=[])
    assert shootgen.named_assets(SCENE, [unphotographed]) == []


def test_a_name_only_matches_as_a_whole_word():
    """A prop called "Key" must not match "monkey"."""
    key = {"name": "Key", "category": "prop", "text": "", "photos": ["/props/key/photo/a.jpg"]}
    assert shootgen.named_assets("a monkey wrench and some whiskey", [key]) == []
    assert shootgen.named_assets("he turns the key", [key]) == [key]


def test_nothing_named_is_not_an_error():
    assert shootgen.named_assets("an empty road at night", CAST) == []
    assert shootgen.named_assets("", CAST) == []


# --- attaching them to the shot ---------------------------------------------

def test_the_written_scene_comes_out_carrying_its_references(tmp_db, monkeypatch):
    """End to end: an idea in, and the concept that lands has the photos
    of everyone it named sitting on its shot — which is what the
    Director graph reads as ref_urls."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("google.genai.Client", lambda api_key=None: object())
    monkeypatch.setattr("src.shootgen.reference_block",
                        lambda spark=None, client=None, db_path=None: "")
    monkeypatch.setattr(api, "_assets_all", lambda account_id=None: CAST)
    monkeypatch.setattr(
        "src.shootgen.generate_with_retry",
        lambda c, m, p, **_: json.dumps({"scenes": [
            {"title": "The Garage Guest", "prompt": SCENE}]}))

    job = wait_for_job(client.post(
        "/api/scenes/run",
        data={"idea": "a rider suits up", "count": "1", "brand": "zeropage"},
    ).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert "1 grounded in references" in job["detail"]

    card = client.get("/api/pipeline/concepts?brand=zeropage").json()["items"][0]
    assert card["refs"] == ["/characters/michael/photo/a.jpg",
                            "/characters/cyclops/photo/a.jpg",
                            "/props/motorcycle/photo/a.jpg"]
    # the ?thumb=1 the media grid uses is stripped — the render wants the
    # full-size file, not the thumbnail
    assert all("thumb" not in r for r in card["refs"])


def test_a_manual_pick_outranks_an_inferred_one(tmp_db, monkeypatch):
    """An explicit pick is first, because first is what Runway anchors
    on. Inferred references fill in behind it."""
    monkeypatch.setattr(api, "_assets_all", lambda account_id=None: CAST)
    scene_id = preprod.save_concept(
        {"title": "t", "shots": [{"n": 1, "source": "AI", "prompt": SCENE}]},
        brand="zeropage", path=tmp_db, account_id=None)
    refs = api._attach_scene_refs(scene_id, ["/locations/living-room/photo/a.jpg"])
    assert refs[0] == "/locations/living-room/photo/a.jpg"
    assert "/characters/michael/photo/a.jpg" in refs
    assert preprod.get_concept(scene_id, path=tmp_db, account_id=None)["refs"] == refs


def test_attaching_never_rewrites_the_prompt(tmp_db, monkeypatch):
    monkeypatch.setattr(api, "_assets_all", lambda account_id=None: CAST)
    scene_id = preprod.save_concept(
        {"title": "t", "shots": [{"n": 1, "source": "AI", "prompt": SCENE}]},
        brand="zeropage", path=tmp_db, account_id=None)
    api._attach_scene_refs(scene_id, [])
    assert preprod.get_concept(scene_id, path=tmp_db, account_id=None)["shots"][0]["prompt"] == SCENE


def test_no_assets_at_all_leaves_the_scene_alone(tmp_db, monkeypatch):
    """Grounding shapes, it doesn't gate — an empty asset bank writes
    scenes exactly like it did before."""
    monkeypatch.setattr(api, "_assets_all", lambda account_id=None: [])
    scene_id = preprod.save_concept(
        {"title": "t", "shots": [{"n": 1, "source": "AI", "prompt": SCENE}]},
        brand="zeropage", path=tmp_db, account_id=None)
    assert api._attach_scene_refs(scene_id, []) == []


# --- uploads live somewhere now ---------------------------------------------

def test_an_uploaded_reference_is_saved_and_resolves_back(tmp_path, monkeypatch):
    """An upload used to ground one Gemini call and vanish, so it could
    never reach the keyframe or the clip. It needs a URL, and that URL
    has to resolve back to bytes through the same function every render
    path uses."""
    # src/refbin.py owns data/refs in both directions now, so the
    # directory is patched there -- patching api.UPLOAD_REFS_DIR alone
    # would move the reader and leave the writer on the real folder.
    monkeypatch.setattr(refbin, "REFS_DIR", tmp_path / "refs")
    jpeg = b"\xff\xd8\xff" + b"not really a jpeg"
    url = api._save_upload_ref(jpeg)
    assert url.startswith("/refs/") and url.endswith(".jpg")
    assert api._resolve_asset_photo(url).read_bytes() == jpeg
    # content addressed: the same photo on six scenes is stored once
    assert api._save_upload_ref(jpeg) == url
    assert len(list((tmp_path / "refs").iterdir())) == 1


def test_an_upload_url_cannot_escape_its_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "UPLOAD_REFS_DIR", tmp_path / "refs")
    (tmp_path / "refs").mkdir()
    (tmp_path / "secret.jpg").write_bytes(b"x")
    assert api._resolve_asset_photo("/refs/../secret.jpg") is None
    assert api._resolve_asset_photo("/refs/nope.jpg") is None


def test_asset_photos_still_resolve(tmp_path, monkeypatch):
    """The new /refs branch must not have broken the old shape."""
    root = tmp_path / "characters" / "michael"
    root.mkdir(parents=True)
    (root / "a.jpg").write_bytes(b"x")
    monkeypatch.setitem(api._PHOTO_ROOTS, "characters", tmp_path / "characters")
    assert api._resolve_asset_photo("/characters/michael/photo/a.jpg?thumb=1") is not None
    assert api._resolve_asset_photo("/characters/../etc/photo/passwd") is None


# --- and the graph actually carries them ------------------------------------

def test_every_billed_node_grounds_on_the_scenes_references():
    """The contract the Director graph builder relies on: refs land as
    ref_urls on the enhance, the keyframe AND the clip, because a face
    is not a property of one step."""
    refs = ["/characters/michael/photo/a.jpg", "/props/motorcycle/photo/a.jpg"]
    node = {"id": 1}
    urls = workflow_runner.node_reference_urls(
        node, {"ref_urls": refs, "image_url": ""}, {}, {})
    assert urls == refs
    # a wired keyframe leads, and is not sent twice when it is also a ref
    wired = workflow_runner.node_reference_urls(
        node, {"ref_urls": refs, "image_url": refs[0]}, {}, {})
    assert wired == refs


def test_an_empty_ref_list_reads_the_shot_back(tmp_path, monkeypatch):
    """The bug this closes: a Director chain freezes the shot's refs
    into every billed node at BUILD time, and a saved canvas beats a
    rebuild -- so a graph drawn before its scene had photos rendered
    blind for good, and attaching them later changed nothing. An empty
    ref_urls is no longer a promise that there is nothing to ground on.
    """
    refs = ["/characters/michael/photo/a.jpg", "/props/motorcycle/photo/b.jpg"]
    monkeypatch.setattr(
        "src.preprod.get_concept",
        lambda concept_id, path=None, account_id=None: {"shots": [{"n": 1, "refs": refs}]})
    urls = workflow_runner.node_reference_urls(
        {"id": 1}, {"concept_id": 121, "shot_n": 1,
                    "ref_urls": [], "image_url": ""}, {}, {})
    assert urls == refs


def test_a_graph_that_carries_refs_is_never_second_guessed(monkeypatch):
    """The frozen list wins whenever it has anything in it -- unpicking
    a reference on the canvas has to stick."""
    def boom(*a, **kw):                     # must not even be consulted
        raise AssertionError("read the shot back over an explicit list")

    monkeypatch.setattr("src.preprod.get_concept", boom)
    urls = workflow_runner.node_reference_urls(
        {"id": 1}, {"concept_id": 121, "shot_n": 1,
                    "ref_urls": ["/characters/michael/photo/a.jpg"],
                    "image_url": ""}, {}, {})
    assert urls == ["/characters/michael/photo/a.jpg"]


def test_a_node_with_no_shot_grounds_on_nothing(monkeypatch):
    """A free-standing library workflow has no shot to read back, and
    that is not an error -- grounding shapes, it never gates."""
    monkeypatch.setattr(
        "src.preprod.get_concept",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no shot")))
    assert workflow_runner.node_reference_urls(
        {"id": 1}, {"ref_urls": [], "image_url": ""}, {}, {}) == []


# --- a reference is a NAMED thing, not a loose picture -----------------------

def test_a_reference_url_names_its_asset():
    """Runway takes {uri, tag} and documents the tag as "used to
    reference the image in prompt text"; Higgsfield rewrites
    <<<element>>> to @element_name. Gemini has no tag field, so the same
    binding is a caption before the image -- and the caption has to name
    the asset, not just say "reference photo"."""
    from src import shootgen
    assert shootgen.reference_label(
        "/characters/michael/photo/IMG_0586.JPG") == (
        "Reference photo — Michael, the EXACT face and likeness:")
    assert shootgen.reference_label(
        "/props/leather-moto-jacket/photo/a.jpg") == (
        "Reference photo — Leather Moto Jacket, the EXACT object:")
    assert "location" in shootgen.reference_label(
        "/locations/studio-bedroom/photo/a.jpg")
    assert shootgen.reference_label("/refs/abc.jpg?thumb=1") == (
        "Reference photo supplied with this prompt:")


def test_the_prompt_names_the_photographs_that_are_actually_attached():
    """The scene writers invent "@Image 1 / @Image 2". Nothing in this
    repo emits that syntax and no renderer ever receives such a tag, so
    the one sentence saying which photograph was the face pointed at
    nothing. The jacket bound anyway -- "leather moto jacket" collides
    with its own caption -- and the face did not, which is the whole of
    why 155-158 came back as a stock leading man in an accurate jacket
    (2026-09-02)."""
    from src import shootgen
    prompt = (
        "Scene: The Oil Ritual -- Michael in his garage.\n\n"
        "REFERENCES: Use @Image 1 for Michael's face and @Image 2 for the "
        "leather moto jacket.\n\n"
        "CONTINUITY: Michael wears the @Image 2 leather jacket throughout.\n\n"
        "LOOK: heavy film grain.")
    out = shootgen.bind_references(prompt, [
        "/characters/michael/photo/IMG_0586.JPG",
        "/props/leather-moto-jacket/photo/IMG_0599.JPG",
        "/characters/michael/photo/IMG_0593.JPG",
        "/characters/michael/photo/IMG_0599.JPG",
    ])
    # the invented tags are gone -- from the block AND from the prose
    assert "@Image" not in out
    assert "Use @Image 1" not in out
    assert "Michael wears the leather jacket throughout." in out
    # what replaces them names the assets by the words reference_label
    # captions the images with, so prompt and captions agree
    assert out.startswith("REFERENCES —")
    assert '"Michael" — 3 photographs' in out
    assert '"Leather Moto Jacket"' in out
    assert "APPARENT AGE" in out          # the drift these renders showed
    assert "LOOK: heavy film grain." in out


def test_the_numbers_are_stripped_and_never_remapped():
    """The writer numbered its images before `attach_refs` had chosen
    anything, so "@Image 2" never referred to the second entry of this
    list. Guessing a mapping would be a guess wearing a fact's clothes."""
    from src import shootgen
    out = shootgen.bind_references(
        "ACTION: he lifts the @Image 3 helmet onto @Image 1's head.",
        ["/characters/michael/photo/a.jpg"])
    assert "@Image" not in out and "3" not in out.split("REFERENCES")[-1].split("ACTION")[-1]
    assert "he lifts the helmet onto 's head." in out or "helmet" in out


def test_no_references_means_no_reference_block():
    """A block describing images that are not there is worse than none:
    it spends the model's attention looking for them. A scene with no
    refs renders on its text, which is the documented behaviour."""
    from src import shootgen
    out = shootgen.bind_references(
        "Scene: a room.\n\nREFERENCES: Use @Image 1 for the face.\n\n"
        "LOOK: grainy.", [])
    assert "REFERENCES" not in out
    assert "@Image" not in out
    assert "Scene: a room." in out and "LOOK: grainy." in out


def test_an_unrecognised_url_is_simply_unlabelled():
    """No label is the old behaviour, never an error."""
    from src import shootgen
    for url in ("", "/nonsense", "/characters/michael/thumb/a.jpg",
                "https://example.com/a.jpg", None):
        assert shootgen.reference_label(url) == ""


def test_the_keyframe_call_captions_every_reference():
    """Each image part is preceded by the name of what it shows, in
    order -- a scene with two characters and two props otherwise leaves
    the model guessing which photo is the face."""
    from src import nano_banana
    refs = nano_banana.as_reference_list([
        ("Reference photo — Michael, the EXACT face and likeness:", b"\xff\xd8a"),
        ("Reference photo — Cyclops, the EXACT face and likeness:", b"\xff\xd8b"),
    ])
    assert [label for label, _ in refs] == [
        "Reference photo — Michael, the EXACT face and likeness:",
        "Reference photo — Cyclops, the EXACT face and likeness:"]
    assert [data for _, data in refs] == [b"\xff\xd8a", b"\xff\xd8b"]


def test_bare_bytes_still_work_unlabelled():
    """Old callers pass bytes and get the old behaviour."""
    from src import nano_banana
    assert nano_banana.as_reference_list(b"\xff\xd8x") == [("", b"\xff\xd8x")]
    assert nano_banana.as_reference_list([b"a", b"b"]) == [("", b"a"), ("", b"b")]
    assert nano_banana.as_reference_list(None) == []
    assert nano_banana.as_reference_list(["not bytes", 7, b""]) == []


# --- and the references reach the renderer the right way up -----------------

def _jpeg(size=(40, 20), orientation=None):
    import io

    from PIL import Image
    im = Image.new("RGB", size, (200, 30, 30))
    buf = io.BytesIO()
    if orientation is None:
        im.save(buf, format="JPEG")
    else:
        exif = im.getexif()
        exif[274] = orientation
        im.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_a_sideways_photo_is_turned_upright():
    """Every still off an iPhone is stored landscape with orientation 6
    -- a portrait only because a tag says so. We hand the renderers raw
    bytes, so a decoder that ignores the tag grounds a face lying on
    its side (2026-08-28)."""
    import io

    from PIL import Image
    fixed = imagery.upright(_jpeg((40, 20), orientation=6))
    with Image.open(io.BytesIO(fixed)) as im:
        assert im.size == (20, 40)                  # turned, not just tagged
        assert (im.getexif() or {}).get(274, 1) in (1, None)


def test_a_huge_photo_is_capped_before_it_is_sent():
    """Three untouched iPhone stills came to ~10MB of request body
    against an inline ceiling around 20MB, and these models tile an
    image at about a thousand pixels regardless -- the megabytes buy
    nothing and a heavy request is the first thing shed when the model
    is busy (2026-08-28)."""
    import io

    from PIL import Image
    big = _jpeg((4000, 3000))
    small = imagery.upright(big)
    with Image.open(io.BytesIO(small)) as im:
        assert max(im.size) == imagery.VISION_MAX_EDGE
        assert im.size == (imagery.VISION_MAX_EDGE, 1152)  # aspect kept
    assert len(small) < len(big)


def test_a_sideways_huge_photo_is_both_turned_and_capped():
    import io

    from PIL import Image
    fixed = imagery.upright(_jpeg((4000, 3000), orientation=6))
    with Image.open(io.BytesIO(fixed)) as im:
        assert im.size[1] > im.size[0]                     # turned upright
        assert max(im.size) == imagery.VISION_MAX_EDGE


def test_an_already_upright_photo_is_untouched():
    """No re-encode, no quality loss, on the majority that need nothing."""
    data = _jpeg((40, 20), orientation=1)
    assert imagery.upright(data) is data
    plain = _jpeg((40, 20))
    assert imagery.upright(plain) is plain


def test_an_uploaded_photo_is_not_saved_sideways(tmp_path, monkeypatch):
    """_to_jpeg used to convert("RGB") FIRST, which drops the EXIF it
    then needed -- baking an iPhone still in sideways and writing that
    unrecoverable file to data/refs. The Create button is the path that
    does this, so it never reached the workflow runner's fix."""
    import io

    from PIL import Image

    from app import api

    src = Image.new("RGB", (40, 20), (200, 30, 30))
    exif = src.getexif()
    exif[274] = 6                      # every photo off Mike's phone
    buf = io.BytesIO()
    src.save(buf, format="JPEG", exif=exif)

    out = api._to_jpeg(buf.getvalue())
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (20, 40), "the rotation must be baked in, not dropped"


def test_an_upright_upload_is_unchanged_in_shape():
    import io

    from PIL import Image

    from app import api

    src = Image.new("RGB", (40, 20), (30, 60, 200))
    buf = io.BytesIO()
    src.save(buf, format="JPEG")
    with Image.open(io.BytesIO(api._to_jpeg(buf.getvalue()))) as im:
        assert im.size == (40, 20)


def test_a_photo_that_is_not_an_image_is_skipped_not_raised():
    from app import api
    assert api._to_jpeg(b"not an image") is None


def test_unreadable_bytes_pass_straight_through():
    assert imagery.upright(b"not an image") == b"not an image"
    assert imagery.upright(b"") == b""


# --- every route that writes a concept grounds it ---------------------------
# Three routes create a concept and all three feed Director, so all
# three have to attach references. Two of them silently discarded the
# URLs until 2026-08-28; these are the regression guard.

def _fake_gemini(monkeypatch, scene_text):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("google.genai.Client", lambda api_key=None: object())
    monkeypatch.setattr("src.shootgen.reference_block",
                        lambda spark=None, client=None, db_path=None: "")
    monkeypatch.setattr(api, "_assets_all", lambda account_id=None: CAST)
    monkeypatch.setattr(
        "src.shootgen.generate_with_retry",
        # both response shapes: `brief` for the one-scene route
        # (parse_scene_brief_response), `scenes[]` for the N-scene one
        lambda c, m, p: json.dumps({"title": "The Garage Guest", "hook": "",
                                    "logline": "", "brief": scene_text,
                                    "scenes": [{"title": "The Garage Guest",
                                                "prompt": scene_text}]}))


def test_the_director_brief_grounds_its_scene_too(tmp_db, monkeypatch):
    """/api/pipeline/run — the Director brief's "Build the scene". Its
    concept lands on the same canvas and needs the same face."""
    _fake_gemini(monkeypatch, SCENE)
    job = wait_for_job(client.post(
        "/api/pipeline/run", data={"prompt": SCENE, "brand": "zeropage"},
    ).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    card = client.get("/api/pipeline/concepts?brand=zeropage").json()["items"][0]
    assert card["refs"][0] == "/characters/michael/photo/a.jpg"
    assert len(card["refs"]) == 3


def test_every_concept_writing_route_uses_the_one_collector():
    """The drift guard. Three copies of the reference-collecting loop is
    how two routes ended up throwing the URLs away; if a fourth copy
    appears, this fails."""
    source = (pathlib.Path(api.__file__)).read_text()
    # the one place uploads/asset_photos are read off a form
    assert source.count('form.getlist("asset_photos")') == 1
    assert source.count('form.getlist("files")') == 1
    # and every route that writes a concept attaches what it collected.
    # Counted without the paren because /scenes/run now HANDS the
    # function to src/scene_chain.py rather than calling it inline --
    # src/ cannot list asset photos itself, so the app injects the one
    # implementation instead of a second copy growing down there.
    assert source.count("_attach_scene_refs") == 4    # 1 def + 2 calls + 1 injection
    assert "attach_refs=_attach_scene_refs" in source
