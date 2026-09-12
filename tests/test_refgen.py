"""src/refgen.py -- one rendered reference per spark, Midjourney first,
banked on the spark's own gen-<id> pass and read ahead of the crawl bin."""
import pytest

from src import imagesearch, mcp_server, preprod, refbin, refgen, scout


@pytest.fixture
def tmp_db(pg, tmp_path, monkeypatch):
    path = pg
    preprod.init(path)
    scout.init(path)
    imagesearch.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    monkeypatch.setattr(refbin, "REFS_DIR", tmp_path / "refs")
    monkeypatch.setenv("REFGEN_LANE", "1")
    monkeypatch.delenv("REFGEN_PROVIDERS", raising=False)
    return path


def real_jpeg() -> bytes:
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (9, 16), (20, 60, 70)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def a_spark(tmp_db):
    return mcp_server.bank_spark("zeropage", "the flooded mall keeps its lights on",
                                 rationale="r", dsn=tmp_db)["id"]


def stub_renderers(monkeypatch, **behaviour):
    """behaviour[name] is bytes to write, or an Exception to raise."""
    calls = []
    def make(name):
        def run(prompt, out, *extra):
            calls.append((name, prompt))
            b = behaviour.get(name, RuntimeError("not configured"))
            if isinstance(b, Exception):
                raise b
            out.write_bytes(b)
            return out
        return run
    monkeypatch.setattr(refgen, "_RENDERERS", {n: make(n) for n in refgen.PROVIDERS})
    return calls


def test_midjourney_is_tried_first_and_the_fallback_is_named(tmp_db, a_spark, monkeypatch):
    calls = stub_renderers(monkeypatch, midjourney=RuntimeError("credit spend not approved"),
                           nano=real_jpeg())
    out = refgen.render_for_finding(a_spark, "a wall of helmets under a red light", dsn=tmp_db)
    assert out["ok"] and out["provider"] == "nano"
    assert out["fell_back_from"] == ["midjourney"]
    assert [c[0] for c in calls] == ["midjourney", "nano"]


def test_the_prompt_is_the_hook_frame_plus_the_look(tmp_db, a_spark, monkeypatch):
    calls = stub_renderers(monkeypatch, midjourney=real_jpeg())
    out = refgen.render_for_finding(a_spark, "a drowned escalator under generator light", dsn=tmp_db)
    assert out["ok"] and out["provider"] == "midjourney"
    prompt = calls[0][1]
    assert prompt.startswith("a drowned escalator under generator light.")
    # the look block, not the Midjourney flag: `--ar 9:16 --style raw --s
    # 150` is appended by _midjourney itself, so it is not in what the
    # renderer is HANDED. prompts/look_antihero.txt carries the framing
    # in prose ("vertical 9:16") for the providers that take no flags.
    assert "teal" in prompt.lower() and "9:16" in prompt


def test_the_render_is_banked_on_its_own_pass_and_read_first(tmp_db, a_spark, monkeypatch):
    stub_renderers(monkeypatch, midjourney=real_jpeg())
    # a crawl-style image already on the spark's ordinary pass
    finding = scout.get_finding(a_spark, dsn=tmp_db)
    pass_id = scout.pass_id_for(finding, dsn=tmp_db)
    scout.bin_add("zeropage", pass_id, "/refs/crawl.jpg", source_url="https://x/1",
                  lane="agent", dsn=tmp_db)
    out = refgen.render_for_finding(a_spark, "hook", dsn=tmp_db)
    assert out["ok"] and out["pass_id"] == f"gen-{a_spark}"
    rows = scout.bin_for_finding(a_spark, dsn=tmp_db)
    assert [r["lane"] for r in rows] == ["generated", "agent"]
    assert rows[0]["source_url"].startswith("generated://midjourney/")
    assert rows[0]["url"].startswith("/refs/")


def test_the_cap_stops_the_spend(tmp_db, a_spark, monkeypatch):
    calls = stub_renderers(monkeypatch, midjourney=real_jpeg())
    monkeypatch.setattr(refgen, "rendered_today", lambda dsn=None: 8)
    out = refgen.render_for_finding(a_spark, "hook", dsn=tmp_db)
    assert not out["ok"] and "cap reached" in out["note"] and calls == []


def test_nothing_rendered_says_why(tmp_db, a_spark, monkeypatch):
    stub_renderers(monkeypatch)          # every provider raises
    out = refgen.render_for_finding(a_spark, "hook", dsn=tmp_db)
    assert not out["ok"] and "midjourney: RuntimeError" in out["note"]
    assert scout.bin_for_finding(a_spark, dsn=tmp_db) == []


def test_off_switch(tmp_db, a_spark, monkeypatch):
    monkeypatch.setenv("REFGEN_LANE", "0")
    calls = stub_renderers(monkeypatch, midjourney=real_jpeg())
    out = refgen.render_for_finding(a_spark, "hook", dsn=tmp_db)
    assert not out["ok"] and calls == []


def test_the_mcp_tool_is_published(tmp_db):
    import asyncio
    server = mcp_server.build_server(dsn=tmp_db)
    by_name = {t.name: t for t in asyncio.run(server.list_tools())}
    assert "imagine_reference" in by_name
    assert set(by_name["imagine_reference"].input_schema["properties"]) == {"finding_id", "hook_frame"}


def test_a_picked_photo_on_a_crawl_spark_stays_with_that_spark(tmp_db, monkeypatch):
    """The crawl banks eight sparks against one pass. A photo picked for
    one of them (2026-09-06: Pinterest picks via `reference`) goes on
    that spark's own agent-<id> pass and reads first; the crawl bin
    still follows, and the sibling spark never sees the pick."""
    a = scout.record("zeropage", {"spark": "the bleached sector", "score": 0.7},
                     pass_id="crawl-1", dsn=tmp_db)
    b = scout.record("zeropage", {"spark": "the salt city", "score": 0.7},
                     pass_id="crawl-1", dsn=tmp_db)
    scout.bin_add("zeropage", "crawl-1", "/refs/crawl.jpg", source_url="https://x/c",
                  lane="instagram", dsn=tmp_db)
    monkeypatch.setattr(refbin, "fetch", lambda url: "/refs/pick.jpg")
    monkeypatch.setattr(mcp_server, "_reachable", lambda url: True)

    out = mcp_server.bank_reference(a, image_url="https://i.pinimg.com/736x/p.jpg",
                                    source_url="https://www.pinterest.com/pin/1/", dsn=tmp_db)
    assert out["ok"] and out["pass_id"] == f"agent-{a}"
    assert [r["url"] for r in scout.bin_for_finding(a, dsn=tmp_db)] == ["/refs/pick.jpg", "/refs/crawl.jpg"]
    assert [r["url"] for r in scout.bin_for_finding(b, dsn=tmp_db)] == ["/refs/crawl.jpg"]
    assert scout.get_finding(a, dsn=tmp_db)["pass_id"] == "crawl-1"


def test_a_still_of_michael_goes_to_nano_with_his_photos(monkeypatch, tmp_path):
    """Midjourney leads for everything except his face: nano is the one
    renderer that can be handed his real photos, and it goes first. The
    Soul path rendered somebody else (2026-09-06), so it is never first
    for him; the prompt opens by naming the attached man as the subject
    and the photos ride as labelled reference parts."""
    monkeypatch.delenv("REFGEN_PROVIDERS", raising=False)
    assert refgen.provider_order() == ("midjourney", "nano", "higgsfield")
    assert refgen.provider_order(identity=True) == ("nano", "midjourney", "higgsfield")
    assert refgen.is_identity("Michael at the gate, visor up", "antihero")
    assert not refgen.is_identity("a stranger at the gate", "zeropage")

    prompt = refgen.build_prompt("Michael at the gate, visor up", "antihero")
    assert prompt.startswith(refgen.LIKENESS_OPENER)
    assert "even light stubble" in prompt
    assert "NOT have a grown or" in prompt
    assert not refgen.build_prompt("a stranger at the gate", "antihero").startswith(
        refgen.LIKENESS_OPENER)

    from src import asset_shelf, nano_banana, refbin
    fake = [tmp_path / n for n in refgen.LIKENESS_PHOTOS]
    for f in fake:
        f.write_bytes(b"jpegbytes")
    monkeypatch.setattr(asset_shelf, "photos_for", lambda kind, slug: fake)
    monkeypatch.setattr(refbin, "to_jpeg", lambda data: b"JPEG" + data)
    monkeypatch.setattr(nano_banana, "has_key", lambda: True)
    seen = {}

    def fake_generate(prompt, out, **kw):
        seen.update(kw)
        out.write_bytes(b"img")
        return out
    monkeypatch.setattr(nano_banana, "generate_image", fake_generate)

    result = refgen.render(prompt, identity=True)
    assert result["provider"] == "nano"
    assert seen["model"] == refgen.LIKENESS_MODEL
    assert [label for label, _ in seen["reference_bytes"]] == [
        f"Reference photo {i} of Michael" for i in (1, 2, 3)]

    # Without his photos on disk, nano refuses rather than rendering a
    # stranger, and the next provider gets its turn.
    monkeypatch.setattr(asset_shelf, "photos_for", lambda kind, slug: [])
    seen.clear()
    result = refgen.render(prompt, identity=True)
    assert result["tried"][0][0] == "nano" and "likeness photos" in result["tried"][0][1]
