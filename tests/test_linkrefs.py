"""A pasted link becomes a reference frame (src/linkrefs.py, 2026-10-01).

The rule under test everywhere here: the MODEL never handles a URL. The
link is read off the person's own message by the route, its frames are
screened and registered server-side, and the model is told one line --
"N frames from the link you pasted are on the sheet" -- never the
address. tests/conftest.py blocks the network; every fetch is injected.
"""
import json
import types as pytypes

import pytest
from fastapi.testclient import TestClient

from app import api, auth
from app.main import app
from src import assistant_brain, charge, creative_guide, gemini_utils, guide_tools, linkrefs, scene_chain

GHOST = "https://www.ghostlifestyle.com/products/ghost-energy-orange-cream"
PAGE = """<!doctype html><html><head>
<title>GHOST Energy Orange Cream | GHOST</title>
<meta property="og:title" content="GHOST Energy -- Orange Cream">
<meta property="og:image" content="//cdn.shopify.com/s/files/can-front.jpg?v=1">
<meta property="og:image:secure_url" content="https://cdn.shopify.com/s/files/can-front.jpg?v=1">
<meta property="og:image" content="/s/files/can-back.jpg">
<meta name="twitter:image" content="https://cdn.shopify.com/s/files/can-tw.jpg">
<link rel="image_src" href="https://cdn.shopify.com/s/files/can-link.jpg">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Orange Cream",
 "image":["https://cdn.shopify.com/s/files/ld-1.jpg", {"@type":"ImageObject","url":"https://cdn.shopify.com/s/files/ld-2.jpg"}]}
</script>
</head><body><p>cans</p></body></html>"""


@pytest.fixture
def public(monkeypatch):
    """refbin.public_host resolves the name (DNS, which conftest cannot
    block and which an offline suite must not depend on). Stand in a
    pure check for the extraction tests; the refusal test keeps the
    real one, which needs no network for a literal address."""
    from src import refbin

    monkeypatch.setattr(refbin, "public_host",
                        lambda host: not host.startswith(("127.", "10.", "localhost", "::1", "169.254.")))


def _page(body=PAGE, status=200, kind="text/html", url=GHOST, error=""):
    return {"url": url, "status": status, "content_type": kind,
            "body": body.encode() if isinstance(body, str) else body, "error": error}


# ---------- reading the person's message ----------

def test_extract_links_reads_the_message_and_only_http():
    text = ("look at this: " + GHOST + ". and https://www.instagram.com/p/abc/ "
            "(also https://x.example/a) ftp://no.example/x www.bare.example "
            + GHOST + " https://d.example https://e.example")
    assert linkrefs.extract_links(text) == [GHOST, "https://www.instagram.com/p/abc/",
                                            "https://x.example/a"]
    assert linkrefs.extract_links("no links here") == []
    assert linkrefs.extract_links("https://en.wikipedia.org/wiki/Can_(band)") == [
        "https://en.wikipedia.org/wiki/Can_(band)"]


# ---------- what a page gives up ----------

def test_a_product_page_gives_up_its_preview_images_in_order_resolved_and_capped(public):
    got = linkrefs.read_link(GHOST, get=lambda url: _page())
    urls = [c["image_url"] for c in got["images"]]
    # og:image first (both, protocol-relative and relative resolved against the
    # page), the secure_url duplicate folded in, then twitter, then the link tag;
    # the JSON-LD frames fall off the cap of four
    assert urls == ["https://cdn.shopify.com/s/files/can-front.jpg?v=1",
                    "https://www.ghostlifestyle.com/s/files/can-back.jpg",
                    "https://cdn.shopify.com/s/files/can-tw.jpg",
                    "https://cdn.shopify.com/s/files/can-link.jpg"]
    assert len(got["images"]) == linkrefs.MAX_PER_LINK
    assert got["title"] == "GHOST Energy -- Orange Cream"
    assert got["note"] == ""
    for c in got["images"]:
        assert c["source"] == linkrefs.SOURCE and c["source_url"] == GHOST
        assert c["title"] == "GHOST Energy -- Orange Cream"
        assert c["credit"] == "www.ghostlifestyle.com"


def test_json_ld_product_images_count_when_the_meta_tags_are_missing(public):
    body = ("<html><head><title>Plain</title><script type='application/ld+json'>"
            + json.dumps({"@graph": [{"@type": "WebPage"}, {"@type": ["Product", "Thing"],
                                                              "image": ["/a.jpg", {"url": "b.jpg"}]}]})
            + "</script></head></html>")
    got = linkrefs.read_link("https://shop.example/p/1", get=lambda url: _page(body, url="https://shop.example/p/1"))
    assert [c["image_url"] for c in got["images"]] == ["https://shop.example/a.jpg",
                                                       "https://shop.example/p/b.jpg"]
    assert got["title"] == "Plain"


def test_one_file_under_two_schemes_is_one_frame_and_the_logo_goes_last(public):
    """Shopify's head, read live off a Ghost product page (2026-10-01):
    og:image is the site LOGO as http, og:image:secure_url the same logo
    as https, and the product photos sit in the JSON-LD. The logo is not
    dropped (the look rejects it with the reason on the card), but it
    must not take the first slot, nor two of the four."""
    body = """<html><head><title>GHOST LEGEND | ORANGE CREAM</title>
    <meta property="og:image" content="http://shop.example/cdn/t/1/assets/logo.png?v=1">
    <meta property="og:image:secure_url" content="https://shop.example/cdn/t/1/assets/logo.png?v=1">
    <script type="application/ld+json">{"@type":"Product","image":[
      "http://shop.example/cdn/files/LegendOrangeCream_grande.webp",
      "http://shop.example/cdn/files/LegendOrangeCreamBack_grande.webp",
      "http://shop.example/cdn/shopifycloud/no-image-2048_large.gif",
      "https://shop.example/cdn/files/mark.svg"]}</script></head></html>"""
    got = linkrefs.read_link("https://shop.example/products/legend", get=lambda url: _page(body))
    assert [c["image_url"] for c in got["images"]] == [
        "http://shop.example/cdn/files/LegendOrangeCream_grande.webp",
        "http://shop.example/cdn/files/LegendOrangeCreamBack_grande.webp",
        "https://shop.example/cdn/t/1/assets/logo.png?v=1",
        "http://shop.example/cdn/shopifycloud/no-image-2048_large.gif"]


def test_a_malformed_address_on_the_page_is_skipped_not_a_traceback(public):
    """drinkghost.com (live, 2026-10-01) writes `https:/cdn...` with one
    slash: a scheme and no host. It was an IndexError out of a function
    documented never to raise; now it is skipped and the good tags count."""
    body = """<html><head><title>GHOST ENERGY</title>
    <meta property="og:image" content="https:/cdn.example/one-slash.jpg">
    <meta property="og:image" content="https://cdn.example/fine.jpg">
    <meta name="twitter:image" content="mailto:nobody@example.com"></head></html>"""
    got = linkrefs.read_link("https://shop.example/p/1", get=lambda url: _page(body))
    assert [c["image_url"] for c in got["images"]] == ["https://cdn.example/fine.jpg"]
    assert got["title"] == "GHOST ENERGY"
    # and a parser that blows up outright still answers with a note
    import pytest as _pytest
    monkey = _pytest.MonkeyPatch()
    monkey.setattr(linkrefs, "parse_images", lambda html, base: 1 / 0)
    try:
        got = linkrefs.read_link("https://shop.example/p/1", get=lambda url: _page(body))
    finally:
        monkey.undo()
    assert got["images"] == [] and linkrefs.BLOCKED_NOTE in got["note"]


def test_json_ld_gives_the_pages_own_product_not_every_flavour_and_a_usable_size(public):
    """drinkghost.com, live 2026-10-01: the page's ProductGroup (one
    Product, a 300px thumbnail) is followed by a ProductGroup of every
    flavour. Only the first product's images count, with its own
    variants, and Shopify's documented width parameter is raised."""
    body = ("<html><head><title>GHOST ENERGY | ORANGE CREAM</title><script type='application/ld+json'>"
            + json.dumps([
                {"@type": "ProductGroup", "name": "Orange Cream", "hasVariant": [
                    {"@type": "Product", "image": "https://drinkghost.com/cdn/shop/files/OrangeCreamFront.webp?v=1&width=300",
                     "hasVariant": [{"@type": "Product", "image": "https://drinkghost.com/cdn/shop/files/OrangeCreamBack.webp?width=300"}]}]},
                {"@type": "ProductGroup", "name": "Every flavour", "hasVariant": [
                    {"@type": "Product", "image": "https://drinkghost.com/cdn/shop/files/Warheads.webp?width=300"},
                    {"@type": "Product", "image": "https://drinkghost.com/cdn/shop/files/Peaches.webp?width=300"}]}])
            + "</script><script type='application/ld+json'>"
            + json.dumps({"@type": "Product", "name": "4-pack", "image": "https://drinkghost.com/cdn/shop/files/4Pack.png?width=300"})
            + "</script></head></html>")
    got = linkrefs.read_link("https://drinkghost.com/products/x", get=lambda url: _page(body))
    assert [c["image_url"] for c in got["images"]] == [
        "https://drinkghost.com/cdn/shop/files/OrangeCreamFront.webp?v=1&width=1200",
        "https://drinkghost.com/cdn/shop/files/OrangeCreamBack.webp?width=1200"]
    # the size rule is Shopify's CDN only; another host's query is untouched
    assert linkrefs._usable_size("https://i.example/a.jpg?width=300") == "https://i.example/a.jpg?width=300"
    assert linkrefs._usable_size("https://s.example/cdn/shop/files/a.jpg?width=2048") == "https://s.example/cdn/shop/files/a.jpg?width=2048"


def test_twitter_image_alone_is_enough(public):
    body = '<html><head><meta name="twitter:image" content="https://i.example/t.png"></head></html>'
    got = linkrefs.read_link("https://a.example/x", get=lambda url: _page(body))
    assert [c["image_url"] for c in got["images"]] == ["https://i.example/t.png"]
    assert got["title"] == "a.example"                    # no title: the host


def test_a_direct_image_link_is_its_own_frame(public):
    got = linkrefs.read_link("https://i.example/photo.jpg",
                             get=lambda url: _page(b"\xff\xd8\xff", kind="image/jpeg", url=url))
    assert [c["image_url"] for c in got["images"]] == ["https://i.example/photo.jpg"]
    assert got["images"][0]["source_url"] == "https://i.example/photo.jpg"


def test_an_oversized_page_is_read_to_the_cap_and_still_gives_up_its_head(public):
    body = PAGE.replace("<p>cans</p>", "<p>" + "x" * (linkrefs.MAX_HTML_BYTES + 4096) + "</p>")
    got = linkrefs.read_link(GHOST, get=lambda url: _page(body))
    assert len(got["images"]) == linkrefs.MAX_PER_LINK


@pytest.mark.parametrize("url", ["http://127.0.0.1/secret", "http://10.1.2.3/x",
                                 "http://localhost:8000/api", "http://[::1]/x",
                                 "ftp://files.example/x", "not a url"])
def test_a_non_public_address_is_refused_before_any_fetch(url):
    def get(u):
        pytest.fail("fetched a non-public address")
    got = linkrefs.read_link(url, get=get)
    assert got["images"] == [] and got["note"] == "not a public web address"


def test_a_redirect_into_a_private_range_is_refused(public, monkeypatch):
    """requests' own redirect handling is bypassed on purpose: a public
    page that 302s to a link-local metadata address must not be followed."""
    import requests

    class Resp:
        def __init__(self, status, headers):
            self.status_code, self.headers = status, headers
            self.is_redirect = status in (301, 302, 303, 307, 308)

        def iter_content(self, n):
            yield b"<html></html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    hops = []

    def get(url, **kwargs):
        hops.append(url)
        assert kwargs["allow_redirects"] is False
        return Resp(302, {"location": "http://169.254.169.254/latest/meta-data/"})

    monkeypatch.setattr(requests, "get", get)
    got = linkrefs._get("https://public.example/page")
    assert got["error"] == "not a public address" and got["body"] == b""
    assert hops == ["https://public.example/page"]        # the private hop was never fetched


@pytest.mark.parametrize("page, note_has", [
    (_page("<html><head><title>Login</title></head></html>", status=403), "HTTP 403"),
    (_page("<html><head><title>Nothing</title></head><body>app shell</body></html>"), linkrefs.BLOCKED_NOTE),
    (_page("<html><head><meta property='og:image' content='https://i.example/logo.png'></head></html>",
           url="https://www.instagram.com/accounts/login/"), "sign-in"),
    (_page(b"", status=0, error="fetch failed: ConnectionError"), "ConnectionError"),
])
def test_a_page_that_will_not_give_up_its_image_says_so(public, page, note_has):
    got = linkrefs.read_link("https://www.instagram.com/p/abc/", get=lambda url: page)
    assert got["images"] == []
    assert linkrefs.BLOCKED_NOTE in got["note"] and note_has in got["note"]


def test_read_link_never_raises(public):
    def get(url):
        raise RuntimeError("boom")
    got = linkrefs.read_link(GHOST, get=get)
    assert got["images"] == [] and "boom" not in got["note"] and linkrefs.BLOCKED_NOTE in got["note"]


# ---------- the sheet row, with real ids ----------

def _read(url):
    return {"url": url, "title": "GHOST Energy -- Orange Cream", "note": "", "images": [
        {"source": "link", "image_url": "https://cdn.example/front.jpg", "source_url": url,
         "title": "GHOST Energy -- Orange Cream", "credit": "www.ghostlifestyle.com"},
        {"source": "link", "image_url": "https://cdn.example/collage.jpg", "source_url": url,
         "title": "GHOST Energy -- Orange Cream", "credit": "www.ghostlifestyle.com",
         "fallback_url": "https://cdn.example/collage-thumb.jpg"}]}


def _screen(candidates, need, **kwargs):
    assert need["role"] == "link"
    keep, cut = candidates
    return {"ok": True, "checked": True, "note": "1 of 2 frame(s) kept",
            "keepers": [{**keep, "why": "", "kept_for": "the can, front, clean"}],
            "rejected": [{**cut, "why": "collage -- not a clean frame", "flags": ["collage"]}]}


def test_link_sheet_screens_registers_and_keeps_the_rejected_frame_on_the_sheet(pg):
    links = assistant_brain.link_sheet([GHOST], brand="zeropage", dsn=pg, read=_read, screen=_screen)
    assert links["links"] == 1 and links["ok"] and links["checked"]
    [row] = links["sheet"]
    assert row["role"] == "link" and row["query"] == "GHOST Energy -- Orange Cream"
    assert [k["kept_for"] for k in row["keepers"]] == ["the can, front, clean"]
    assert [r["why"] for r in row["rejected"]] == ["collage -- not a clean frame"]
    assert all(f["source_url"] == GHOST and f["source"] == "link"
               for f in row["keepers"] + row["rejected"])
    # the ids are real: keep_references redeems them, the second through its fallback
    ids = [row["keepers"][0]["id"], row["rejected"][0]["id"]]
    assert all(i.startswith("lin-") for i in ids)
    fetched = []

    def fetch(url):
        fetched.append(url)
        return None if url.endswith("collage.jpg") else "/refs/" + url.rsplit("/", 1)[1][:5] + ".jpg"

    kept = assistant_brain.keep_references(ids, dsn=pg, fetch=fetch)
    assert [k["url"] for k in kept["kept"]] == ["/refs/front.jpg", "/refs/colla.jpg"]
    assert kept["refused"] == []
    assert "https://cdn.example/collage-thumb.jpg" in fetched
    assert kept["kept"][0]["source_url"] == GHOST


def test_a_frame_nobody_could_look_at_is_still_offered_because_the_person_chose_it(pg):
    links = assistant_brain.link_sheet(
        [GHOST], dsn=pg, read=_read,
        screen=lambda c, n, **k: {"checked": False, "keepers": [], "rejected": [], "note": "no model client"})
    [row] = links["sheet"]
    assert len(row["keepers"]) == 2 and row["rejected"] == []
    assert "not looked at" in row["note"] and "no model client" in row["note"]
    assert links["checked"] is False and links["ok"]


def test_a_link_with_nothing_behind_it_is_a_row_with_a_note_not_a_silent_one():
    links = assistant_brain.link_sheet(
        ["https://www.instagram.com/p/abc/"],
        read=lambda url: {"url": url, "title": "www.instagram.com", "images": [],
                          "note": linkrefs.BLOCKED_NOTE + " (it wants a sign-in)"},
        screen=lambda *a, **k: pytest.fail("nothing to screen"),
        remember=lambda *a, **k: pytest.fail("nothing to register"))
    [row] = links["sheet"]
    assert row["role"] == "link" and row["query"] == "www.instagram.com"
    assert row["keepers"] == [] and row["rejected"] == []
    assert linkrefs.BLOCKED_NOTE in row["note"]
    assert not links["ok"] and "gave up no image" in links["note"]
    note = assistant_brain.link_note(links)
    assert "gave up no image" in note and "drop it in" in note
    assert "instagram" not in note                            # not even the host


def test_a_title_that_is_itself_an_address_is_not_the_label():
    assert assistant_brain._link_label({"url": GHOST, "title": "see www.ghost.com/x"}) == "www.ghostlifestyle.com"
    assert assistant_brain._link_label({"url": GHOST, "title": ""}) == "www.ghostlifestyle.com"
    assert assistant_brain._link_label({"url": GHOST, "title": "  GHOST  Orange "}) == "GHOST Orange"


def test_link_sheet_without_links_is_none():
    assert assistant_brain.link_sheet([]) is None
    assert assistant_brain.link_sheet(None) is None


def _links():
    return assistant_brain.link_sheet(
        [GHOST], read=_read, screen=_screen,
        remember=lambda c, query="", **k: [{**x, "id": f"lin-{i}"} for i, x in enumerate(c)])


def test_merge_puts_the_link_row_first_and_the_model_line_names_no_address():
    links = _links()
    hunted = {"ok": True, "checked": True, "faces": 1, "note": "looked at 3, kept 2",
              "sheet": [{"role": "place", "query": "wet bar", "keepers": [], "rejected": [], "note": ""}]}
    merged = assistant_brain.merge_sheets(links, hunted)
    assert [r["role"] for r in merged["sheet"]] == ["link", "place"]
    assert merged["faces"] == 1 and merged["links"] == 1 and merged["ok"]
    assert merged["note"].startswith("2 frame(s) from the link(s) you pasted, 1 kept; looked at 3")
    assert assistant_brain.merge_sheets(None, hunted) is hunted
    assert assistant_brain.merge_sheets(links, None) is links
    note = assistant_brain.link_note(links)
    assert note.startswith("2 frame(s) from the link they pasted are already on the contact sheet")
    assert "1 kept" in note
    for secret in (GHOST, "ghostlifestyle", "cdn.example", "front.jpg"):
        assert secret not in note
    assert assistant_brain.link_note(None) == ""


# ---------- the model never sees the address ----------

def test_check_args_still_refuses_a_url_the_model_puts_in_a_tool_argument():
    with pytest.raises(guide_tools.Refused):
        guide_tools.check_args("find_references", {"scene": "the can on " + GHOST})
    with pytest.raises(guide_tools.Refused):
        guide_tools.check_args("keep_references", {"candidate_ids": [GHOST]})


class _Resp:
    def __init__(self, text=None, calls=()):
        self.text = text
        self.function_calls = [pytypes.SimpleNamespace(name=n, args=a) for n, a in calls]
        self.candidates = [pytypes.SimpleNamespace(content=pytypes.SimpleNamespace(role="model", parts=[]))]


def _texts(contents):
    out = []
    for c in contents:
        for p in getattr(c, "parts", []) or []:
            if getattr(p, "text", None):
                out.append(p.text)
    return out


def test_a_tools_turn_merges_the_link_row_ahead_of_the_hunt_and_tells_the_model_once(monkeypatch):
    responses = [
        _Resp(calls=[("find_references", {"scene": "a can on a wet bar"})]),
        _Resp(text=json.dumps({"message": "Your link's frames are on the sheet.", "choices": [],
                               "brief": ""})),
    ]
    seen = []

    def generate(client, model, contents, **kwargs):
        seen.append((list(contents), kwargs))
        r = responses.pop(0)
        return r if kwargs.get("raw") else r.text

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    hunted = {"ok": True, "checked": True, "note": "kept 1", "faces": 0,
              "sheet": [{"role": "place", "query": "wet bar", "keepers": [], "rejected": [], "note": ""}]}

    def run_tool(name, args):
        run_tool.attachments["sheet"] = hunted
        return "kept c-1"
    run_tool.attachments = {}

    reply = creative_guide.respond(
        creative_guide.Conversation(messages=[{"role": "user", "content": "refs for " + GHOST}]),
        client=object(), brand="zeropage", grounding={}, tools=[dict(assistant_brain.FIND_SPEC)],
        run_tool=run_tool, links=_links())
    assert [r["role"] for r in reply["sheet"]["sheet"]] == ["link", "place"]
    assert reply["message"] == "Your link's frames are on the sheet."
    contents, kwargs = seen[0]
    texts = _texts(contents)
    # the person's own message still carries the address (it is theirs); the
    # feature adds ONE line about the sheet and never the URL itself
    assert any("2 frame(s) from the link they pasted" in t for t in texts)
    assert sum(GHOST in t for t in texts) == 1 and texts[1].endswith(GHOST)
    assert GHOST not in kwargs["config"].system_instruction
    assert "cdn.example" not in " ".join(texts) and "cdn.example" not in kwargs["config"].system_instruction


def test_a_plain_turn_carries_the_link_sheet_too(monkeypatch):
    seen = []

    def generate(client, model, contents, **kwargs):
        seen.append(list(contents))
        return json.dumps({"message": "On the sheet.", "choices": [], "brief": ""})

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    reply = creative_guide.respond(
        creative_guide.Conversation(messages=[{"role": "user", "content": "use " + GHOST}]),
        client=object(), brand="zeropage", grounding={}, links=_links())
    assert reply["sheet"]["sheet"][0]["role"] == "link" and reply["sheet"]["links"] == 1
    assert any("already on the contact sheet" in t for t in _texts(seen[0]))
    # and with no links, byte for byte what it was
    reply = creative_guide.respond(
        creative_guide.Conversation(messages=[{"role": "user", "content": "hi"}]),
        client=object(), brand="zeropage", grounding={})
    assert reply["sheet"] is None
    assert not any("contact sheet" in t for t in _texts(seen[1]))


# ---------- the route ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "guide-user"})
    monkeypatch.setattr(auth, "current_account", lambda request: {"slug": "zeropage"})
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    # the account here is a made-up id with no plan and no balance: the
    # Create gate (tested in test_spend_gates.py) is held open
    monkeypatch.setattr(charge, "create_refusal_code", lambda *a, **k: None)
    app.dependency_overrides[auth.current_account_id] = lambda: 42
    yield TestClient(app, headers={"X-ZPF-Model-Connection": "1"})
    app.dependency_overrides.pop(auth.current_account_id, None)


def _wait(client, job_id):
    import time
    for _ in range(200):
        body = client.get(f"/api/jobs/{job_id}").json()
        if body.get("status") in ("done", "error", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_the_route_reads_the_link_off_the_persons_message_never_a_tool_argument(client, monkeypatch):
    from src import imagesearch, refcheck

    async def refs(form, **kwargs):
        return [], [], []

    monkeypatch.setattr(api, "_collect_refs", refs)
    monkeypatch.setattr(scene_chain, "ground", lambda *a, **k: {})
    monkeypatch.setattr(api, "_guide_tools", lambda account_id, **k: (None, None))
    read_urls, screened = [], []

    def read_link(url, **kwargs):
        read_urls.append(url)
        return _read(url)

    def screen(candidates, need, **kwargs):
        screened.append((need, kwargs.get("brand"), kwargs.get("account_id")))
        return _screen(candidates, need)

    monkeypatch.setattr(linkrefs, "read_link", read_link)
    monkeypatch.setattr(refcheck, "screen", screen)
    monkeypatch.setattr(imagesearch, "remember",
                        lambda c, query="", **k: [{**x, "id": f"lin-{i}"} for i, x in enumerate(c)])
    seen = []

    def generate(client, model, contents, **kwargs):
        seen.append((list(contents), kwargs))
        return json.dumps({"message": "Two frames from your link are on the sheet.",
                           "choices": [], "brief": ""})

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    r = client.post("/api/creative-guide", data={"conversation": json.dumps({"messages": [
        {"role": "assistant", "content": "What are we shooting?"},
        {"role": "user", "content": "the orange cream can: " + GHOST + " -- find me references"}]})})
    assert r.status_code == 200
    body = _wait(client, r.json()["job_id"])
    assert body["status"] == "done", body
    reply = body["reply"]
    assert read_urls == [GHOST]
    assert screened == [({"role": "link", "query": "GHOST Energy -- Orange Cream",
                          "want": "the picture on the page the person pasted (GHOST Energy -- Orange Cream)"},
                         "zeropage", 42)]
    [row] = reply["sheet"]["sheet"]
    assert row["role"] == "link" and row["query"] == "GHOST Energy -- Orange Cream"
    assert [k["id"] for k in row["keepers"]] == ["lin-0"] and [x["id"] for x in row["rejected"]] == ["lin-1"]
    assert row["keepers"][0]["source_url"] == GHOST
    assert row["rejected"][0]["why"] == "collage -- not a clean frame"
    # the model got the one line, and the address only where the person typed it
    contents, kwargs = seen[0]
    texts = _texts(contents)
    assert any("2 frame(s) from the link they pasted" in t for t in texts)
    assert sum(GHOST in t for t in texts) == 1
    assert "cdn.example" not in " ".join(texts) + kwargs["config"].system_instruction


def test_a_message_without_a_link_reads_nothing(client, monkeypatch):
    async def refs(form, **kwargs):
        return [], [], []

    monkeypatch.setattr(api, "_collect_refs", refs)
    monkeypatch.setattr(scene_chain, "ground", lambda *a, **k: {})
    monkeypatch.setattr(api, "_guide_tools", lambda account_id, **k: (None, None))
    monkeypatch.setattr(linkrefs, "read_link", lambda url, **k: pytest.fail("read a link nobody pasted"))
    monkeypatch.setattr(gemini_utils, "generate_with_retry",
                        lambda *a, **k: json.dumps({"message": "ok", "choices": [], "brief": ""}))
    r = client.post("/api/creative-guide", data={"conversation": json.dumps({"messages": [
        {"role": "user", "content": "a can on a wet bar, no link"}]})})
    body = _wait(client, r.json()["job_id"])
    assert body["reply"]["sheet"] is None
