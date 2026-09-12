"""
The JSON API behind /ui -- the ported studio.html skin. One rule from
its build spec governs everything here: every control in that UI is
backed by a working endpoint, and GET /api/capabilities is derived
from what is actually wired (key presence, store reachability), never
a static dict someone forgets to update.

Adaptations from the spec, decided 2026-08-21: the pipeline surface is
the real pre-production loop (concepts -> approve = plan a shot list,
deny = reasons + note recorded as a correction AND a RAG feedback
chunk), not the removed pitch/editgen chain. Assets are the real
grounding entities (locations, characters, props); footage ingest is a
later phase. Analytics reads the real metrics snapshots -- no daily
rollups exist yet, so no daily chart is served.
"""
import hashlib
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src import (
    account_keys,
    accounts,
    asset_shelf,
    autonomy,
    autopilot,
    crag,
    db,
    entities,
    evalstore,
    generative,
    higgsfield,
    imagery,
    inspiration,
    instagram,
    manual_lane,
    preprod,
    presets,
    providers,
    rag,
    rag_eval,
    refbin,
    render_assets,
    render_specs,
    runway,
    scout,
    settings,
    timeline,
    winners,
    workflows,
    youtube,
)
from src.locations import IMAGE_EXTENSIONS

from . import auth, jobs, model_connections, workflow_runner
from . import creative_projects as creative_projects_routes

router = APIRouter(prefix="/api")

# Both live in their own module and mount UNDER /api, which is what makes
# their client paths /api/creative-projects and /api/model-connections.
# They are included here rather than in main.py so they inherit this
# router's auth dependency along with every other /api route -- and so a
# reader looking for "what is under /api" finds all of it in one place.
router.include_router(creative_projects_routes.router)
router.include_router(model_connections.router)

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
LOCATIONS_DIR = PROJECT_ROOT / "locations"
CHARACTERS_DIR = PROJECT_ROOT / "characters"
PROPS_DIR = PROJECT_ROOT / "props"
CRAG_REWRITE_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

# The deny screen's vocabulary. An enum, not free text, so denial
# reasons aggregate instead of fragmenting into synonyms.
DENY_REASONS = (
    "wrong location", "off-tone", "character drift",
    "pacing", "retrieval missed", "too generic",
)


def _eval_k() -> int:
    """How many results the eval scores per query -- a Dev Studio
    tunable (settings -> EVAL_K env -> 5), resolved per run so a
    change takes effect on the next run, no restart."""
    return settings.eval_k()


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


# --- capabilities -----------------------------------------------------------

def _gemini_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _rag_reachable() -> bool:
    """A real connect, not a config guess -- localhost Postgres answers in
    single-digit ms, and 'the store is down' must gate retrieve/evals
    honestly rather than surfacing as a wall of failed fetches."""
    try:
        conn = rag.connect()
        try:
            conn.close()
        except Exception:
            pass
        return True
    except Exception:
        return False


def compute_capabilities(account_id: Optional[int] = None) -> dict:
    """What the shell may render. Derived live, never a static dict.

    `account_id` is the TENANT, resolved server-side, and it exists for
    exactly one key: `manual_lane`. Everything else here is a property of
    the INSTALLATION -- a key is set or it is not -- and is the same
    answer for every caller, which is why this route is allowed to take
    no account at all (tests/test_tenancy.py's exempt list). The lane is
    a property of the ACCOUNT, so it needs one, and `None` -- nobody
    signed in, or a user with no membership -- reads as no lane, which is
    also what manual_lane's fail-closed rule says.
    """
    from src import promptgen

    gemini = bool(_gemini_key())
    store = _rag_reachable()
    return {
        # per-shot polish needs the in-flight promptgen.refine_prompt to
        # have landed, plus the shelf and the key it refines with
        "polish": gemini and store and hasattr(promptgen, "refine_prompt"),
        "assets.list": True,
        "assets.create": True,
        "retrieve": store and gemini,          # query embeds with Gemini
        "pipeline.concepts": True,
        "pipeline.run": gemini,
        # the scout crawls with the google_search tool on the same key
        # every other stage uses, so the key is the whole gate
        "scout": gemini,
        # the guide's default provider is Gemini on the same key; the
        # personal providers are reported per-account by
        # /api/model-connections, which is a different question
        "creative_guide": gemini,
        "pipeline.deny": True,                  # correction always lands; RAG chunk is best-effort
        "holds": True,
        "evals.golden": True,
        "evals.run": store and gemini,
        "analytics": True,
        "analytics.youtube": bool(os.environ.get("YOUTUBE_API_KEY")),
        "analytics.instagram": bool(instagram.access_token()),
        "runway.generate": runway.has_key(),
        # the Director's Generate node renders on whatever this account
        # holds a key for (providers.renderer_for), not on Runway alone
        "video.generate": providers.renderer_for(
            account_id, needs="generate_from_prompt") is not None,
        # `*.spend` is TRUE for anything a person drives (2026-09-09):
        # the click is the approval, so a key is the whole gate on a
        # human surface. It stays a live read for the unattended paths,
        # which still need *_SPEND_OK set for them on purpose -- see
        # runway.spend_approved. The UI reads these to decide whether to
        # dim a button, and dimming a button a person is allowed to
        # press was the whole complaint.
        "runway.spend": runway.has_key(),
        # Higgsfield is the other half of ZEROPAGE_AI_TOOLS, and it
        # bills its own API credits on the same terms
        "higgsfield.generate": higgsfield.has_key(),
        "higgsfield.spend": higgsfield.has_key(),
        "nano.generate": gemini,               # Nano Banana rides the Gemini key
        "workflows": True,
        "jobs": True,
        # deployment posture (app/main.py's DEV_TOOLS, read live like the
        # keys above): gates /ui elements that point into the dev console,
        # e.g. the rail's "legacy" link -- on a public deployment there is
        # no /studio to link to
        "dev_tools": os.environ.get("DEV_TOOLS") == "1",
        # The operator-only subscription lane (src/manual_lane.py), so
        # the Queue view can leave its section out entirely for everyone
        # else instead of rendering a panel that 404s.
        #
        # PRESENTATION ONLY, and this is the line worth not crossing: a
        # capability is what the shell may DRAW, never what the server
        # may DO. Every lane route re-asks manual_lane against the
        # account it resolved itself, so a caller who fakes this flag --
        # it is a JSON field in a response they can edit in a console --
        # gains a section full of cards that refuse. There is also no
        # write twin: the flag is granted with
        # `python -m src.accounts operator <slug> --on` and nowhere else,
        # because an account that can grant itself the lane is not gated.
        "manual_lane": manual_lane.manual_lane_allowed(account_id),
    }


@router.get("/capabilities")
def capabilities(account_id: Optional[int] = Depends(auth.optional_account_id)):
    """What the shell may draw. `optional_account_id` and not
    `current_account_id`, because this is the one route the shell asks
    BEFORE it knows whether the person has an account at all -- a 403
    here blanks the whole UI -- and because None is a perfectly good
    answer to "does this account have the lane": no."""
    return compute_capabilities(account_id)


def _account_card(a: dict) -> dict:
    """accounts rows name the label display_name and the accent
    accent_color; the shell wants the shorter names."""
    return {"id": a["id"], "slug": a["slug"],
            "label": a.get("display_name") or a["slug"],
            "accent": a.get("accent_color"), "role": a.get("role")}
@router.get("/scene-lengths")
def scene_lengths(account_id: int = Depends(auth.current_account_id)):
    """The scene lengths the composer offers, and which is the default --
    timeline.SCENE_SECONDS_CHOICES and scene_seconds() projected, so the
    select cannot drift from what the route will clamp to. The default
    follows ZEROPAGE_SCENE_SECONDS, which is also what the night writes."""
    default = timeline.scene_seconds()
    choices = sorted(set(timeline.SCENE_SECONDS_CHOICES) | {default})
    return {"choices": choices, "default": default,
            "min": timeline.MIN_SCENE_SECONDS, "max": timeline.MAX_SCENE_SECONDS}


@router.get("/brains")
def brains(account_id: int = Depends(auth.current_account_id)):
    """The model tiers the composer may offer, as a PROJECTION of
    gemini_utils.BRAINS rather than a second list (providers.render_options'
    rule). A hardcoded <option> in the template is a copy that goes stale
    the first time a tier is added or a model id moves.

    Not a capability: a capability answers "may the shell draw this", and
    the answer for the tiers is the same as for Create itself
    (`pipeline.run` -- the Gemini key). This is the menu behind a control
    that is already gated.

    Takes the account even though the menu is installation-wide, unlike
    /capabilities beside it. That route is exempt because the shell asks
    it BEFORE it knows whether the person has an account at all; this one
    is asked from inside Studio, which is already behind sign-in, so
    there is nothing to gain from being the one /api route a signed-in
    stranger can reach (tests/test_tenancy.py enforces exactly that).

    Local import: src.gemini_utils pulls in google.genai, and this module
    stays cheap to import (the shootgen convention above).
    """
    from src import gemini_utils
    return {"brains": gemini_utils.brain_options(),
            "default": gemini_utils.DEFAULT_BRAIN}


@router.get("/render-choices")
def render_choices(account_id: int = Depends(auth.current_account_id)):
    """The frames a scene can be written for, PROJECTED from
    src/render_specs.py rather than listed again here.

    There is deliberately no "resolution" beside it: a ratio in this
    project is a frame SIZE ("720:1280"), so width and height are the
    same choice, and offering a second control for a dimension the
    renderers do not take would be a pill that changes nothing.

    The label is derived, not stored -- one place decides that 720:1280
    is 9:16, so a size added to RUNWAY_RATIOS shows up here correctly
    without anyone remembering to name it.
    """
    from math import gcd

    def label(size: str) -> str:
        try:
            w, h = (int(n) for n in size.split(":"))
        except ValueError:
            return size
        step = gcd(w, h) or 1
        return f"{w // step}:{h // step}"

    return {
        "ratios": [{"id": r, "label": label(r), "size": r}
                   for r in render_specs.RUNWAY_RATIOS],
        "default": render_specs.RATIO_9_16,
    }


@router.get("/me")
def me(request: Request, account_id: int = Depends(auth.current_account_id)):
    """Who is signed in and which account they are acting as -- the
    account block at the bottom of the React shell's rail (2026-09-11).
    Composed from the same helpers the Jinja shell reads
    (auth.current_user / current_account / accounts.memberships), so the
    two shells can never disagree about who you are. Identity fields
    are the profile mirror's; the active account is real membership,
    with the `brand` cookie only a preference among the accounts you
    belong to."""
    user = auth.current_user(request) or {}
    member_of = accounts.memberships(user["id"]) if user.get("id") else []
    active = next((a for a in member_of if a["id"] == account_id), None)
    return {
        "user": {"id": user.get("id"), "email": user.get("email"),
                 "display_name": user.get("display_name") or (user.get("email") or "").split("@")[0],
                 "avatar_url": user.get("avatar_url")},
        "account": _account_card(active) if active else None,
        "accounts": [_account_card(a) for a in member_of],
    }


# --- the creative guide -----------------------------------------------------
# Conversational brief development. It writes NOTHING: no concept, no
# render, no spend beyond the one model call -- the Create button is
# still the only thing that writes scenes, which is why this route can
# be as chatty as it likes.
#
# Restored 2026-09-10 after being overwritten. src/creative_guide.py,
# app/creative_projects.py, app/model_connections.py and the client all
# survived; this route and the two include_routers above did not, and
# are rebuilt from the contract the client still states. Diff it against
# your editor's local history before trusting it to be what was there.

@router.post("/creative-guide")
async def creative_guide_reply(request: Request,
                               account_id: int = Depends(auth.current_account_id)):
    """One turn of the conversation, as a job.

    A job rather than a plain response because the reasoning tier takes
    tens of seconds and an open request that long is indistinguishable
    from a hang -- the client polls /api/jobs/{id} and shows `detail`.

    The header check is model_connections' own: a studio session is
    SameSite=None, so a cross-site form post must not be able to spend a
    personal model connection. It runs for every provider, not just the
    personal ones, because the cheapest place to refuse is before any
    work happens.
    """
    from src import creative_guide, scene_chain

    model_connections.mutation_header(request)
    form = await request.form()
    raw = form.get("conversation") or ""
    try:
        conversation = creative_guide.Conversation.model_validate_json(raw)
    except Exception:
        return _error(400, "bad_conversation", "that conversation could not be read")
    # A turn is a REPLY to something the person said, so the history has
    # to end with them. An assistant-last history would ask the model to
    # talk to itself, and it is worth refusing before anything is billed
    # rather than after.
    if conversation.messages[-1].role != "user":
        return _error(400, "bad_conversation",
                      "the conversation has to end with your own message")

    # The brand is the ACCOUNT's, never the submitted field: the guide
    # grounds on a brand's own library and inspiration accounts, and a
    # form value would let one brand's context be pulled while signed in
    # to another. The form's `brand` is ignored on purpose.
    account = auth.current_account(request) or {}
    brand = account.get("slug") if account.get("slug") in preprod.BRANDS else "antihero"

    provider = (form.get("guide_provider") or "gemini").strip().lower()
    model = (form.get("guide_model") or "").strip() or None
    personal = provider != "gemini"

    scope = None
    if personal:
        scope = model_connections.connection_scope(request, account_id)
        if not _personal_connected(provider, scope):
            # 409, and the client reads it as "offer the studio
            # assistant" -- checked BEFORE the job so a disconnected
            # provider never silently falls back onto Gemini credit.
            return _error(409, "model_not_connected",
                          f"Connect your {provider} account first.")
    elif not _gemini_key():
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    image_refs, ref_urls, _ = await _collect_refs(form)
    idea = (form.get("idea") or form.get("prompt") or "").strip()

    def work(job):
        # Grounded through scene_chain.ground -- the same scoped set a
        # Create would be handed (named in the idea, or explicitly
        # picked), so what the guide proposes is shaped by the material
        # a scene could actually be written from. It writes nothing.
        grounding = scene_chain.ground(idea, brand=brand, account_id=account_id,
                                       refs=ref_urls)
        note = lambda text: jobs.progress(job, 0.5, text)   # noqa: E731
        if personal:
            reply = creative_guide.respond_personal(
                conversation, provider=provider, scope=scope, model=model,
                brand=brand, grounding=grounding, image_refs=image_refs)
        else:
            from google import genai
            reply = creative_guide.respond(
                conversation, client=genai.Client(api_key=_gemini_key()),
                brand=brand, grounding=grounding, image_refs=image_refs,
                account_id=account_id, on_retry=note)
        # `billing` says WHOSE plan paid: a personal connection spends
        # the person's own ChatGPT/Claude subscription and never touches
        # this install's Gemini credit, and /costs must not count it.
        return {"reply": reply, "reference_urls": ref_urls,
                "billing": "personal_plan" if personal else "studio_credits",
                "detail": "ready"}

    job = jobs.start("guide", "creative guide", work, account_id=account_id)
    return {"job_id": job["id"]}


def _personal_connected(provider: str, scope) -> bool:
    """Is this person's own model account connected?

    Deliberately the narrow question, not model_connections.provider_status:
    that one also reports whether the CLI is installed and what models
    exist, which is what the settings panel needs and more than a guide
    turn should depend on. Never raises -- an unreachable connection
    reads as not connected, which is the safe answer.
    """
    from src import personal_models

    try:
        if provider == "chatgpt":
            return bool(personal_models.codex_session(scope).status().get("connected"))
        if provider == "claude":
            return bool(personal_models.claude_status(scope).get("connected"))
    except Exception:
        return False
    return False


# --- assets -----------------------------------------------------------------
# Path helpers mirror app/main.py's (photos_for / _entity_photos /
# safe_space_name); duplicated rather than imported to keep main -> api
# a one-way street.

def _slug(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip().replace(" ", "-").lower()
    return cleaned.strip("-.")


def _photo_names(base_dir: Path, folder: str) -> list:
    directory = base_dir / folder
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)


def _asset_photo_urls(kind: str, base_dir: Path, slug: str) -> list:
    """One asset's photos, as the URL they ride on everywhere.

    Through asset_shelf.photo_url rather than an f-string (2026-09-08,
    Mike: "the reference photos aren't appearing"). These strings are
    not only what the gallery draws -- _auto_refs stores them on the
    shot, and a site-relative /characters/... path is true only on the
    machine holding the folder. characters/, props/ and locations/ are
    gitignored AND dockerignored, so the deployed site 404s every one:
    four refs on the row, four empty tiles on the card, and a renderer
    reaching for a face it cannot fetch. photo_url returns the public
    R2 URL when R2 is configured, which src/asset_shelf.catalogue has
    handed the nightly graph since the same day -- two catalogues
    disagreeing about one photo's URL is the shape of bug this repo
    keeps finding.

    ?thumb=1 rides only on the local route: it is a query this app's own
    handler understands and R2 does not.
    """
    from src import asset_shelf as _shelf

    urls = []
    for fn in _photo_names(base_dir, slug):
        url = _shelf.photo_url(kind, slug, fn)
        urls.append(url if url.startswith("http") else f"{url}?thumb=1")
    return urls


def _location_photos(space: str) -> list:
    return _asset_photo_urls("location", LOCATIONS_DIR, space)


def _description_text(desc) -> str:
    """locations.description_json -> one readable paragraph."""
    if isinstance(desc, str):
        try:
            desc = json.loads(desc)
        except (ValueError, TypeError):
            return desc
    if not isinstance(desc, dict):
        return ""
    parts = []
    for key in ("space", "light_sources", "textures", "angles", "constraints"):
        value = desc.get(key)
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        if value:
            parts.append(f"{key.replace('_', ' ')}: {value}")
    return " · ".join(parts)


def _assets_all(account_id: Optional[int] = None) -> list:
    items = []
    for loc in preprod.list_locations(account_id=account_id):
        photos = _location_photos(loc["name"])
        items.append({
            "id": f"location-{loc['id']}", "category": "location",
            "name": loc["name"], "photos": photos,
            "poster": photos[0] if photos else None,
            "text": _description_text(loc.get("description")
                                      or loc.get("description_json") or ""),
            "meta": {"photo_count": loc.get("photo_count")},
            "created_at": loc.get("created_at"),
        })
    for c in entities.list_characters(account_id=account_id):
        slug = _slug(c["name"])
        photos = _asset_photo_urls("character", CHARACTERS_DIR, slug)
        items.append({
            "id": f"character-{c['id']}", "category": "character",
            "name": c["name"], "photos": photos,
            "poster": photos[0] if photos else None,
            "text": c.get("notes") or c.get("role") or "",
            "meta": {"role": c.get("role")},
            "created_at": c.get("created_at"),
        })
    for p in entities.list_props(account_id=account_id):
        slug = _slug(p["name"])
        photos = _asset_photo_urls("prop", PROPS_DIR, slug)
        items.append({
            "id": f"prop-{p['id']}", "category": "prop",
            "name": p["name"], "photos": photos,
            "poster": photos[0] if photos else None,
            "text": p.get("notes") or p.get("category") or "",
            "meta": {"kind": p.get("category")},
            "created_at": p.get("created_at"),
        })
    for rendered in render_assets.list_all(account_id=account_id):
        url = rendered["media_url"]
        kind = rendered["media_kind"]
        meta = {
            "provider": rendered["provider"],
            "model": rendered["model"],
            "type": kind,
        }
        for key in ("ratio", "duration", "references", "source", "framing",
                    "prompt_image"):
            if rendered["metadata"].get(key) is not None:
                meta[key] = rendered["metadata"][key]
        for key in ("project", "concept_id", "shot_n"):
            if rendered.get(key) is not None:
                meta[key] = rendered[key]
        items.append({
            "id": f"generated-{rendered['id']}", "category": "generated",
            "name": f"{rendered['provider']} {kind}",
            "photos": [url] if kind == "image" else [],
            "media": [{"url": url, "kind": kind}],
            "media_url": url, "media_kind": kind,
            "poster": url if kind == "image" else None,
            "text": rendered["prompt"], "meta": meta,
            "created_at": rendered.get("created_at"),
        })
    return items


@router.get("/assets")
def assets_list(q: Optional[str] = None, category: Optional[str] = None,
                limit: int = 200,
                account_id: int = Depends(auth.current_account_id),
):
    items = _assets_all(account_id)
    counts = {"all": len(items)}
    for cat in ("location", "character", "prop", "generated"):
        counts[cat] = sum(1 for i in items if i["category"] == cat)
    if category in ("location", "character", "prop", "generated"):
        items = [i for i in items if i["category"] == category]
    if q:
        needle = q.lower().strip()
        items = [i for i in items
                 if needle in (i["name"] + " " + (i["text"] or "")).lower()]
    return {"items": items[:limit], "total": len(items), "counts": counts}


@router.get("/media")
def media_list(q: Optional[str] = None, category: Optional[str] = None,
               kind: str = "image", limit: int = 500,
               account_id: int = Depends(auth.current_account_id)):
    """This account's saved media as one flat, newest-first list.

    Image-only is the safe default because this endpoint also feeds image
    reference pickers.  The Asset Bank requests ``kind=all`` so generated
    Runway clips appear in its gallery without being offered as still-image
    inputs to Nano or Runway. Photo dates come from the file on disk;
    generated media from its record.
    """
    from datetime import datetime, timezone

    items = []
    for asset in _assets_all(account_id):
        generated = asset["category"] == "generated"
        media = asset.get("media") or [
            {"url": url, "kind": "image"} for url in asset["photos"]]
        for entry in media:
            url = entry["url"]
            media_kind = entry.get("kind", "image")
            if kind != "all" and media_kind != kind:
                continue
            if generated:
                try:
                    mtime = datetime.fromisoformat(
                        str(asset.get("created_at") or "").replace("Z", "+00:00"))
                    if mtime.tzinfo is None:
                        mtime = mtime.replace(tzinfo=timezone.utc)
                except ValueError:
                    mtime = datetime.now(timezone.utc)
            else:
                target = _resolve_asset_photo(url)
                if target is None:
                    # Not on THIS disk. Once a photo's canonical URL is
                    # its R2 one (2026-09-08) that is the normal case on
                    # any machine but the one that saved it -- dropping
                    # it here would empty the reference picker on the
                    # deployed site while /api/assets listed the same
                    # photo happily. It is only the sort date that is
                    # unknown, so it sorts oldest rather than vanishing.
                    if not str(url).startswith("http"):
                        continue
                    mtime = datetime.fromtimestamp(0, tz=timezone.utc)
                else:
                    mtime = datetime.fromtimestamp(target.stat().st_mtime,
                                                    tz=timezone.utc)
            items.append({
                "url": url, "asset_id": asset["id"],
                "asset_name": asset["name"], "category": asset["category"],
                "kind": media_kind,
                "haystack": (asset["name"] + " " + (asset["text"] or "")).lower(),
                "date": mtime.date().isoformat(),
                "ts": mtime.timestamp(),
            })
    items.sort(key=lambda x: x["ts"], reverse=True)
    # counts are set totals, before any filter -- same rule as /api/assets
    counts = {"all": len(items)}
    for cat in ("location", "character", "prop", "generated"):
        counts[cat] = sum(1 for i in items if i["category"] == cat)
    if category in ("location", "character", "prop", "generated"):
        items = [i for i in items if i["category"] == category]
    if q:
        needle = q.lower().strip()
        items = [i for i in items if needle in i["haystack"]]
    for item in items:
        item.pop("haystack", None)
    return {"items": items[:limit], "counts": counts}


@router.get("/assets/search")
def assets_search(q: str = "", limit: int = 8, account_id: int = Depends(auth.current_account_id)):
    """Cross-category name search over characters/props/locations -- the
    `@` mention autocomplete's endpoint. Name-prefix matches rank first,
    substring matches after; slim rows (name, category, thumb) because
    the dropdown needs nothing heavier."""
    needle = q.lower().strip()
    items = _assets_all(account_id)
    if needle:
        starts = [i for i in items if i["name"].lower().startswith(needle)]
        start_ids = {i["id"] for i in starts}
        contains = [i for i in items
                    if needle in i["name"].lower() and i["id"] not in start_ids]
        items = starts + contains
    return {"items": [{"name": i["name"], "category": i["category"],
                       "thumb": i["poster"]}
                      for i in items[:max(1, min(limit, 20))]]}


@router.get("/assets/{category}/{item_id}")
def asset_detail(category: str, item_id: int, account_id: int = Depends(auth.current_account_id)):
    asset = next((i for i in _assets_all(account_id)
                  if i["id"] == f"{category}-{item_id}"), None)
    if asset is None:
        return _error(404, "not_found", "no such asset")
    return asset


# --- asset creation ----------------------------------------------------------
# The always-on create path (2026-08-26): /ui's Assets view creates
# entities through these, so asset creation survives a public deploy
# where the dev console (and its old form routes) is never registered.
# Every save also lands a small text chunk on the RAG "assets" shelf --
# the upload IS the grounding source, closing the gap where the memory
# bank and the vector library sat side by side without talking.

ASSETS_DOMAIN = asset_shelf.DOMAIN

# The shelf's format and source keys live in src/asset_shelf.py so this
# route and the backfill there write identical chunks -- two formats on
# one shelf means a re-ingest duplicates instead of replacing.
ingest_asset_chunk = asset_shelf.ingest_one
_drop_asset_chunk = asset_shelf.drop_one


def describe_entity_photos(kind: str, name: str, photos: list) -> dict:
    """The vision step for a character or prop, mirroring what a
    location has always got on upload. This is what makes the asset
    *searchable*: the RAG library is text-only, so an undescribed
    character retrieves on its typed name alone, never on how it looks.

    Never raises -- a failed vision call must not lose the photos or
    the entity row, exactly the locations contract."""
    api_key = _gemini_key()
    if not (api_key and photos):
        return {"ok": False, "description": None,
                "error": "no photos" if api_key else "GEMINI_API_KEY not set"}
    try:
        from google import genai

        from src import locations as locations_mod
        description = locations_mod.describe_entity(
            genai.Client(api_key=api_key), kind, name, photos)
        return {"ok": True, "description": description, "error": None}
    except Exception as e:
        return {"ok": False, "description": None, "error": str(e)}


def _mirror_photos_to_r2(plural: str, slug: str, saved) -> None:
    """Push newly saved asset photos to R2, best-effort.

    The counterpart of asset_shelf.photo_url returning an R2 URL: a
    photo added after the 2026-09-08 backfill would otherwise be handed
    out under a URL whose object was never uploaded -- a broken tile
    that looks exactly like the bug this whole change fixes, only newer.
    Never raises; an unconfigured or unreachable R2 leaves the file on
    local disk, where the /characters/... route still serves it.
    """
    try:
        from src import storage
        if not storage.configured():
            return
    except Exception:                                   # noqa: BLE001
        return
    for target in saved:
        try:
            storage.upload_file(target, key=f"{plural}/{slug}/{target.name}",
                                content_type="image/jpeg")
        except Exception as e:                          # noqa: BLE001
            print(f"note: R2 mirror failed for {plural}/{slug}/{target.name}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)


async def _save_uploaded_photos(base_dir: Path, slug: str, photos) -> tuple:
    """(first filename, count) -- mirrors the old dev-console handler."""
    images = [p for p in photos
              if getattr(p, "filename", "") and (p.content_type or "").startswith("image/")]
    if not images:
        return "", 0
    directory = base_dir / slug
    directory.mkdir(parents=True, exist_ok=True)
    saved = []
    for upload in images:
        target = directory / Path(upload.filename).name
        target.write_bytes(await upload.read())
        saved.append(target)
    _mirror_photos_to_r2(
        "characters" if base_dir == CHARACTERS_DIR else "props", slug, saved)
    return Path(images[0].filename).name, len(images)


@router.post("/assets/locations")
async def asset_create_location(request: Request, account_id: int = Depends(auth.current_account_id)):
    """Save a space's photos and describe it (vision) -- the describe is
    best-effort so a failed model call keeps the photos on disk to
    retry, exactly the old /locations/upload contract."""
    form = await request.form()
    name = (form.get("name") or "").strip()
    slug = _slug(name)
    if not slug:
        return _error(400, "invalid_name", "a space name is required")
    photos = [p for p in form.getlist("photos") if getattr(p, "filename", "")]
    images = [p for p in photos if (p.content_type or "").startswith("image/")]
    if not images:
        return _error(400, "no_photos", "at least one photo is required")

    space_dir = LOCATIONS_DIR / slug
    space_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for upload in images:
        target = space_dir / Path(upload.filename).name
        target.write_bytes(await upload.read())
        saved.append(target)
    _mirror_photos_to_r2("locations", slug, saved)

    described = False
    note = None
    description = None
    api_key = _gemini_key()
    if not api_key:
        note = "GEMINI_API_KEY is not set, so the photos were not described"
    else:
        try:
            from google import genai

            from src import locations as locations_mod
            description = locations_mod.describe_location(
                genai.Client(api_key=api_key), slug, saved)
            all_photos = sorted(
                p for p in space_dir.iterdir()
                if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
            preprod.add_location(slug, description,
                                 photo_count=len(all_photos), account_id=account_id)
            described = True
        except Exception as e:
            note = f"saved {len(saved)} photo(s) but could not describe the space: {e}"

    chunk = ingest_asset_chunk("location", slug, slug,
                               {"description": description or {}},
                               project=accounts.slug_of(account_id))
    return {"ok": True, "slug": slug, "described": described,
            "photos": len(saved), "note": note, "rag": chunk}


async def _create_entity(kind: str, request: Request, account_id: int):
    """Characters and props are the same shape: name + one labelled
    field + notes + photos. Save the photos, describe them (vision, so
    appearance is retrievable), store the row, put it on the shelf."""
    base_dir = CHARACTERS_DIR if kind == "character" else PROPS_DIR
    label = "role" if kind == "character" else "category"

    form = await request.form()
    name = (form.get("name") or "").strip()
    slug = _slug(name)
    if not slug:
        return _error(400, "invalid_name", "a name is required")
    field = (form.get(label) or "").strip()
    notes = (form.get("notes") or "").strip()
    ref, count = await _save_uploaded_photos(base_dir, slug, form.getlist("photos"))

    # resolved against THIS route's base_dir, not asset_shelf's module
    # constant -- they're the same in production, but the photos that
    # were just written are the ones to describe.
    saved_photos = [base_dir / slug / n for n in _photo_names(base_dir, slug)]
    vision = describe_entity_photos(kind, name, saved_photos)
    description = dict(vision["description"] or {})
    if notes:
        description["notes"] = notes

    # picked by kind, so the audit that checks every scoped call site
    # cannot see this one -- account_id is passed by hand, and stays that way
    add = entities.add_character if kind == "character" else entities.add_prop
    add(name=name, **{label: field},
        description=description or None,
        reference_image=ref, photo_count=count, notes=notes,
        account_id=account_id)

    chunk = ingest_asset_chunk(kind, slug, name, {
        label: field, "notes": notes, "description": description},
        project=accounts.slug_of(account_id))
    note = None if vision["ok"] else (
        f"photos saved but not described: {vision['error']}" if count
        else "no photos to describe")
    return {"ok": True, "slug": slug, "photos": count,
            "described": vision["ok"], "note": note, "rag": chunk}


@router.post("/assets/characters")
async def asset_create_character(request: Request, account_id: int = Depends(auth.current_account_id)):
    return await _create_entity("character", request, account_id)


@router.post("/assets/props")
async def asset_create_prop(request: Request, account_id: int = Depends(auth.current_account_id)):
    return await _create_entity("prop", request, account_id)


class BackfillBody(BaseModel):
    describe: bool = False


@router.post("/assets/backfill")
def assets_backfill(body: BackfillBody, account_id: int = Depends(auth.current_account_id)):
    """Put everything already on disk onto the shelf -- the catch-up for
    assets created before the shelf existed. `describe` also runs the
    vision step on undescribed cast/props: one billed call each, opt-in,
    and already-described assets are skipped rather than re-described.
    Runs as a job because a real library takes a while."""
    if body.describe and not _gemini_key():
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        client = None
        if body.describe:
            from google import genai
            client = genai.Client(api_key=_gemini_key())
        jobs.progress(job, 0.1, "walking assets")
        result = asset_shelf.backfill(db_path=None, describe=body.describe,
                                      gemini_client=client, account_id=account_id)
        detail = f"{result['ingested']} on the shelf"
        if result["described"]:
            detail += f" · {result['described']} described"
        if result["failed"]:
            detail += f" · {result['failed']} failed"
        return {"detail": detail, "output": json.dumps(result)}

    job = jobs.start("backfill", "assets → rag shelf", work, account_id=account_id)
    return {"job_id": job["id"]}


@router.delete("/assets/characters/{character_id}")
def asset_delete_character(character_id: int, account_id: int = Depends(auth.current_account_id)):
    row = entities.get_character(character_id, account_id=account_id)
    if row is None:
        return _error(404, "not_found", "no such character")
    entities.delete_character(character_id, account_id=account_id)
    _drop_asset_chunk("character", _slug(row["name"]))
    return {"deleted": character_id}


@router.delete("/assets/props/{prop_id}")
def asset_delete_prop(prop_id: int, account_id: int = Depends(auth.current_account_id)):
    row = entities.get_prop(prop_id, account_id=account_id)
    if row is None:
        return _error(404, "not_found", "no such prop")
    entities.delete_prop(prop_id, account_id=account_id)
    _drop_asset_chunk("prop", _slug(row["name"]))
    return {"deleted": prop_id}


# --- retrieval --------------------------------------------------------------

class RetrieveBody(BaseModel):
    query: str
    k: int = Field(default=5, ge=1, le=20)
    domain: Optional[str] = None


@router.post("/retrieve")
def retrieve(body: RetrieveBody, account_id: int = Depends(auth.current_account_id)):
    """One endpoint serves the Studio grounding rail, the Evals probe,
    and the harness -- the same scorer everywhere, per the spec."""
    query_text = body.query.strip()
    if not query_text:
        return _error(400, "empty_query", "query text is required")
    started = time.perf_counter()
    try:
        conn = rag.connect()
        try:
            hits = rag.query(query_text, rag.make_client(), conn,
                             k=body.k, domain=body.domain or None,
                             prefer_project=accounts.slug_of(account_id))
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        return _error(503, "retrieval_unavailable", str(e))
    return {
        "hits": hits,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "model": rag.EMBED_MODEL,
    }


# --- pipeline (adapted to pre-production) -----------------------------------

def _concept_card(c: dict, subscription_ids: Optional[set] = None) -> dict:
    status = "shot" if c.get("shot_done") else (
        "planned" if c.get("has_shot_list") else "idea")
    location_names = [loc["name"] for loc in c.get("locations") or []]
    # ONE line saying what happens, so the board can be scanned instead
    # of read (2026-08-31). `card_line` is the purpose-written label;
    # `logline` is 2-4 sentences of idea record on the scene-brief path
    # and only a fallback here; the prompt is the last resort.
    first_shot = (c.get("shots") or [{}])[0]
    summary = preprod.concept_summary(
        c.get("card_line") or "",
        c.get("logline") or "",
        first_shot.get("prompt") or "",
    ) if c.get("is_scene") else ""
    grounded = []
    for name in location_names:
        photos = _location_photos(name)
        grounded.append({"name": name,
                         "poster": photos[0] if photos else None})
    return {
        "id": c["id"], "n": f"SHOOT-{c['id']:02d}",
        "title": c.get("title"), "hook": c.get("hook"),
        "logline": c.get("logline") or c.get("hook") or "",
        "card_line": c.get("card_line") or "",
        "summary": summary,
        "brand": c.get("brand"), "spark": c.get("spark"),
        "status": status,
        "shot_count": len(c.get("shots") or []),
        "ai_shot_count": len(c.get("ai_shots") or []),
        "warnings": c.get("warnings") or [],
        "grounded": grounded,
        "judge_overall": c.get("judge_overall"),
        "created_at": c.get("created_at"),
        # a one-shot concept IS a scene: its single prompt, the photos
        # it was written against, and whether it was picked to render
        "is_scene": c.get("is_scene", False),
        "picked": c.get("picked", False),
        "archived": c.get("archived", False),
        # parked = the chain took it as far as it can without spending;
        # it is waiting in the Queue on a human. An explicit marker, not
        # "has a reference_image" -- see preprod.set_shot_parked.
        "parked": c.get("parked", False),
        "park_reason": c.get("park_reason") or "",
        "graded": c.get("graded", False),
        "shot_done": c.get("shot_done", False),
        "refs": c.get("refs") or [],
        "prompt": ((c.get("shots") or [{}])[0].get("prompt") or "")
                  if c.get("is_scene") else "",
        # WHICH TOOL THIS SHOT WAS PLANNED FOR. shootgen chose it and
        # nothing downstream ever showed it, so the Queue's renderer
        # picker had no way to default to the plan and defaulted to
        # Runway for everything -- including a scene written for Kling.
        "tool": ((c.get("shots") or [{}])[0].get("tool") or "")
                if c.get("is_scene") else "",
        "media_url": ((c.get("shots") or [{}])[0].get("media_url") or "")
                     if c.get("is_scene") else "",
        "reference_image": ((c.get("shots") or [{}])[0].get("reference_image") or "")
                           if c.get("is_scene") else "",
        # THE SHOTS a timed scene is rendered as (2026-09-10) -- each with
        # its window, its own refs, its still and its clip -- or None for a
        # scene that renders whole. Only a CURRENT timeline: one planned
        # from a prompt that has since been edited describes shots nobody
        # will render, and the approve re-plans it first.
        "timeline": _timeline_card((c.get("shots") or [{}])[0])
                    if c.get("is_scene") else None,
        # WHO PAID FOR THIS CLIP. A hand-rendered clip off the operator's
        # subscription and an API-rendered one billed to somebody's credit
        # are the same mp4 in the same folder; only `params.source` on the
        # generations row tells them apart, and until this field nobody
        # ever saw it. The board renders it as one word beside RENDERED.
        # Absent set = not asked (a single-card read), which is why the
        # default is False rather than unknown.
        "subscription": bool(subscription_ids and c["id"] in subscription_ids),
    }


def _timeline_card(shot: dict) -> Optional[dict]:
    """The card's view of a scene's shots: the timeline when it is current,
    else the bare windows the prompt carries (so the Queue can still show
    how many clips an approve will make, and price them), else None."""
    if timeline.is_current(shot):
        tl = shot["timeline"]
        return {"planned": True, "seconds": tl.get("seconds"),
                "planner": tl.get("planner"), "continuity": tl.get("continuity") or "",
                "parts": [{k: p.get(k) for k in ("n", "start", "end", "seconds", "text",
                                                  "prompt", "refs", "reference_image",
                                                  "media_url")}
                          for p in tl.get("parts") or []]}
    windows = timeline.parse_windows(shot.get("prompt") or "")
    if not windows:
        return None
    return {"planned": False, "seconds": sum(w["seconds"] for w in windows),
            "planner": None, "continuity": "",
            "parts": [{"n": i, "start": w["start"], "end": w["end"],
                       "seconds": w["seconds"], "text": w["text"], "prompt": "",
                       "refs": [], "reference_image": None, "media_url": None}
                      for i, w in enumerate(windows, start=1)]}


@router.get("/pipeline/concepts")
def pipeline_concepts(brand: Optional[str] = None, status: Optional[str] = None,
                      archived: bool = False,
                      account_id: int = Depends(auth.current_account_id),
):
    """The board. Archived concepts are hidden by default -- they are
    decided about, and the board is for what is still open. They are
    still here (`?archived=true`) and still counted in pick_rate, which
    reads the rows rather than this endpoint."""
    # brand goes into the query, not a filter after it -- list_concepts
    # takes the newest 100 of THIS ACCOUNT, and both brands live in one
    # account, so filtering afterwards meant one brand could eat the
    # whole limit and quietly shorten the other's board.
    # one query for the whole board rather than one per card
    subscription_ids = generative.subscription_rendered(account_id=account_id)
    cards = [_concept_card(c, subscription_ids)
             for c in preprod.list_concepts(account_id=account_id, brand=brand)]
    if status in ("idea", "planned", "shot"):
        cards = [c for c in cards if c["status"] == status]
    if not archived:
        cards = [c for c in cards if not c["archived"]]
    return {
        "items": cards,
        "deny_reasons": list(DENY_REASONS),
        "shoot": preprod.shoot_rate(account_id=account_id),
        "pick": preprod.pick_rate(account_id=account_id),
    }


# --- scenes to pick between --------------------------------------------------
# One idea in, N one-shot concepts out. Not a second data model: each is
# exactly the row generate_scene_concept writes, so the scene board,
# Director, render and autopilot keep working unmodified. What is new is
# that you get SEVERAL and the pick is recorded (preprod.pick_rate).

def _photo_bytes(url: str) -> Optional[bytes]:
    """A reference URL -> its bytes, from disk first and the network
    second, or None.

    The disk half is the old behaviour and stays first: a photo on THIS
    machine costs nothing to read and cannot fail. The network half is
    what a canonical R2 URL needs (2026-09-08) -- on the deployed site
    no asset photo is on disk at all, and without this the composer
    would attach a picked face to the shot and hand the generator
    nothing, which is precisely the silent it-looked-attached failure
    the reference layer exists to prevent. Never raises: fetch_image_bytes
    is SSRF-guarded, image/* only, byte-capped, and returns None on
    anything it does not like.
    """
    target = _resolve_asset_photo(url)
    if target is not None:
        try:
            return target.read_bytes()
        except OSError:
            return None
    if str(url or "").startswith(("http://", "https://")):
        from src import imagery
        return imagery.fetch_image_bytes(url)
    return None


async def _collect_refs(form, want_video: bool = False, drop_urls=None):
    """Every reference one composer submission carries, in both the
    forms the pipeline needs: BYTES for the Gemini call happening now,
    and URLS to store on the shot so the keyframe and the clip get them
    too.

    One function because there are three routes that write a concept --
    /scenes/run, /pipeline/run and /generate/run -- and three copies of
    this is exactly how two of them ended up silently discarding the
    URLs (2026-08-28). Returns (image_refs, ref_urls, video_refs).

    `drop_urls` refuses named picked photos before they are read. Only
    /scenes/run passes it, and only for research images the submitted
    idea has walked away from -- see scenes_run. Filtering HERE rather
    than after the fact is what keeps ref_urls and image_refs in step;
    they are built together and image_refs carries no URL to filter on
    later.
    """
    drop_urls = drop_urls or set()
    # local, like every other shootgen use here -- the module pulls in
    # google.genai and this file must stay cheap to import
    from src import shootgen

    image_refs: list = []
    ref_urls: list = []
    video_refs: list = []
    for upload in form.getlist("files"):
        filename = getattr(upload, "filename", "")
        if not filename:
            continue
        mime = _video_mime(filename) if want_video else None
        if mime:
            if len(video_refs) < MAX_VIDEO_REFS:
                video_refs.append((await upload.read(), mime))
            continue
        if len(image_refs) >= MAX_IMAGE_REFS:
            continue
        jpeg = _to_jpeg(await upload.read())
        if not jpeg:
            continue
        saved = _save_upload_ref(jpeg)
        if saved and saved not in ref_urls:
            ref_urls.append(saved)
        image_refs.append((jpeg, "image/jpeg",
                           shootgen.reference_label(saved or "")))
    for picked in form.getlist("asset_photos"):
        picked = str(picked).split("?")[0]
        if not picked or picked in ref_urls or len(ref_urls) >= MAX_IMAGE_REFS:
            continue
        if picked in drop_urls:
            continue
        ref_urls.append(picked)
        if len(image_refs) >= MAX_IMAGE_REFS:
            continue
        raw = _photo_bytes(picked)
        if raw is None:
            continue
        jpeg = _to_jpeg(raw)
        if jpeg:
            image_refs.append((jpeg, "image/jpeg",
                               shootgen.reference_label(picked)))
    return image_refs, ref_urls, video_refs


def _auto_refs(text: str, already: list,
               account_id: Optional[int] = None, *, idea: Optional[str] = None) -> list:
    """The photos of the assets this scene actually names.

    `idea` (2026-09-05): when given, the assets in scope are the ones
    the IDEA names or `already` explicitly picks -- asset_shelf.in_scope,
    the same rule that decided what the writer was offered -- and the
    finished scene's own text is not scanned. Scanning it back had been
    attaching Michael's photos to scenes whose idea never named him,
    because the writer volunteers his name on his own channel. Without
    `idea` the legacy scene-text scan still runs.

    `format_cast` tells the generator that the cast and props on file
    have "(reference photos on file)", and the scene it writes says so in as
    many words -- but nothing was ever attaching those files, so the
    renderer got the sentence and not the face (2026-08-28). This
    closes that loop: read the finished scene back, find the assets it
    named, and let their photos ride on the shot.

    Two passes, because a slot is worth different things to different
    assets. Pass one takes ONE photo of every asset the scene named, so
    nothing named goes unattached and the anchor slot (Runway reads
    whichever is first) still holds the character the scene opens on.
    Pass two spends what is left on more angles of the characters.

    Grounding shapes, it doesn't gate: no match, or no assets at all,
    just means the scene renders on its text like it did before.
    """
    try:
        from src import shootgen
        assets = _assets_all(account_id)
    except Exception:
        return []
    picked = list(already)
    if idea is not None:
        from src import asset_shelf
        named = asset_shelf.in_scope(idea, already, assets)
    else:
        named = shootgen.named_assets(text, assets)
    for asset in named:
        if len(picked) >= MAX_IMAGE_REFS:
            return picked
        photo = _best_photo(asset["photos"])
        if photo and photo not in picked:
            picked.append(photo)
    # Pass two: whatever slots are left go to MORE ANGLES OF THE FACES,
    # round-robin so two characters share the remainder evenly.
    faces = [a for a in named if a.get("category") == "character"]
    for index in range(1, CHARACTER_REF_PHOTOS):
        for asset in faces:
            if len(picked) >= MAX_IMAGE_REFS:
                return picked
            angles = _asset_photos(asset["photos"], CHARACTER_REF_PHOTOS)
            if index < len(angles) and angles[index] not in picked:
                picked.append(angles[index])
    return picked


# How many photos of one character are worth spending reference slots
# on. A face is the case the one-photo rule below was not written for:
# a guest-character keyframe grounded a three-quarter head turn on a
# single frontal portrait and aged him about ten years, while the
# three-quarter frame it needed sat unused in the same folder
# (2026-08-29). A prop gains almost nothing from a second angle; an
# identity gains most of what it has. Three, because past that the
# photos are duplicates of angles already sent.
CHARACTER_REF_PHOTOS = 3


def _best_photo(photos: list) -> Optional[str]:
    """The one photo that stands for an asset -- a face and a bike, not
    twelve angles of the bike -- preferring one the renderer can
    actually decode."""
    picks = _asset_photos(photos, 1)
    return picks[0] if picks else None


def _asset_photos(photos: list, limit: int) -> list:
    """Up to `limit` of an asset's photos, decodable ones first.

    Same preference _best_photo has always had, applied to a run of
    them: a HEIC the renderer cannot open is worth less than the third
    JPEG, so it sorts last rather than eating a slot."""
    urls = [p.split("?")[0] for p in photos if p]
    native = [u for u in urls if Path(u).suffix.lower() in _DECODES_NATIVELY]
    other = [u for u in urls if u not in native]
    return (native + other)[:max(0, limit)]


def _attach_scene_refs(concept_id: int, manual: list,
                       account_id: Optional[int] = None, *,
                       idea: Optional[str] = None) -> list:
    """Store a scene's references on its shot, manual picks first.

    On the shot rather than on the concept because that is what the
    Director graph reads (`ref_urls` on the enhance, keyframe and clip
    nodes), and manual first because an explicit pick outranks anything
    inferred -- and because Runway anchors on whichever one is first.
    """
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None or not concept["shots"]:
        return []
    shots = [dict(sh) for sh in concept["shots"]]
    text = " ".join(str(shots[0].get(k) or "")
                    for k in ("desc", "prompt", "location"))
    refs = _auto_refs(text, manual, account_id, idea=idea)[:MAX_IMAGE_REFS]
    refs = [asset_shelf.canonical_url(r) for r in refs]
    if not refs:
        return []
    shots[0]["refs"] = refs
    preprod.update_concept_shots(
        concept_id, {"shots": shots, "duration": concept.get("duration")},
        warnings=concept.get("warnings") or [], account_id=account_id)
    return refs


# ONE Create writes ONE scene (2026-09-10, Mike's call). The composer used
# to offer 1-4 takes off one idea; the picker is gone and this is the gate
# that makes it true -- an old client or a hand-made request posting
# count=4 still gets one scene, never four billed takes.
SCENE_COUNT_MAX = 1
SCENE_COUNT_DEFAULT = 1


@router.post("/scenes/run")
async def scenes_run(request: Request, account_id: int = Depends(auth.current_account_id)):
    """Several takes on one idea, to pick between -- the Studio Create
    button (2026-08-28).

    Multipart, the same shape /pipeline/run takes, because the composer
    that fires it can attach BOTH freshly uploaded photos and ones
    picked out of the asset bank. `asset_photos` are stored ON each
    concept's shot as well as sent as vision input, which is what
    carries them into every node once it reaches Director; an uploaded
    file grounds this call only, since it has no URL to ride on.

    It runs the grounding and writing stages of src/scene_chain.py and
    STOPS there: Create's job ends on the concepts board (2026-08-29,
    Mike's call). Enhancing, keyframing and rendering are the Director
    canvas's work when a person is driving, and the nightly graph's when
    nobody is -- both go through the same stage functions, so there is
    one implementation of each rather than three.
    """
    form = await request.form()
    idea = (form.get("idea") or form.get("prompt") or "").strip()
    if not idea:
        return _error(400, "empty_idea", "type an idea first")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    brand_raw = form.get("brand")
    brand = brand_raw if brand_raw in preprod.BRANDS else (
        request.cookies.get("brand") if request.cookies.get("brand") in preprod.BRANDS
        else "antihero")
    try:
        count = int(form.get("count") or SCENE_COUNT_DEFAULT)
    except (TypeError, ValueError):
        count = SCENE_COUNT_DEFAULT
    count = max(1, min(SCENE_COUNT_MAX, count))

    # Which brain writes (2026-09-09). Clamped HERE against the real
    # table, for the reason the count above is: the select is not the
    # gate, and an unknown tier should write a cheap scene rather than
    # fail a run. resolve_brain does the same clamp a second time at the
    # bottom -- deliberately, since the graph reaches it without passing
    # through this route at all.
    from src import gemini_utils
    brain_raw = (form.get("brain") or "").strip().lower()
    brain = brain_raw if brain_raw in gemini_utils.BRAINS else gemini_utils.DEFAULT_BRAIN

    # The frame the scene is written for, stored on its shot so the Queue
    # card defaults to it instead of asking again. REFUSED rather than
    # clamped when it is not a size the renderers take -- the same rule
    # providers.check_render_choice follows, and for the same reason: a
    # silently corrected frame is a clip that comes back the wrong shape.
    ratio = (form.get("ratio") or "").strip()
    if ratio and ratio not in render_specs.RUNWAY_RATIOS:
        return _error(400, "bad_ratio",
                      f"{ratio} is not a frame the renderers take")
    # The scene's total length (2026-09-10). Clamped by scene_seconds,
    # never refused -- the select is not the gate, same as the count.
    seconds = timeline.scene_seconds(form.get("seconds"))

    # A researched spark and an idea Mike typed himself are two separate
    # paths, and this route is the only place they touch. The composer
    # sends the id of whatever research was on screen; the SERVER decides
    # whether this submission is still that research, because a
    # client-side flag is exactly what goes stale when someone loads a
    # spark and then types their own idea over it.
    #
    # One comparison, two consequences. If the idea is no longer the
    # scout's spark then (a) the finding is not claimed -- burning a
    # spark that wrote nothing would silently throw away research -- and
    # (b) that pass's images do not ride along either. The second half
    # matters more than it looks: those photos become the shot's `refs`,
    # and refs[0] is the frame Runway anchors the whole clip on. His own
    # idea anchored on a stranger's thumbnail is not his own idea.
    try:
        scout_finding_id = int(form.get("scout_finding_id") or 0)
    except (TypeError, ValueError):
        scout_finding_id = 0
    scout_claimed = bool(scout_finding_id) and scout.claims(
        scout_finding_id, idea)
    drop_urls = set()
    if scout_finding_id and not scout_claimed:
        drop_urls = {b["url"] for b in
                     scout.bin_for_finding(scout_finding_id)}

    # Videos too (2026-09-10): they ground the WRITING only -- Gemini
    # watches them -- and never land on the shot, since no renderer takes
    # a video as a reference. MAX_VIDEO_REFS caps them, same as Generate.
    image_refs, refs, video_refs = await _collect_refs(
        form, want_video=True, drop_urls=drop_urls)
    # The other half of the claim (2026-09-03): when this IS the spark,
    # the photos attached here go into ITS bin too, so a later run on
    # the same direction -- from the nightly graph or from a phone's
    # `generate` -- sees what was uploaded against it. Before this, four
    # uploads against spark #38 rode straight onto the shot and left the
    # bin reading 0. Banked before the job rather than after it, since a
    # generation that writes nothing leaves the spark to be served again
    # and the photographs should still be waiting behind it.
    if scout_claimed:
        scout.bank_urls(scout_finding_id, refs, lane="composer")

    def work(job):
        from google import genai

        from src import scene_chain

        client = genai.Client(api_key=api_key)
        video_parts = [p for p in (video_part(client, data, mime)
                                   for data, mime in video_refs) if p is not None]
        if video_refs:
            jobs.progress(job, 0.05,
                          f"{len(video_parts)}/{len(video_refs)} reference video(s) ready")

        # ground -> write -> attach, and STOP: pressing Create writes
        # concepts and lands on the board. The enhance, the keyframe and
        # the clip are the Director canvas's job when a person is doing
        # this by hand -- and the nightly graph's job when nobody is
        # (src/orchestrator.py calls the same stage functions).
        result = scene_chain.run(
            idea, brand, count=count, refs=refs, image_refs=image_refs or None,
            db_path=None, account_id=account_id,
            gemini_client=client, video_parts=video_parts,
            resolve_photo=_resolve_asset_photo,
            attach_refs=_attach_scene_refs,
            brain=brain, ratio=ratio or None, seconds=seconds,
            progress=lambda fraction, detail: jobs.progress(job, fraction, detail))
        saved = result["scenes"]
        if scout_claimed and saved:
            scout.mark_used(scout_finding_id,
                            run_id=f"concept:{saved[0]['concept_id']}")
        detail = f"{len(saved)} concept(s)"
        if brain != gemini_utils.DEFAULT_BRAIN:
            detail += f" · {brain}"
        for note in result["notes"]:
            detail += f" · {note}"
        return {"detail": detail,
                "ref_id": saved[0]["concept_id"] if saved else None}

    job = jobs.start("scenes", f"concepts · {idea[:60]}", work, account_id=account_id)
    return {"job_id": job["id"], "image_refs": len(image_refs),
            "video_refs": len(video_refs), "brain": brain, "seconds": seconds}


# --- the research scout -----------------------------------------------------
# src/scout.py crawls, scores and banks; these two routes are how the
# Create composer reaches the bank. The spark it hands back is a plain
# line of text and the bin images are ordinary /refs/<sha>.jpg URLs --
# the same shape a dragged-on photo gets -- so pressing Create after
# loading one goes through exactly the path a hand-typed idea does.


@router.get("/scout/spark")
def scout_spark(brand: Optional[str] = None, account_id: int = Depends(auth.current_account_id)):
    """The next researched spark for this brand, with the images from
    the pass it was read out of.

    Does NOT claim it. A person can load a spark, read it, and decide
    against it without burning it -- the claim happens when a run
    actually generates from it (see /scenes/run's `scout_finding_id`,
    and orchestrator.planner on the nightly path).

    An empty bank is a 200 with `spark: null`, not a 404: "nothing
    researched yet" is a normal state of this surface, and the composer
    renders it as an invitation to research rather than as an error.
    """
    brand = brand if brand in preprod.BRANDS else "antihero"
    finding = scout.next_spark(brand)
    if not finding:
        return {"spark": None, "brand": brand, "bin": [],
                "banked": len(scout.list_findings(brand=brand, unused_only=True))}
    try:
        sources = json.loads(finding.get("sources") or "[]")
    except (TypeError, ValueError):
        sources = []
    return {
        "brand": brand,
        "spark": finding["spark"],
        "finding_id": finding["id"],
        "rationale": finding.get("rationale") or "",
        "evidence": finding.get("evidence") or "",
        "score": finding.get("score"),
        "sources": sources,
        "bin": [{"url": b["url"], "source_url": b.get("source_url") or "",
                 "title": b.get("title") or "", "lane": b.get("lane") or "",
                 "metric": b.get("metric") or ""}
                for b in scout.bin_for_finding(finding["id"])],
    }


class ScoutRunBody(BaseModel):
    brand: Optional[str] = None
    count: int = 4


@router.post("/scout/run")
def scout_run(body: ScoutRunBody, account_id: int = Depends(auth.current_account_id)):
    """Fire one research pass as a job, so the crawl narrates on the
    same SSE feed as everything else -- it takes tens of seconds and a
    silent button is indistinguishable from a broken one."""
    if not _gemini_key():
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    brand = body.brand if body.brand in preprod.BRANDS else "antihero"
    count = max(1, min(6, int(body.count or 4)))

    def work(job):
        jobs.progress(job, 0.15, "crawling")
        result = scout.scout(brand, count)
        jobs.progress(job, 0.9, "banking")
        if not result["ok"]:
            raise RuntimeError(result["errors"][0] if result["errors"]
                               else "the crawl found nothing usable")
        detail = f"{len(result['findings'])} spark(s) · {len(result['bin'])} image(s)"
        return {"detail": detail}

    job = jobs.start("scout", f"research · {brand}", work, account_id=account_id)
    return {"job_id": job["id"], "brand": brand}


def _keyframe_on_pick(concept: dict, account_id: int):
    """Render the picked scene's still(s), in the background. Returns a
    job id, or None when there is nothing to do.

    WHY HERE AND NOT IN THE NIGHT (2026-09-08, Mike's call). The nightly
    graph's keyframe step is off (`ZEROPAGE_KEYFRAME=0`, a deliberate
    cost cut on 09-07): a 40-spark walk that draws every scene spends the
    whole Nano cap on concepts nobody has looked at, and 75 of 75 stills
    from one night is not a review queue, it is wallpaper. The pick is
    the first moment a human has said this scene is worth something, so
    it is the cheapest possible place to spend cents on an image -- and
    the image arrives before the Queue, which is where the dollars are.

    Never fatal, and never in the request. The pick itself has already
    been recorded by the time this runs; a keyframe that fails (no key,
    NANO_DAILY_CAP, a 503 from the image model) leaves a failed job in
    the rail and a scene that is picked, prompted and simply not drawn
    yet -- exactly what every scene looked like before this existed.
    Set ZEROPAGE_KEYFRAME_ON_PICK=0 to turn it off without touching the
    route.

    Deliberately skipped for a scene that already HAS a still: unpicking
    and re-picking a card must not quietly re-bill it, and the Director
    canvas's own keyframe is the one a person chose.
    """
    from src import scene_chain

    api_key = _gemini_key()
    if not api_key:
        return None
    # The guard is scene_chain's, asked here so a skip costs no job at
    # all, and asked again inside draw_on_pick so the MCP door cannot
    # drift away from this one.
    if scene_chain.pick_skip_reason(concept):
        return None
    concept_id = concept.get("id")
    title = (concept.get("title") or f"concept {concept_id}")[:60]

    def work(job):
        from google import genai

        from src import scene_chain

        jobs.progress(job, 0.2, "rendering keyframe")
        result = scene_chain.draw_on_pick(
            concept_id, db_path=None, account_id=account_id,
            resolve_photo=_resolve_asset_photo,
            gemini_client=genai.Client(api_key=api_key))
        if result.get("skipped"):
            return {"detail": result["skipped"]}
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "keyframe failed")
        frames = result.get("frames") or []
        detail = f"{1 + len(frames)} still(s)" if frames else "1 still"
        return {"detail": detail, "ref_id": concept_id}

    job = jobs.start("keyframe", f"keyframe · {title}", work,
                     account_id=account_id)
    return job["id"]


class PickBody(BaseModel):
    picked: bool = True


@router.post("/concepts/{concept_id}/pick")
def concept_pick(concept_id: int, body: PickBody, account_id: int = Depends(auth.current_account_id)):
    """The label: this scene is worth rendering -- and, as of 2026-09-02,
    a verdict.

    The ✓ records an APPROVE on the scene prompt, the mirror of what the ✗
    does, so the concept lands on the Teach tab and its prompt reaches the
    RAG *winning* shelf on the next pass. Without this the board taught
    only negatives, and on a pick rate near 1 in 29 that is a writer being
    told what to avoid twenty times for every example of what to aim at.

    The pick still does everything it did: picked_at is the label
    pick_rate reads, and the Queue is still what decides on spending.
    Teaching is added beside that, not instead of it."""
    try:
        preprod.set_picked(concept_id, body.picked, account_id=account_id)
    except ValueError as e:
        return _error(404, "not_found", str(e))
    concept = preprod.get_concept(concept_id, account_id=account_id)
    ruled = False
    job_id = None
    if concept is not None:
        if body.picked:
            ruled = _board_verdict(concept, "worked", BOARD_PICK_NOTE)
            # The still is rendered for the ones you pick, and only those.
            job_id = _keyframe_on_pick(concept, account_id)
        else:
            _withdraw_board_verdict(concept)
    return {"ok": True, "picked": body.picked, "ruled": ruled,
            "job_id": job_id,
            "pick": preprod.pick_rate(account_id=account_id)}


class ArchiveBody(BaseModel):
    archived: bool = True


BOARD_PASS_NOTE = "passed on the board"
BOARD_PICK_NOTE = "picked on the board"
BOARD_NOTES = (BOARD_PASS_NOTE, BOARD_PICK_NOTE)


def _board_verdict(concept: dict, verdict: str, note: str) -> bool:
    """Record the board's ruling on a concept's scene prompt. True if one
    was filed.

    Both board buttons are verdicts as of 2026-09-02: ✓ files the prompt
    to be imitated, ✗ files it to be avoided. Neither ingests -- they land
    on the Teach tab and the pass there embeds them, so a tap is
    reversible right up until you teach it.

    Two rules about replacing what is already there, and the asymmetry
    between them is the whole point:

      - a previous BOARD verdict is replaced. Picking something you
        X'd has to flip the lesson, not stack a second one against it.
      - a verdict from the Grade tab is NOT touched. That one was
        considered -- you read the prompt, maybe rewrote it -- and a
        one-tap board click must not quietly overwrite it.

    Anything already ingested is never replaced either way: that lesson is
    taught, and no button here is an unteach.
    """
    shots = [sh for sh in (concept.get("shots") or []) if sh.get("prompt")]
    if not shots:
        return False        # nothing to teach; the tap is just a tap
    ref = f"concept-{concept['id']}-shot-{shots[0].get('n') or 1}"
    existing = winners.recorded(ref)
    if any(w.get("ingested") for w in existing):
        return False
    if any((w.get("note") or "") not in BOARD_NOTES for w in existing):
        return False        # a considered verdict from the Grade tab wins
    winners.discard_pending(ref)
    winners.record_and_learn(
        (shots[0].get("tool") or "runway"), shots[0]["prompt"], note=note,
        video_ref=ref, verdict=verdict, ingest=False)
    return True


def _withdraw_board_verdict(concept: dict) -> int:
    """Undo a board ruling that has not taught anything yet. Un-picking or
    un-archiving must take its verdict with it, or the shelves learn from
    a decision that was reversed."""
    withdrawn = 0
    for sh in (concept.get("shots") or []):
        if not sh.get("prompt"):
            continue
        ref = f"concept-{concept['id']}-shot-{sh.get('n') or 1}"
        if all((w.get("note") or "") in BOARD_NOTES
               for w in winners.recorded(ref)):
            withdrawn += winners.discard_pending(ref)
    return withdrawn


@router.post("/concepts/{concept_id}/archive")
def concept_archive(concept_id: int, body: ArchiveBody,
                    account_id: int = Depends(auth.current_account_id)):
    """Take a concept off the board -- and, as of 2026-09-02, RULE on it.

    The X is a verdict now, not just a tidy-up. It archives the row (never
    a delete: it still counts for pick_rate) and records a DENY against
    the scene prompt, so the concept lands on the Teach tab and its prompt
    reaches the RAG avoid shelf on the next pass. One tap, no reason box --
    Mike's standing rule for this button.

    Deliberately entering territory he named himself: he passes on most of
    what is generated, so this puts many more negatives than positives on
    the shelves. Chosen with that known. If generations start reading
    timid, this is the first thing to look at.

    See _board_verdict for the guards -- no prompt, an already-ingested
    lesson, and a considered verdict from the Grade tab are all left
    alone -- and for why un-archiving takes the deny with it.

    account_id comes from the dependency, NOT from a bare default
    (2026-09-02). Written as `account_id: Optional[int] = None` it was a
    *query parameter* to FastAPI, so every call arrived with None and
    set_archived's `WHERE ... AND account_id IS ?` matched nothing --
    the X on the board 404'd on every card that had an owner while Pick,
    which took the dependency, worked. Same scoping as pick or the two
    buttons disagree about whose rows they are."""
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", f"no concept {concept_id}")
    try:
        preprod.set_archived(concept_id, body.archived, account_id=account_id)
    except ValueError as e:
        return _error(404, "not_found", str(e))

    if body.archived:
        ruled = _board_verdict(concept, "didnt_work", BOARD_PASS_NOTE)
    else:
        _withdraw_board_verdict(concept)
        ruled = False
    return {"ok": True, "archived": body.archived, "ruled": ruled}


# --- the approval gate ------------------------------------------------------
# A picked concept is not rendered yet -- rendering costs money, so the
# pick and the spend are two different decisions. Everything picked and
# not yet rendered waits in the Queue, and approving one there is what
# actually calls Runway.


def _runway_state() -> dict:
    """What approving one of these would cost and whether it can even
    happen. The daily count reads the generations log, which a database
    that has never rendered anything does not have yet -- a queue that
    500s because nothing has been billed on it is the wrong failure, so
    the count degrades to None and the gate is still reported."""
    try:
        today = runway.generations_today(db_path=None)
    except Exception:
        today = None
    return {"available": runway.has_key(),
            # TRUE since 2026-09-09: there is no separate spend approval
            # for a person any more, so an older client reading this
            # shape must not dim a button it is allowed to press. The
            # env override still exists for unattended runs and is
            # reported as `env_override` on the per-renderer payload.
            "spend_ok": runway.has_key(),
            "model": runway.DEFAULT_MODEL,
            "estimate_usd": runway.estimate_cost(1),
            # the Gen Space's model chips say what a clip IS before the
            # spend, not just what it costs
            "ratio": runway.DEFAULT_RATIO,
            "duration": runway.DEFAULT_DURATION,
            # the Queue's selectors (2026-09-12): every model with what a
            # second of it costs, and the frames and lengths the endpoint
            # takes -- so the approve button can price the actual choice
            # priced through runway.credits_per_second, never the flat
            # table: seedance bills by the frame's resolution tier, so its
            # per-second figure is quoted at the default frame
            "models": [{"id": m,
                        "label": (m.replace("gen4_turbo", "Gen-4 Turbo").replace("gen4.5", "Gen-4.5")
                                  .replace("seedance2_5", "Seedance 2.5")),
                        "usd_per_second": round(
                            runway.credits_per_second(m, runway.DEFAULT_RATIO) * runway.CREDIT_USD, 3)}
                       for m in runway.MODELS],
            # projected off src/render_specs.py, the one table the lane
            # import and providers.check_render_choice refuse against
            "ratios": list(render_specs.RUNWAY_RATIOS),
            "durations": list(render_specs.RUNWAY_DURATIONS),
            "today": today}


def _renderers_state(account_id: Optional[int] = None) -> dict:
    """Every renderer the Queue may spend on, with its gates and its legal
    options -- the four-vendor form of _runway_state.

    Until 2026-09-08 this surface reported exactly one vendor, because
    approving could only call one: `queue_approve` named runway in the
    route body and the card's disabled state was read off `data.runway`.
    A concept shootgen planned for KLING rendered on Kling at 3:30am
    through orchestrator.generate_render's connectors dict and on Runway
    if a human approved the same row by hand -- two doors disagreeing
    about what a shot's `tool` means.

    `runway` is still returned alongside, unchanged. It is a public shape
    an older client may still be reading, and there is nothing to gain
    from breaking it on the same day the new one arrives."""
    return providers.render_options(account_id)


def _waiting(account_id: Optional[int], brand: Optional[str]) -> list[tuple[dict, dict]]:
    """The queue predicate -- parked by the chain or picked on the board,
    not archived, a scene, no clip yet -- as (concept, card) pairs.

    ONE definition of "waiting" for every surface that reads it: the
    Queue page and the manual-lane list must not be able to disagree
    about which shots are outstanding, or a human renders something the
    Queue never asked for. (ops/render_queue.py keeps its own copy on
    purpose and says so; it has to run without importing app/.)

    AND IT MUST CARRY REFERENCE PHOTOS (2026-09-08, Mike's call). The
    writers already archive an ungrounded concept, so in the normal case
    nothing reaches here to refuse -- this is the check that makes that
    true rather than merely likely. Three ways a row gets here without
    photos anyway: it was written before the gate existed, somebody
    un-archived it, or a later edit cleared the shot's refs. In every one
    of them the next click spends real money on a scene rendering from
    its own text.

    Deliberately NOT a prompt check as well. A prompt is on `shots_json`
    only because score_prompts put it there, and a second bar here would
    be a different opinion from the one that already ran."""
    # scoped in SQL, see above
    out = []
    for concept in preprod.list_concepts(account_id=account_id, brand=brand):
        card = _concept_card(concept)
        if ((card["picked"] or card["parked"]) and not card["archived"]
                and card["is_scene"] and not card["media_url"]
                # nothing reaches a spend ungrounded -- see above
                and not preprod.reference_gate(concept)
                # marked shot by hand (the camera button) -- a card you
                # already made yourself isn't waiting on you to spend
                and not card["shot_done"]):
            out.append((concept, card))
    return out


@router.get("/queue/pending")
def queue_pending(brand: Optional[str] = None, account_id: int = Depends(auth.current_account_id)):
    """What is waiting on you to spend: parked by the chain or picked on
    the board, not archived, no clip yet. Derived from the rows, so it
    survives a restart -- the jobs registry does not, and an approval
    that vanished on restart would be a queue that lies.

    Two ways in, because there are two ways a scene gets here: the
    Studio chain parks it (concept written, prompt enhanced, keyframe
    rendered -- the next step is the one that costs money), or you pick
    a text-only concept off the board yourself."""
    items = []
    for _, card in _waiting(account_id, brand):
        # THE CARD'S OWN DEFAULT RENDERER, resolved here rather than in
        # the browser. The mapping from a shot's planned tool to a
        # (provider, model) pair lives in providers.platform_default and
        # is the same one the approve route resolves with, so what the
        # card offers first and what an empty approve body would spend on
        # cannot come apart -- which they would the moment the browser
        # held its own copy of fal.PLATFORM_MODELS.
        #
        # AND ONE THIS ACCOUNT CAN RENDER (2026-09-11). The plan leads when
        # the account holds its key; when it does not, the card opens on
        # the cheapest renderer the account can use instead of on a dead
        # button -- providers.render_default, the same call an empty
        # approve body makes below.
        items.append({**card, "render_default": providers.render_default(
            card.get("tool"), account_id)})
    return {"items": items,
            "runway": _runway_state(),
            "renderers": _renderers_state(account_id)}


def _lane_models() -> list:
    """The lane's legal models, each with what it may claim, for the
    drop card's controls. `render_specs` is the one table; this is a
    projection of it, never a second copy."""
    return [{"id": name,
             "durations": list(spec.get("durations") or ()),
             "ratios": list(spec.get("ratios") or ())}
            for name, spec in sorted((render_specs.RUNWAY_MODELS or {}).items())]


def _lane_default_model() -> str:
    """What the card offers first: the adapter's own default when the
    lane can actually render it, else the first legal model. RUNWAY_MODEL
    is an env var, so it can name something render_specs does not know --
    and offering that as the default would mean every drop refused."""
    known = render_specs.RUNWAY_MODELS or {}
    if runway.DEFAULT_MODEL in known:
        return runway.DEFAULT_MODEL
    return sorted(known)[0] if known else runway.DEFAULT_MODEL


@router.get("/queue/manual")
def queue_manual(brand: Optional[str] = None,
                 account_id: int = Depends(auth.current_account_id)):
    """The same waiting shots, addressed to a pair of hands in Chrome.

    THE OPERATOR'S LANE, AND ONLY THE OPERATOR'S. Runway's free Explore
    Mode is a web-app toggle with no API parameter, so the only way to
    spend the Unlimited plan is a human driving the app -- and that plan
    is the operator's personal consumer subscription, so rendering a
    paying tenant's shot on it would be reselling it. That is an
    account-termination risk which, on a shared install, takes every
    tenant's renders down at once.

    So the gate is `manual_lane.manual_lane_allowed(account_id)`, called
    on the TENANT resolved server-side by `auth.current_account_id` --
    never a query parameter, a header or a body field, because all three
    are things a caller writes. Since 2026-09-08 that reads ONE column on
    the account's own row (`accounts.manual_lane_operator`, set by hand
    with `python -m src.accounts operator <slug> --on`) rather than an
    env var this process could have been started with, and membership of
    an operator's account grants nothing. A database nobody has been
    turned on in allows nobody.

    The refusal is a 404 carrying `manual_lane.REFUSAL` and nothing
    else, the same for every caller: it must read like a route that does
    not exist, and must never let someone learn from the difference
    between two refusals whether the lane exists for somebody else.

    Read-only, and its POST twin is `queue_manual_import` (2026-09-08),
    which takes the finished mp4 dropped onto a card. That used to be the
    CLI's alone -- "the file is on the human's machine, so the terminal
    is where it gets filed" -- which was true and was still a terminal
    standing between the owner and a lane he drives from a browser. A
    multipart upload carries the file perfectly well; what mattered was
    that the new door be the same door, so it re-asks this same gate and
    calls the same `import_clip` rather than growing a second way to
    write a lane row.
    """
    if not manual_lane.manual_lane_allowed(account_id):
        return _error(404, "not_found", manual_lane.REFUSAL)
    items = []
    for concept, card in _waiting(account_id, brand):
        shot = (concept.get("shots") or [{}])[0]
        try:
            duration = int(shot.get("duration"))
        except (TypeError, ValueError):
            duration = manual_lane.LANE_DURATION
        items.append({
            "concept_id": card["id"],
            "title": card["title"],
            "brand": card["brand"],
            "shot_n": shot.get("n", 1),
            "prompt": card["prompt"],
            # the frame that gets dragged into the start-image slot
            "keyframe_url": card["reference_image"],
            "duration": duration,
            "ratio": shot.get("ratio") or manual_lane.LANE_RATIO,
            "lane": manual_lane.LANES["runway"],
        })
    return {"items": items, "lane": manual_lane.LANES["runway"],
            # The models this lane may claim, and the lengths and frames
            # each of them legally renders, straight off src/render_specs.py
            # -- the same table `import_clip` refuses against. Served
            # rather than written into the JS so the drop card's controls
            # cannot offer a value the import would then refuse, and so a
            # model leaving the table leaves the UI in the same commit.
            "models": _lane_models(),
            "default_model": _lane_default_model(),
            "import_with": "ops/render_queue.py --provider runway import"}


# --- renderer keys (BYOK) ----------------------------------------------------
#
# 2026-09-12, Mike: "is there a long term solution for this so other users can
# start using this product". src/account_keys.py has held per-account encrypted
# credentials since 2026-09-03, and until today the only way to enter one was
# `python -m src.account_keys set` on the server -- so a pilot user could not
# bring their own key at all, and every render they approved billed the
# operator's. This is that table's front door and nothing more: it stores and
# clears, it never reads a key back out.
#
# THREE RULES, each load-bearing:
#   * a stored key is NEVER returned, not even masked. The row says whose
#     credential would be used (account / env / nothing) and when it was
#     stored, which is everything a person needs to decide what to do next,
#     and none of what an attacker who got a session would want.
#   * mutations require the x-zpf-renderer-key header, model_connections'
#     rule: the session cookie is SameSite=None on the hosted deployment
#     (FRONTEND_ORIGINS), so a form on another origin could otherwise POST a
#     key onto somebody's account. A custom header forces a CORS preflight.
#   * the vendors offered are exactly providers.VIDEO_PROVIDERS, plus nothing.
#     Gemini and Midjourney are deliberately absent: the cheap Gemini steps
#     are the operator's to pay for (backlog #10's "split by cost"), and
#     Midjourney has no API to hold a key for.

RENDERER_KEY_HEADER = "x-zpf-renderer-key"

# What to call each field on the form. account_keys.PROVIDER_FIELDS is the
# contract; this is only its spelling for a human.
_KEY_FIELD_LABELS = {
    "api_secret": "API secret",
    "api_key": "API key",
    "api_key_id": "Key id",
    "api_key_secret": "Key secret",
}


def _renderer_key_row(provider: str, account_id: Optional[int],
                      stored: Optional[dict] = None) -> dict:
    """One vendor's state: whose key would pay, when this account stored
    one, and what the environment fallback is called. Never the key.

    `stored` is the whole listing when the caller already has it -- four
    rows on one page load is one query, not four."""
    if stored is None:
        stored = {row["provider"]: row["updated_at"]
                  for row in account_keys.list_providers(account_id)} if account_id else {}
    try:
        source = account_keys.key_source(account_id, provider)
    except ValueError:
        source = None
    return {
        "provider": provider,
        "label": providers.RENDER_LABELS.get(provider, provider),
        "fields": [{"name": name,
                    "label": _KEY_FIELD_LABELS.get(name, name.replace("_", " "))}
                   for name in account_keys.PROVIDER_FIELDS.get(provider, ())],
        # "account" = this account's own stored key, "env" = the operator's
        # environment key, None = nothing resolves and approving refuses
        "source": source,
        "stored_at": stored.get(provider),
        "env_names": [list(names) for names in
                      account_keys.PROVIDER_ENV_FALLBACK.get(provider, ())],
    }


def _renderer_keys(account_id: Optional[int]) -> dict:
    stored = {row["provider"]: row["updated_at"]
              for row in account_keys.list_providers(account_id)} if account_id else {}
    return {"items": [_renderer_key_row(name, account_id, stored)
                      for name in providers.VIDEO_PROVIDERS]}


class RendererKeyBody(BaseModel):
    """The key's parts, in PROVIDER_FIELDS order. A list and not named
    fields because higgsfield takes two and the others one, and the order
    is already the contract every adapter resolves through."""
    values: list[str]


@router.get("/renderer-keys")
def renderer_keys(account_id: int = Depends(auth.current_account_id)):
    """Which renderers this account can spend on, and on whose credential."""
    return _renderer_keys(account_id)


@router.put("/renderer-keys/{provider}")
def renderer_key_set(provider: str, body: RendererKeyBody, request: Request,
                     account_id: int = Depends(auth.current_account_id)):
    """Store this account's own key for one renderer. Encrypted at rest
    (Fernet, ACCOUNT_KEYS_SECRET); overwrites whatever was there."""
    if request.headers.get(RENDERER_KEY_HEADER) != "1":
        return _error(403, "forbidden", "use the studio's renderer key controls")
    if provider not in providers.VIDEO_PROVIDERS:
        return _error(404, "not_found", f"no renderer {provider!r}")
    fields = account_keys.PROVIDER_FIELDS.get(provider, ())
    values = [(v or "").strip() for v in body.values]
    if len(values) != len(fields) or not all(values):
        return _error(400, "bad_key",
                      f"{providers.RENDER_LABELS.get(provider, provider)} takes "
                      f"{len(fields)} value(s): "
                      f"{', '.join(_KEY_FIELD_LABELS.get(f, f) for f in fields)}")
    try:
        account_keys.set_key(account_id, provider, *values)
    except RuntimeError as e:
        # ACCOUNT_KEYS_SECRET unset: there is nothing to encrypt with, and
        # storing the key in the clear instead is exactly what that secret
        # exists to prevent. Say so rather than failing as a 500.
        return _error(503, "encryption_unavailable", str(e))
    return _renderer_key_row(provider, account_id)


@router.delete("/renderer-keys/{provider}")
def renderer_key_clear(provider: str, request: Request,
                       account_id: int = Depends(auth.current_account_id)):
    """Forget this account's key. The environment fallback (the operator's
    own key, where there is one) takes over again -- which the returned
    row says, so nobody has to guess whether removing it turned rendering
    off."""
    if request.headers.get(RENDERER_KEY_HEADER) != "1":
        return _error(403, "forbidden", "use the studio's renderer key controls")
    if provider not in providers.VIDEO_PROVIDERS:
        return _error(404, "not_found", f"no renderer {provider!r}")
    account_keys.clear_key(account_id, provider)
    return _renderer_key_row(provider, account_id)


# --- the manual lane's drop target ------------------------------------------
# The other half of /queue/manual: the card shows what to paste and what
# to drag in, and this takes back the mp4 that comes out the far end. It
# exists so the owner never has to leave /ui for this lane -- until
# 2026-09-08 filing a clip meant a terminal and a full `ops/render_queue.py
# import` command line, which is a lot of ceremony for a file that is
# already sitting in ~/Downloads.

# What a Runway Explore clip actually weighs: a 10s 9:16 gen4 render is
# tens of megabytes. The cap is generous against that and still bounded,
# because an unbounded multipart body is a way to fill the disk this
# app's own renders live on. Enforced while STREAMING (see below), not
# after the read, or the cap would be enforced by first accepting the
# thing it exists to refuse.
MANUAL_CLIP_MAX_BYTES = 256 * 1024 * 1024

# Enough bytes to see the ISO base-media file-type box. Byte 4..8 of an
# mp4 is the literal `ftyp`; the four after it are the major brand.
_MAGIC_BYTES = 12

# QuickTime uses the SAME ftyp box with this brand, and a .mov is not an
# mp4 however much the filename insists. Named rather than allow-listing
# mp4 brands, because that list is long, vendor-specific and still
# growing (isom, iso2, mp41, mp42, avc1, dash, mmp4...) -- an allowlist
# that refuses a real Runway render is worse than a denylist that lets a
# rare sibling format through to ffprobe.
_NOT_MP4_BRANDS = (b"qt  ",)


def _looks_like_mp4(head: bytes) -> bool:
    """Whether these first bytes are an mp4, asked of the FILE and never
    of its name.

    The extension is the uploader's opinion; `.mp4` on a zip is one
    rename away and the browser's own content-type is no better -- both
    are client-supplied strings. The ftyp box is the file itself saying
    what it is. This is a cheap sanity check, not a parser: what it
    stops is a wrong file being copied into data/renders/ and attached to
    a shot as a render that happened.
    """
    if len(head) < _MAGIC_BYTES or head[4:8] != b"ftyp":
        return False
    return head[8:12] not in _NOT_MP4_BRANDS


async def _spool_clip(upload, dest: Path) -> Optional[JSONResponse]:
    """The upload onto disk, in chunks, refusing before it is all here.

    Returns an error response, or None when `dest` now holds the clip.
    Chunked because the two things worth refusing -- the wrong format and
    an oversized body -- are both knowable early: the magic number from
    the first chunk, the cap the moment it is crossed. Reading the whole
    body first and checking afterwards would mean holding a quarter of a
    gigabyte of somebody's mistake in memory to decide it was a mistake.
    """
    size = 0
    head = b""
    with dest.open("wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            if not head:
                head = chunk[:_MAGIC_BYTES]
                if not _looks_like_mp4(head):
                    return _error(
                        400, "not_an_mp4",
                        "that is not an mp4 -- the file's own header says so, "
                        "whatever it is called. Drop the clip Runway gave you.")
            size += len(chunk)
            if size > MANUAL_CLIP_MAX_BYTES:
                return _error(
                    413, "clip_too_large",
                    f"clip is over {MANUAL_CLIP_MAX_BYTES // (1024 * 1024)}MB -- "
                    f"that is not a 10-second render")
            out.write(chunk)
    if not size:
        return _error(400, "empty_upload", "no file arrived")
    return None


@router.post("/queue/manual/{concept_id}/clip")
async def queue_manual_import(concept_id: int, request: Request,
                              account_id: int = Depends(auth.current_account_id)):
    """Drag the finished mp4 onto its card and it is filed. The lane's
    one writing surface on /ui.

    THE SAME GATE, NOT A SECOND ONE. `manual_lane.require` on the account
    `auth.current_account_id` resolved server-side, refusing with the
    byte-identical `manual_lane.REFUSAL` in a 404 exactly as
    `queue_manual` does -- a new door onto an operator-only lane must not
    be a weaker one, and two refusals that differ are a way to learn
    whether the lane exists here at all. The `manual_lane` capability
    flag is presentation and is deliberately not consulted here: it is a
    field in a response the caller can edit.

    THE VERIFICATION IS NOT REIMPLEMENTED HERE. `ops/render_queue.py`'s
    `import_clip` is the SINGLE IMPLEMENTATION of filing a lane clip --
    the model/ratio/duration claims checked against `src/render_specs.py`
    and REFUSED rather than clamped, the ffprobe measurement written
    beside the claim as `duration_measured_s`/`duration_source`, `_place`
    putting the file where the /renders mount can serve it, and the
    `generations` row with `cost_usd` NULL and the `manual-unlimited`
    marker that makes `ledger.is_billable` refuse a hold. This route
    calls it. It does not repeat it, and it must never grow a copy: a
    second implementation of "is this claim legal" is how the CLI and the
    UI come to disagree about what was rendered, which is the exact
    failure the checks were added to catch. Its refusals are SystemExit
    (the script's idiom) and arrive here as a 400 carrying the message
    render_specs wrote.

    WHAT THIS ROUTE OWNS, because it is about the upload and not about
    the lane: the file is an mp4 by MAGIC NUMBER rather than by name, it
    is under MANUAL_CLIP_MAX_BYTES, and it is written under a name this
    server chose (`concept<id>-shot<n>.mp4`) rather than the uploader's
    -- `_place` names the served file after the one it is handed, and a
    filename is caller-supplied text.

    A SECOND DROP ON THE SAME SHOT IS REFUSED, not silently applied.
    Dropping is a gesture, and gestures repeat: a browser can fire twice,
    a hand can drop again when the card did not visibly change, and the
    two are indistinguishable from a deliberate replacement. Applying it
    would leave the shot pointing at the newer file with an older
    `generations` row still claiming to be this shot's render -- two
    attempts recorded for one, which is exactly what the tool scoreboard
    counts -- and the first mp4 orphaned in data/renders/ where nothing
    names it. Refusing costs one clear sentence and is undoable (clear
    the shot's media_url and drop again); replacing is not. The CLI keeps
    its overwrite behaviour on purpose: a full command line naming
    --concept and --shot is a stated intention, and a drop is not.
    """
    if not manual_lane.manual_lane_allowed(account_id):
        return _error(404, "not_found", manual_lane.REFUSAL)

    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return _error(400, "no_file", "attach the mp4 Runway rendered")

    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", f"no concept {concept_id}")
    try:
        shot_n = int(form.get("shot_n") or (concept.get("shots") or [{}])[0].get("n", 1))
    except (TypeError, ValueError):
        shot_n = 1
    shot = next((s for s in concept.get("shots") or [] if s.get("n") == shot_n), None)
    if shot is None:
        return _error(404, "not_found", f"concept {concept_id} has no shot {shot_n}")
    if shot.get("media_url"):
        return _error(
            409, "already_filed",
            "this shot already has a clip -- it left the queue when the "
            "first one landed. Clear its media_url if you meant to replace it.")

    model = (form.get("model") or "").strip() or runway.DEFAULT_MODEL
    ratio = (form.get("ratio") or "").strip() or None
    duration_raw = (form.get("duration") or "").strip()
    try:
        duration = int(duration_raw) if duration_raw else None
    except (TypeError, ValueError):
        return _error(400, "bad_duration", f"duration {duration_raw!r} is not seconds")
    anchored = str(form.get("anchored") or "").lower() in ("1", "true", "on", "yes")

    import tempfile

    from ops import render_queue

    with tempfile.TemporaryDirectory() as tmp:
        landing = Path(tmp) / f"concept{concept_id}-shot{shot_n}.mp4"
        refused = await _spool_clip(upload, landing)
        if refused is not None:
            return refused
        try:
            filed = render_queue.import_clip(
                concept_id, shot_n, str(landing), model, None, None, anchored,
                account_id=account_id, provider="runway",
                duration=duration, ratio=ratio)
        except SystemExit as refusal:
            # render_specs said no (a model, a ratio or a length this
            # lane cannot have produced), or the concept moved under us.
            # Nothing was copied and no row was written -- that is
            # import_clip's own contract.
            return _error(400, "refused", str(refusal))
    return {"ok": True, **filed}


class ApproveBody(BaseModel):
    """WHICH RENDERER this approve spends on, and how.

    Every field is optional, and an empty body is the pre-2026-09-08
    call: it resolves to the tool the shot was actually PLANNED for
    (`providers.platform_default`), falling back to Runway. So an older
    client keeps working, and what it gets is the plan rather than a
    hardcoded vendor -- which is what the route did before, and was
    wrong about for every concept shootgen wrote for Kling or Seedance.

    `frame` is one field for two vocabularies on purpose: Runway takes a
    frame SIZE ("720:1280"), the other three take a resolution tier
    ("720p"). providers.FRAME_AXIS says which one a given renderer is
    talking about, and the card labels its control from that -- one axis
    with two names beats two fields where only ever one is legal.
    """
    provider: Optional[str] = None
    model: Optional[str] = None
    duration: Optional[int] = None
    frame: Optional[str] = None


@router.post("/queue/{concept_id}/approve")
def queue_approve(concept_id: int, body: Optional[ApproveBody] = None,
                  account_id: int = Depends(auth.current_account_id)):
    """Approve = render, and approving IS the pick.

    The concept's stored prompt goes through the renderer picked on the
    card (anchored on its keyframe when it has one) and the clip comes
    back attached to the shot. picked_at is stamped here rather than
    requiring a separate click, because with the chain parking scenes
    straight into the Queue the spend gate is where the real choice is
    made -- and pick_rate ("how many generated scenes were worth
    rendering") is better answered there than by a board click nothing
    was ever risked on.

    It deliberately does NOT archive the siblings any more. That tidy-up
    inferred "you have answered this batch" from which rows were picked,
    which was safe while picking was a separate bulk step done first:
    pick two, approve one, both survived. Now that approval is the pick,
    approving take 1 would archive takes 2-4 out from under you -- and
    nondeterministically, since it ran after the render returned ~90s
    later.  Rejecting archives explicitly, and that is the honest signal.

    ANY REGISTERED RENDERER, not just Runway (2026-09-08, Mike's call).
    The old body named `runway` in three places -- the key check, the
    render call and the button's price -- so the one surface that spends
    money could reach exactly one of four working adapters, and a scene
    planned for Kling was rendered on Runway without ever saying so. It
    dispatches through providers.VIDEO_PROVIDERS now, which is the same
    registry orchestrator.generate_render's connectors dict is built
    from, so the nightly graph and this button can no longer disagree
    about which vendor a tool name means.

    WHAT DID NOT CHANGE, and each of these is load-bearing:
      * the gates run in the same order and refuse the same things --
        no prompt, not queued, no reference photos;
      * the reference gate is asked HERE and not only in the listing,
        because this route is reachable by id and a concept can lose its
        refs between the two requests;
      * the pick is recorded BEFORE the spend, so a render that fails
        halfway still leaves the row saying you chose this one;
      * the spend approval is still checked inside the adapter's own
        generate_video and NOT here. That looks like something to hoist
        up for a nicer error, and it is not: the gate has to sit where
        the money is spent so no caller can spend around it, and a
        route-level copy would be a second opinion that can drift from
        the one that actually holds.

    WHAT SATISFIES THAT APPROVAL CHANGED (2026-09-09, Mike's call). It
    used to be `*_SPEND_OK=1` in the server's environment, which meant
    this button did nothing until somebody restarted the server with a
    variable set -- and once set for one render it stayed set for the
    session, which is the "approval that's always on" the gate was
    written to prevent, reached the long way round. The click IS the
    approval now: this route passes `approved=True` and the unattended
    callers (orchestrator.py, autopilot.py) pass nothing, so they still
    need their own env flag on purpose. The daily caps are untouched and
    are now the only automatic wall -- see generative.cap_error.
    """
    body = body or ApproveBody()
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    if not concept["shots"]:
        return _error(400, "no_prompt", "this concept carries no prompt to render")
    if not (concept.get("picked") or concept.get("parked")):
        return _error(400, "not_queued",
                      "this concept isn't in the queue — pick it on the board first")
    # Asked again HERE, not just in _waiting. The queue list and the
    # approve button are two requests, and a concept can lose its refs
    # between them; more to the point, this route is reachable by id
    # without ever reading the list. The gate has to sit where the money
    # is spent, which is this function.
    ungrounded = preprod.reference_gate(concept)
    if ungrounded:
        return _error(400, "no_reference",
                      f"this concept has no reference photos attached "
                      f"({ungrounded}) — rendering it would generate from "
                      f"text alone. Attach references and try again.")

    shot = concept["shots"][0]
    shot_n = shot.get("n", 1)
    # A SCENE OF SEVERAL TIMED SHOTS renders as that many clips, one after
    # another (2026-09-10, src/timeline.py). What decides it is the prompt
    # carrying windows, not whether the timeline happens to be planned yet
    # -- a stale or missing one is planned inside the job, before the first
    # clip, so the card can never render the old split of an edited scene.
    windows = [p["seconds"] for p in (_timeline_card(shot) or {}).get("parts") or []]

    # The plan is the default, the body overrides it. A shot carries the
    # tool shootgen chose; platform_default turns that into (provider,
    # model) through the SAME binding orchestrator.generate_render holds,
    # so "KLING" means one model in both places or in neither.
    # An empty body resolves exactly as the card's default did
    # (providers.render_default: the plan if this account can render it,
    # else the cheapest renderer it can), so the two cannot come apart.
    planned = providers.platform_default(shot.get("tool"))
    if body.provider:
        provider = body.provider
        model = body.model
        if model is None and planned and provider == planned[0]:
            model = planned[1]
    else:
        default = providers.render_default(shot.get("tool"), account_id)
        provider = default["provider"]
        model = body.model or default["model"]
    try:
        # A timed scene's LENGTHS are its windows', fitted to the model --
        # the card's duration does not apply, so it is not checked either.
        choice = (providers.check_timeline_choice(provider, model, body.frame, windows)
                  if windows else
                  providers.check_render_choice(
                      provider, model, body.duration, body.frame))
    except ValueError as e:
        # REFUSED, never clamped: a length or a frame outside the model's
        # own set is evidence the card and the model have come apart, and
        # quietly rounding it spends real money on something nobody
        # picked. (The adapters clamp internally -- that is their contract
        # with the nightly graph, which has no human to refuse to.)
        return _error(400, "bad_render_choice", str(e))

    module = providers.VIDEO_PROVIDERS[choice["provider"]]
    label = providers.RENDER_LABELS.get(choice["provider"], choice["provider"])
    # the CALLER's key, not the operator's: a BYOK account with its own
    # stored secret is available even on a server whose environment
    # variable is unset, and generate_for_shot resolves it per account
    # anyway (2026-09-08)
    if not module.has_key(account_id):
        return _error(503, "renderer_unavailable",
                      f"no {label} key is available for this account — add one, "
                      f"or approve on a renderer that has a key")

    # runway takes a frame SIZE and calls it `ratio`; the others take a
    # resolution tier. One axis, two parameter names -- see ApproveBody.
    frame_kw = "ratio" if choice["provider"] == "runway" else "resolution"
    render_kwargs = {"model": choice["model"],
                     "duration": choice["duration"],
                     frame_kw: choice["frame"]}

    # the pick is recorded BEFORE the spend, not after it: a render that
    # fails halfway still leaves the row saying you chose this one
    if not concept.get("picked"):
        preprod.set_picked(concept_id, True, account_id=account_id)

    def work(job):
        if windows:
            return _render_timeline(job, concept_id, shot_n, module, label, choice,
                                    frame_kw, account_id)
        jobs.progress(job, 0.2, f"rendering via {label} ({choice['model']})")
        result = module.generate_for_shot(
            concept_id, shot_n, db_path=None,
            resolve_photo=_resolve_asset_photo,
            # A PERSON PRESSED THE PRICED BUTTON. That is the approval
            # the adapter's gate is asking for -- see spend_approved.
            approved=True,
            account_id=account_id,
            **render_kwargs)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "render failed")
        return {"ref_id": concept_id, "detail": "clip attached"}

    job = jobs.start("render",
                     f"approved · {concept['title']} · {label} {choice['model']}",
                     work, account_id=account_id)
    return {"job_id": job["id"], "render": choice}


def _render_timeline(job, concept_id: int, shot_n, module, label: str, choice: dict,
                     frame_kw: str, account_id: int) -> dict:
    """Render a timed scene ONE SHOT AT A TIME, in order (2026-09-10).

    Each part is its own call through the SAME adapter entry point a whole
    scene goes through (`generate_for_shot(..., part=n)`), so every wall is
    unchanged per clip: the spend approval inside generate_video, the daily
    cap before each call, a generations row per attempt. Its length is its
    window fitted to the model (timeline.fit_seconds), its anchor its own
    still, its prompt the scene's continuity followed by that shot.

    Parts that already have a clip are skipped, and the loop stops at the
    first failure -- usually the daily cap -- keeping what rendered. The
    scene stays in the Queue until every part has its clip, so approving
    again renders the rest rather than paying for shot 1 twice."""
    jobs.progress(job, 0.05, "planning the shots")
    tl = timeline.ensure(concept_id, shot_n, resolve_photo=_resolve_asset_photo,
                         account_id=account_id)
    if not tl:
        raise RuntimeError("this scene's shots could not be planned -- open it in "
                           "Director or approve again")
    axis = providers.model_options(choice["provider"], choice["model"])["duration"]
    parts = tl.get("parts") or []
    todo = [p for p in parts if not p.get("media_url")]
    done = len(parts) - len(todo)
    for i, part in enumerate(todo):
        seconds = timeline.fit_seconds(axis, part.get("seconds"))
        jobs.progress(job, 0.1 + 0.85 * i / max(1, len(todo)),
                      f"shot {part['n']} of {len(parts)} · {seconds}s via {label} "
                      f"({choice['model']})")
        result = module.generate_for_shot(
            concept_id, shot_n, db_path=None, part=part["n"],
            resolve_photo=_resolve_asset_photo,
            approved=True,          # the priced button -- see queue_approve
            account_id=account_id,
            model=choice["model"], duration=seconds, **{frame_kw: choice["frame"]})
        if not result.get("ok"):
            raise RuntimeError(
                f"shot {part['n']} of {len(parts)} failed: "
                f"{result.get('error') or 'render failed'} -- {done} of {len(parts)} "
                f"rendered; approve again to render the rest")
        done += 1
    return {"ref_id": concept_id, "detail": f"{done} of {len(parts)} shots rendered"}


@router.post("/queue/{concept_id}/reject")
def queue_reject(concept_id: int, account_id: int = Depends(auth.current_account_id)):
    """Rejected here means: not worth the spend. Any pick comes off and
    the concept archives, so it reads as generated-but-not-picked in
    pick_rate -- which is the truth about it. This is the only thing
    that takes a sibling off the board now; approving no longer infers
    it (see queue_approve)."""
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    preprod.set_picked(concept_id, False, account_id=account_id)
    preprod.set_archived(concept_id, True, account_id=account_id)
    return {"ok": True, "pick": preprod.pick_rate(account_id=account_id)}


class ShotBody(BaseModel):
    shot: bool = True


@router.post("/queue/{concept_id}/shot")
def queue_mark_shot(concept_id: int, body: ShotBody,
                    account_id: int = Depends(auth.current_account_id)):
    """The camera: you made this yourself, outside the render pipeline --
    a manual Runway session, a hand-tweaked prompt, your own stills, cut
    together by hand -- and it worked. `shot_done` is the ground-truth
    column shoot_rate() has always read (preprod.py's own docstring:
    "you generate several concepts and go shoot some of them; that
    choice is ground truth about what's actually worth making"). It
    predates the render pipeline and was never wired to a button on
    /ui -- this is that wire, not a new label.

    Deliberately does nothing else. It does NOT touch picked_at (a
    manual shoot proves the idea, not that the system's OWN automated
    render was good -- queue_approve already owns that meaning and
    stays as-is). It does NOT attach media -- paste the finished clip's
    URL through /concepts/{id}/shots/{n}/media, same as any manual
    Runway render. And it does NOT rule for RAG -- grade the corrected
    prompt and the reason it worked on the Grade/Teach tabs same as
    anything else; this button only marks that the shoot happened, not
    what it taught. Toggleable, so a wrong click un-marks it.

    Marking it shot takes the card off the Queue's pending list (see
    queue_pending's filter) -- one you already made by hand isn't
    waiting on you to spend anything."""
    try:
        preprod.mark_shot(concept_id, body.shot, account_id=account_id)
    except ValueError as e:
        return _error(404, "not_found", str(e))
    return {"ok": True, "shot_done": body.shot,
            "shoot": preprod.shoot_rate(account_id=account_id)}


class ConceptRefsBody(BaseModel):
    refs: list[str] = []


@router.post("/concepts/{concept_id}/refs")
def concept_refs(concept_id: int, body: ConceptRefsBody, account_id: int = Depends(auth.current_account_id)):
    """The reference photos a scene grounds on -- a LIST, because a face
    and a jacket are two references. Stored on the shot itself, so they
    ride into the enhance, the keyframe and the clip."""
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None or not concept["shots"]:
        return _error(404, "not_found", "no such scene")
    shots = [dict(s) for s in concept["shots"]]
    shots[0]["refs"] = [asset_shelf.canonical_url(r)
                        for r in body.refs if r][:MAX_IMAGE_REFS]
    # a plan dict, not a bare list: update_concept_shots re-validates the
    # whole plan, and carrying the existing warnings/duration through
    # keeps attaching a reference from rewriting anything else
    preprod.update_concept_shots(
        concept_id,
        {"shots": shots, "duration": concept.get("duration")},
        warnings=concept.get("warnings") or [], account_id=account_id)
    return {"ok": True, "refs": shots[0]["refs"]}


@router.get("/concepts/{concept_id}")
def concept_detail(concept_id: int, account_id: int = Depends(auth.current_account_id)):
    """The scene board's data: the full shot list, each shot carrying its
    stored per-tool AI prompt plus the OpenArt Director rendering
    (pure text composition, zero model calls). This is the surface the
    plug-into-Runway loop works from: copy a shot's prompt, generate in
    the tool's own UI, paste the rendered clip's URL back onto the shot."""
    from src import shootgen

    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    # director_prompt (the OpenArt rendering) ships with in-progress
    # shootgen work; until that lands, the field is empty and the UI
    # renders no Director toggle -- degrade, don't crash.
    director = getattr(shootgen, "director_prompt", None)
    shots = []
    for shot in concept.get("shots") or []:
        shots.append({**shot,
                      "director_prompt": director(shot, concept) if director else ""})
    card = _concept_card(concept)
    return {**card, "duration": concept.get("duration"),
            "edit_note": concept.get("edit_note") or concept.get("edit"),
            "shots": shots,
            # the render button's copy is server-sourced: availability,
            # the spend gate's state, and what one clip would cost
            "runway": _runway_state()}


class ShotMediaBody(BaseModel):
    url: str


@router.post("/concepts/{concept_id}/shots/{shot_n}/media")
def shot_media_attach(concept_id: int, shot_n: int, body: ShotMediaBody,
                      account_id: int = Depends(auth.current_account_id)):
    """Attach the rendered clip's URL to one shot -- the paste-back half
    of the Runway loop, and the field autopilot.build_plan() requires
    before it will ever emit a post action."""
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        return _error(400, "invalid_url",
                      "paste the clip's public http(s) URL")
    try:
        preprod.set_shot_media_url(concept_id, shot_n, url, account_id=account_id)
    except ValueError as e:
        return _error(404, "not_found", str(e))
    return {"concept_id": concept_id, "shot_n": shot_n, "media_url": url}


class DirectBody(BaseModel):
    note: str


@router.post("/concepts/{concept_id}/direct")
def concept_direct(concept_id: int, body: DirectBody, account_id: int = Depends(auth.current_account_id)):
    """Director mode: one note revises the stored scene in place --
    validated, attachments carried over, refused when the revision
    comes back broken. One billed call per note."""
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    note = body.note.strip()
    if not note:
        return _error(400, "empty_note", "an empty note directs nothing")
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")

    def work(job):
        from google import genai

        from src import director
        jobs.progress(job, 0.3, "revising the scene")
        result = director.direct_scene(
            concept_id, note, gemini_client=genai.Client(api_key=api_key),
            db_path=None)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "direction failed")
        detail = result.get("summary") or "revised"
        if result.get("warnings"):
            detail += f" · {len(result['warnings'])} warning(s)"
        return {"ref_id": concept_id, "detail": detail}

    job = jobs.start("direct", f"direct · {note[:60]}", work, account_id=account_id)
    return {"job_id": job["id"]}


@router.post("/concepts/{concept_id}/shots/{shot_n}/refine")
def shot_refine(concept_id: int, shot_n: int, account_id: int = Depends(auth.current_account_id)):
    """Technique-aware polish for one shot's AI prompt, grounded in the
    ai_prompting shelf. Falls back to unchanged on anything broken."""
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")

    def work(job):
        from google import genai

        from src import director
        jobs.progress(job, 0.3, "polishing against technique references")
        result = director.refine_shot_prompt(
            concept_id, shot_n, gemini_client=genai.Client(api_key=api_key),
            db_path=None)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "polish failed")
        return {"ref_id": concept_id, "detail": result.get("summary") or "polished"}

    job = jobs.start("refine", f"polish · shot {shot_n}", work, account_id=account_id)
    return {"job_id": job["id"]}


@router.post("/concepts/{concept_id}/shots/{shot_n}/generate")
def shot_generate(concept_id: int, shot_n: int, account_id: int = Depends(auth.current_account_id)):
    """One click, one render: the shot's stored prompt through the
    Runway API (anchored on its reference_image when set), the clip
    downloaded, logged as a generations row, and attached to the shot.

    Billed and capped. The click is the spend approval (2026-09-09) --
    this route passes approved=True into generate_for_shot, and the gate
    itself still lives inside generate_video so nothing here spends
    around it. RUNWAY_DAILY_CAP is what stops a stuck loop."""
    # the caller's key, not the operator's -- see queue_approve
    if not runway.has_key(account_id):
        return _error(503, "runway_unavailable", "RUNWAYML_API_SECRET is not set")
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")

    def work(job):
        jobs.progress(job, 0.2, "rendering via Runway")
        result = runway.generate_for_shot(
            concept_id, shot_n, db_path=None,
            resolve_photo=_resolve_asset_photo, approved=True,
            account_id=account_id)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "render failed")
        return {"ref_id": concept_id,
                "detail": f"clip attached to shot {shot_n}"}

    job = jobs.start("render", f"runway · {concept['title']} shot {shot_n}", work, account_id=account_id)
    return {"job_id": job["id"]}


# Cap what one Create sends to Gemini, same as the composer's MAX_ATTACH
# and scene_chain.MAX_REFS. 6 -> 12 on 2026-09-10: the extras ground the
# writing and the per-shot planner; Mike narrows them afterwards.
MAX_IMAGE_REFS = 12

_PHOTO_ROOTS = {
    "locations": LOCATIONS_DIR,
    "characters": CHARACTERS_DIR,
    "props": PROPS_DIR,
}


# Composer uploads. A photo dragged onto the composer is a reference
# in exactly the sense a picked asset photo is -- it just had nowhere to
# live, so it grounded one Gemini call and vanished. It lives here now,
# beside the rendered clips, under the same gitignored data/ roof.
#
# The directory, the content-addressed name and the JPEG normalisation
# moved to src/refbin.py once the scout started writing research images
# into the same bin: src/ cannot import app/, so leaving the rule here
# would have meant a second implementation of it, and a second writer
# that drifts is how one photo ends up stored under two names. These
# two names stay as the app-side spelling -- app/main.py mounts
# UPLOAD_REFS_DIR, and several routes call _save_upload_ref.
UPLOAD_REFS_DIR = refbin.REFS_DIR


def _save_upload_ref(jpeg: bytes) -> Optional[str]:
    """Persist one uploaded reference, return the URL it rides on.
    Best-effort: a full disk costs the reference, never the scene that
    was being written."""
    return refbin.save(jpeg)


def _resolve_asset_photo(url_path: str) -> Optional[Path]:
    """A reference URL -> the file on disk, or None.

    Delegates to src/asset_shelf.resolve_photo (2026-08-31). The rule
    moved down there because the nightly graph resolves references at
    6am with no web app running and cannot call this; two copies of a
    path-traversal guard is the shape of bug where one of them is weaker
    and nobody notices. Behaviour is unchanged: both URL shapes, the
    ?thumb strip, and anything escaping its root silently dropped.

    Composer uploads (/refs/<name>.jpg) resolve here too, because every
    caller that turns a reference URL into bytes -- the scene writer,
    the Director graph's enhance/keyframe/clip nodes -- goes through
    this one function. The research scout writes into the same bin, so
    a crawled image needs no new route and no new resolver.
    """
    # roots injected (the tests point them at a tmp_path); the refs
    # directory deliberately NOT injected -- src/refbin.py owns it in
    # both directions, so the reader has to follow refbin.REFS_DIR or
    # it moves while the writer stays on the real folder.
    return asset_shelf.resolve_photo(url_path, roots=_PHOTO_ROOTS)


MAX_VIDEO_REFS = 2   # a video ref is heavy; two is plenty of grounding

# Under this, a clip rides inline as Part.from_bytes -- the same shape
# image refs use, just a video mime. Over it, the Gemini Files API is
# the documented path (inline requests cap out around 20MB total).
INLINE_VIDEO_LIMIT = 19_000_000

VIDEO_MIMES = {
    ".mp4": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".m4v": "video/x-m4v",
}


def _video_mime(filename: str) -> Optional[str]:
    from pathlib import PurePosixPath
    return VIDEO_MIMES.get(PurePosixPath(filename or "").suffix.lower())


def video_part(client, data: bytes, mime: str):
    """One video reference -> something a Gemini call can take as vision
    input. Small clips ride inline as bytes; anything bigger goes
    through the Files API (upload, poll until ACTIVE, hand back the file
    handle -- the SDK accepts it directly in contents). None on any
    failure: a reference is an enhancement, never a gate."""
    import io
    import time as _time

    from google.genai import types

    try:
        if len(data) <= INLINE_VIDEO_LIMIT:
            return types.Part.from_bytes(data=data, mime_type=mime)
        handle = client.files.upload(file=io.BytesIO(data),
                                     config={"mime_type": mime})
        deadline = _time.time() + 120
        while getattr(handle.state, "name", str(handle.state)) == "PROCESSING" \
                and _time.time() < deadline:
            _time.sleep(2)
            handle = client.files.get(name=handle.name)
        if getattr(handle.state, "name", str(handle.state)) != "ACTIVE":
            return None
        return handle
    except Exception:
        return None


# Photo formats Pillow reads out of the box. IMAGE_EXTENSIONS also
# lists .heic -- correctly, an iPhone export IS a photo and belongs in
# the gallery -- but Pillow only decodes it with pillow-heif present,
# and a reference that fails to decode is dropped SILENTLY, which is
# the worst way for a reference to fail. Preferring a sibling the
# renderer can definitely read costs nothing when there is one.
_DECODES_NATIVELY = {".jpg", ".jpeg", ".png", ".webp"}


def _to_jpeg(data: bytes) -> Optional[bytes]:
    """Any readable upload -> upright RGB JPEG. See src/refbin.to_jpeg
    for why the EXIF transpose has to happen before the RGB convert."""
    return refbin.to_jpeg(data)


def scene_grounding(brand: str, spark, client=None) -> str:
    """
    Everything a scene generation grounds on, composed at the edge (the
    reference_block contract: generators stay hermetic).

    The brand's own inspiration accounts ride in front of the retrieved
    references, brand-scoped so ANTIHERO's own riffs never leak
    into Zero Page's faceless ideation. This used to live on the dev
    console's /concepts/generate; that route went with the page, and
    without it here the accounts would quietly stop steering anything.
    Both halves degrade to "" rather than failing a generation.
    """
    from src import shootgen

    references = shootgen.reference_block(spark=spark, client=client,
                                          db_path=None)
    try:
        insp = inspiration.combined_grounding(brand=brand)
    except Exception:
        insp = ""
    if insp:
        return insp + "\n\n" + (references or "")
    return references


@router.post("/pipeline/run")
async def pipeline_run(request: Request, account_id: int = Depends(auth.current_account_id)):
    """The Create button: one full concept from the composer's prompt,
    grounded exactly the way /concepts/generate grounds -- reference
    block first, then the generator. Multipart: `prompt` plus optional
    attached media (`files` uploads and `asset_photos` picked from the
    media panel), which ride into the generation as vision input.
    Billed, so it only exists when the key does."""
    form = await request.form()
    prompt = (form.get("prompt") or "").strip()
    if not prompt:
        return _error(400, "empty_prompt", "a prompt is required")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    brand_raw = form.get("brand")
    brand = brand_raw if brand_raw in preprod.BRANDS else (
        request.cookies.get("brand") if request.cookies.get("brand") in preprod.BRANDS
        else "antihero")

    image_refs, refs, _ = await _collect_refs(form)

    def work(job):
        from google import genai

        from src import scene_chain, shootgen
        gemini_client = genai.Client(api_key=api_key)
        jobs.progress(job, 0.15, "grounding in references")
        references = scene_grounding(brand, prompt, client=gemini_client)
        # Named in the prompt, or picked (asset_photos/uploads) -- the
        # same rule Studio's Create button follows, not the old
        # cast=None default that showed this brief every character and
        # prop on file regardless of whether the brief named any of
        # them (2026-09-03, Mike's call). Split out of scene_chain.ground()
        # so this doesn't also re-run reference_block, which scene_grounding
        # already queried above.
        try:
            cast, _locs = scene_chain.scoped_cast_and_locations(
                prompt, brand, refs, db_path=None, account_id=account_id)
        except Exception:
            cast = None
        jobs.progress(job, 0.35,
                      "writing the scene prompt"
                      + (f" · {len(image_refs)} image ref(s)" if image_refs else ""))
        # One concept = one scene = one paste-ready prompt (2026-08-26).
        # The old idea -> shot-list split is still reachable through the
        # two-stage path; this button no longer produces it.
        result = shootgen.generate_scene_concept(
            brand=brand, spark=prompt,
            gemini_client=gemini_client,
            db_path=None, references=references, cast=cast,
            image_refs=image_refs or None,
        )
        title = (result.get("concept") or {}).get("title") or "untitled"
        warnings = result.get("warnings") or []
        detail = f'"{title}"'
        if warnings:
            detail += f" · {len(warnings)} warning(s)"
        # the same grounding /scenes/run does: this concept goes to
        # Director too, and a brief-written scene needs its face as
        # much as a Create-written one
        try:
            if result.get("concept_id"):
                attached = _attach_scene_refs(result["concept_id"], refs, account_id,
                                              idea=prompt)
                if attached:
                    detail += f" · {len(attached)} reference(s)"
        except Exception:
            pass
        return {"ref_id": result.get("concept_id"), "detail": detail}

    job = jobs.start("concept", f"concept · {prompt[:60]}", work, account_id=account_id)
    return {"job_id": job["id"], "image_refs": len(image_refs)}


# --- generate tab (Higgsfield-style one-shot generation) --------------------
# One run through the same four primitives Concept uses -- Reference /
# Ground / Enhance / Generate -- for a single image or clip. The result
# is NOT a second data model: it saves as an ordinary shoot_concepts
# row with exactly one shot (or appends a shot to an existing concept),
# so teach-to-RAG, generation history, and the scene board all keep
# working unmodified.

GENERATE_OUTPUTS = ("image", "video", "prompt")


@router.get("/presets")
def presets_list():
    """The curated camera/framing scaffolds (prompts/presets.json) the
    Generate tab and Director nodes fold into the Enhance step, plus
    the enhancement instruction (prompts/enhance_system.txt) the
    Director chain seeds its Instructions node with."""
    return {"items": presets.load_presets(),
            "enhance_system": workflows._enhance_system_text()}


@router.get("/director/landing")
def director_landing(request: Request, brand: Optional[str] = None,
                     account_id: int = Depends(auth.current_account_id)):
    """Director tab's chat-first entry: a real pre-filled sample brief
    (the gold-standard exemplar, shortened to its style + action blocks)
    plus quick-start chips. Zero Page's chips are its real format
    skeletons (ZEROPAGE_FORMATS); Antihero has no equivalent fixed list
    yet, so it leads with the sample composer alone."""
    from src import shootgen

    brand = brand if brand in preprod.BRANDS else (
        request.cookies.get("brand")
        if request.cookies.get("brand") in preprod.BRANDS else "antihero")
    sample = shootgen.gold_standard_example()
    if sample:
        paragraphs = [p for p in sample.split("\n\n") if p.strip()]
        sample = "\n\n".join(paragraphs[:2])
    chips = []
    if brand == "zeropage":
        chips = [{"label": name, "text": how}
                 for name, how in shootgen.ZEROPAGE_FORMATS[:4]]
    return {"brand": brand, "sample_prompt": sample, "chips": chips}


def _enhance_generate_prompt(gemini_client, prompt: str, *, preset=None,
                             references: str = "", image_refs=None,
                             video_refs=None) -> str:
    """The Enhance primitive for one Generate-tab run: the typed prompt,
    the picked preset's scaffold, and the RAG references folded into one
    billed Gemini call, with image/video references riding as real
    vision input. Raises on failure -- here the model call IS the
    deliverable, the promptgen contract."""
    from google.genai import types

    from src import shootgen
    from src import workflows as _workflows
    from src.gemini_utils import generate_with_retry

    blocks = [_workflows._enhance_system_text()]
    if preset:
        blocks.append("CAMERA / FRAMING SCAFFOLD -- build the prompt around "
                      f"this move:\n{preset['label']}: {preset['how']}")
    if references:
        blocks.append("REFERENCES -- ground the prompt in these:\n" + references)
    if image_refs or video_refs:
        blocks.append("(Reference media is attached above -- ground the prompt "
                      "in what it actually shows, don't ignore it.)")
    blocks.append("PROMPT TO ENHANCE:\n" + prompt)

    # caption then image, so the model is told which photo is the face
    # and which is the jacket rather than inferring it from the prose
    parts: list = []
    for ref in image_refs or []:
        if len(ref) > 2 and ref[2]:
            parts.append(ref[2])
        parts.append(types.Part.from_bytes(data=ref[0], mime_type=ref[1]))
    for data, mime in video_refs or []:
        part = video_part(gemini_client, data, mime)
        if part is not None:
            parts.append(part)
    parts.append("\n\n".join(blocks))
    return generate_with_retry(gemini_client, shootgen.MODEL, parts, stage="enhance").strip()


def _generate_title(prompt: str) -> str:
    words = prompt.split()
    title = " ".join(words[:8])
    return title + ("…" if len(words) > 8 else "")


@router.post("/generate/run")
async def generate_run(request: Request, account_id: int = Depends(auth.current_account_id)):
    """The Generate button: preset + prompt (+ attached image/video
    references) -> Ground -> Enhance -> saved one-shot concept -> the
    render. The render is best-effort and honestly gated: an image goes
    through Nano Banana (cheap, capped) and lands as the shot's
    reference_image; a video goes through Runway's spend gate and lands
    as media_url; a refusal still leaves the saved concept + prompt."""
    form = await request.form()
    prompt = (form.get("prompt") or "").strip()
    if not prompt:
        return _error(400, "empty_prompt", "a prompt is required")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    brand_raw = form.get("brand")
    brand = brand_raw if brand_raw in preprod.BRANDS else (
        request.cookies.get("brand") if request.cookies.get("brand") in preprod.BRANDS
        else "antihero")
    output = form.get("output")
    if output not in GENERATE_OUTPUTS:
        output = "image"
    preset = presets.get_preset(form.get("preset"))
    concept_id_raw = (form.get("concept_id") or "").strip()
    attach_to = int(concept_id_raw) if concept_id_raw.isdigit() else None
    if attach_to is not None and preprod.get_concept(attach_to, account_id=account_id) is None:
        return _error(404, "not_found", "no such concept to attach to")

    image_refs, ref_urls, video_refs = await _collect_refs(form, want_video=True)

    def work(job):
        # NOT `def work(job, account_id=None)` (2026-09-02): jobs.start
        # calls fn(job), so that parameter shadowed the route's
        # dependency with None and every concept this route saved
        # belonged to nobody until backfill_owner handed it to the
        # bootstrap account at the next startup.
        from google import genai

        from src import nano_banana, shootgen
        gemini_client = genai.Client(api_key=api_key)

        jobs.progress(job, 0.1, "grounding in references")
        references = shootgen.reference_block(spark=prompt, db_path=None)

        refs_note = ""
        if image_refs or video_refs:
            refs_note = f" · {len(image_refs) + len(video_refs)} ref(s)"
        jobs.progress(job, 0.3, "enhancing prompt" + refs_note)
        enhanced = _enhance_generate_prompt(
            gemini_client, prompt, preset=preset, references=references,
            image_refs=image_refs, video_refs=video_refs)
        if not enhanced:
            raise RuntimeError("enhancement came back empty")

        jobs.progress(job, 0.55, "saving concept")
        shot = {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                "desc": prompt, "prompt": enhanced}
        allowed = shootgen.ZEROPAGE_AI_TOOLS if brand == "zeropage" else None
        location_names = [loc["name"]
                          for loc in preprod.list_locations(account_id=account_id)]
        if attach_to is not None:
            concept = preprod.get_concept(attach_to, account_id=account_id)
            shots = list(concept.get("shots") or [])
            shot["n"] = max((s.get("n") or 0 for s in shots), default=0) + 1
            shots.append(shot)
            warnings = shootgen.validate_concept(
                {**concept, "shots": shots}, location_names,
                use_pov=bool(concept.get("use_pov")), allowed_tools=allowed)
            preprod.update_concept_shots(attach_to, {"shots": shots},
                                         warnings=warnings, account_id=account_id)
            concept_id = attach_to
        else:
            concept_dict = {"title": _generate_title(prompt), "hook": "",
                            "logline": prompt, "shots": [shot]}
            warnings = shootgen.validate_concept(
                concept_dict, location_names, allowed_tools=allowed)
            concept_id = preprod.save_concept(
                concept_dict, brand=brand, spark=prompt,
                warnings=warnings, account_id=account_id)
            # a one-shot generation is a concept like any other and
            # opens in Director like any other, so it grounds like any
            # other -- best-effort, never fails the generation
            try:
                _attach_scene_refs(concept_id, ref_urls, account_id)
            except Exception:
                pass

        notes = []
        if output == "image":
            jobs.progress(job, 0.7, "rendering image via Nano Banana")
            result = nano_banana.generate_from_prompt(
                enhanced, reference_image=image_refs[0][0] if image_refs else None,
                db_path=None)
            if result.get("ok"):
                preprod.set_shot_reference_image(
                    concept_id, shot["n"], result["media_url"], account_id=account_id)
                notes.append("image rendered → shot reference")
            else:
                notes.append(f"image render skipped: {result.get('error')}")
        elif output == "video":
            if runway.has_key():
                jobs.progress(job, 0.7, "rendering via Runway")
                result = runway.generate_from_prompt(
                    enhanced,
                    reference_image=image_refs[0][0] if image_refs else None,
                    # a person asked for a video from this composer
                    approved=True,
                    db_path=None)
                if result.get("ok"):
                    preprod.set_shot_media_url(
                        concept_id, shot["n"], result["media_url"], account_id=account_id)
                    notes.append("clip rendered and attached")
                else:
                    notes.append(f"render skipped: {result.get('error')}")
            else:
                notes.append("render skipped: RUNWAYML_API_SECRET not set")

        detail = "prompt saved" if output == "prompt" else (notes[0] if notes else "saved")
        if warnings:
            detail += f" · {len(warnings)} warning(s)"
        return {"ref_id": concept_id, "detail": detail, "output": enhanced,
                "shot_n": shot["n"]}

    job = jobs.start("generate", f"generate · {prompt[:60]}", work, account_id=account_id)
    return {"job_id": job["id"],
            "image_refs": len(image_refs), "video_refs": len(video_refs)}


# --- director mode: per-shot save-back --------------------------------------

class ShotPromptBody(BaseModel):
    prompt: str


class ShotGraphBody(BaseModel):
    graph: dict
    states: Optional[dict] = None
    name: Optional[str] = None
    # what the canvas was drawn against (from the GET); a save carrying a
    # hash the shot no longer matches is refused rather than applied
    seed_hash: Optional[str] = None


@router.put("/concepts/{concept_id}/shots/{shot_n}/graph")
def shot_graph_save(concept_id: int, shot_n: int, body: ShotGraphBody,
        account_id: int = Depends(auth.current_account_id)):
    """Keep a shot's canvas — the node tree AND what each node produced.

    Run all used to save the graph to a throwaway workflow row purely so
    the runner had something to execute, and reopening the concept
    rebuilt the canvas from the shot and cleared every output. That made
    re-running a paid Gemini enhance the only way to see the enhanced
    prompt again (2026-08-28)."""
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    current = _shot_seed_hash(concept, shot_n)
    if current is None:
        return _error(404, "not_found", "no such shot")
    if not body.graph.get("nodes"):
        return _error(400, "empty_graph", "nothing to save")
    # The React canvas hands back the seed_hash it loaded against. A shot
    # revised underneath it (Direct, Polish, a replan) means the drawing
    # is of words the shot no longer says -- refuse, and the client
    # re-reads a fresh seed instead of overwriting a canvas it never saw.
    if body.seed_hash and body.seed_hash != current:
        return _error(409, "stale_canvas",
                      "the scene changed since this canvas was drawn -- reload it")
    workflow_id = workflows.save_shot_graph(
        concept_id, shot_n, body.graph, states=body.states,
        name=body.name or concept.get("title"), brand=concept.get("brand"),
        seed_hash=current,
        account_id=account_id)
    return {"ok": True, "id": workflow_id, "seed_hash": current}


def _shot_seed_hash(concept: dict, shot_n: int) -> Optional[str]:
    """What the canvas was drawn against. A saved graph carries a copy
    of the shot's prompt in its User Prompt node, so if the shot's
    prompt changes underneath it -- a Direct revision, a Polish, a
    replan -- the stored drawing is of a shot that no longer says that.

    The refs are in the hash for the same reason and were missed for a
    worse one: the graph freezes them into `ref_urls` on every billed
    node, so a shot whose references improve while its prompt stays
    identical restores a canvas still grounded on the old ones, and the
    next keyframe silently renders against a set nobody meant to use
    (2026-08-29 -- found re-attaching a scene's photos). A drawing of
    the wrong references is as stale as a drawing of the wrong words.
    """
    shot = next((s for s in (concept.get("shots") or [])
                 if s.get("n") == shot_n), None)
    if shot is None:
        return None
    seed = [shot.get("prompt") or ""]
    seed.extend(str(ref) for ref in (shot.get("refs") or []))
    return hashlib.sha256("\x00".join(seed).encode()).hexdigest()


@router.get("/concepts/{concept_id}/shots/{shot_n}/graph")
def shot_graph_get(concept_id: int, shot_n: int, account_id: int = Depends(auth.current_account_id)):
    """The saved canvas, or `graph: null` meaning build a fresh one.

    Staleness is checked HERE rather than invalidated from the handful
    of routes that can rewrite a prompt (direct, refine, approve, the
    canvas's own save). Comparing on read is self-healing: a route
    added later that rewrites a prompt cannot forget to call anything.
    """
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    current = _shot_seed_hash(concept, shot_n)
    if current is None:
        return _error(404, "not_found", "no such shot")
    saved = workflows.get_shot_graph(concept_id, shot_n,
                                     account_id=account_id)
    # `seed_hash` is always the CURRENT one -- what a save must carry --
    # so a fresh canvas and a stale one both learn what they are drawn against
    if saved is None:
        return {"graph": None, "states": None, "updated_at": None,
                "stale": False, "seed_hash": current}
    if saved.get("seed_hash") and saved["seed_hash"] != current:
        return {"graph": None, "states": None,
                "updated_at": saved["updated_at"], "stale": True,
                "seed_hash": current}
    saved["stale"] = False
    saved["seed_hash"] = current
    return saved


@router.delete("/concepts/{concept_id}/graph")
def shot_graph_reset(concept_id: int, account_id: int = Depends(auth.current_account_id)):
    """Throw the saved canvases away and rebuild from the shots — the
    escape hatch for a graph that has gone stale against its prompt.
    Someone else's concept is a 404, the same as a missing one."""
    if preprod.get_concept(concept_id, account_id=account_id) is None:
        return _error(404, "not_found", "no such concept")
    removed = workflows.delete_shot_graphs(concept_id,
                                           account_id=account_id)
    return {"ok": True, "removed": removed}


@router.post("/concepts/{concept_id}/shots/{shot_n}/prompt")
def shot_prompt_update(concept_id: int, shot_n: int, body: ShotPromptBody,
        account_id: int = Depends(auth.current_account_id)):
    """Persist one shot's edited prompt from the Director canvas --
    through update_concept_shots (so the picked title/hook/logline are
    never touched), re-validated the same way a fresh plan is. The
    other shots ride along unchanged."""
    from src import shootgen

    text = body.prompt.strip()
    if not text:
        return _error(400, "empty_prompt", "an empty prompt renders nothing")
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    shots = concept.get("shots") or []
    shot = next((s for s in shots if s.get("n") == shot_n), None)
    if shot is None:
        return _error(404, "not_found", f"no shot {shot_n}")
    shot["prompt"] = text
    warnings = shootgen.validate_concept(
        {**concept, "shots": shots},
        [loc["name"] for loc in preprod.list_locations(account_id=account_id)],
        use_pov=bool(concept.get("use_pov")),
        allowed_tools=shootgen.ZEROPAGE_AI_TOOLS
        if concept.get("brand") == "zeropage" else None)
    preprod.update_concept_shots(concept_id, {"shots": shots},
                                 warnings=warnings, account_id=account_id)
    return {"concept_id": concept_id, "shot_n": shot_n, "warnings": warnings}


class ShotReferenceBody(BaseModel):
    url: str


@router.post("/concepts/{concept_id}/shots/{shot_n}/reference")
def shot_reference_attach(concept_id: int, shot_n: int, body: ShotReferenceBody,
                          account_id: int = Depends(auth.current_account_id)):
    """Attach (or clear, with "") an image URL as one shot's reference
    anchor -- how a Director-canvas Nano render lands back on the shot.
    The /ui JSON twin of the dev console's form route."""
    url = body.url.strip()
    if url and not url.startswith(("http://", "https://", "/")):
        return _error(400, "invalid_url",
                      "paste a public http(s) URL or a site-relative path")
    try:
        preprod.set_shot_reference_image(concept_id, shot_n, url, account_id=account_id)
    except ValueError as e:
        return _error(404, "not_found", str(e))
    return {"concept_id": concept_id, "shot_n": shot_n,
            "reference_image": url or None}


@router.post("/concepts/{concept_id}/approve")
def concept_approve(concept_id: int, account_id: int = Depends(auth.current_account_id)):
    """Approve an idea = write ITS scene prompt (2026-08-26). Stage two
    used to explode an idea into a shot list; a concept is one scene now,
    so this fills in that one prompt. Only an idea needs it -- a concept
    that already carries its scene has nothing to write."""
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    if concept.get("shots"):
        return _error(409, "already_written",
                      "this concept already has its scene prompt")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        from google import genai

        from src import shootgen
        jobs.progress(job, 0.2, "grounding in references")
        references = shootgen.reference_block(
            spark=concept.get("title"), db_path=None)
        jobs.progress(job, 0.4, "writing the scene prompt")
        result = shootgen.write_scene_for_concept(
            concept_id, gemini_client=genai.Client(api_key=api_key),
            references=references, db_path=None,
        )
        warnings = result.get("warnings") or []
        detail = "scene written"
        if warnings:
            detail += f" · {len(warnings)} warning(s)"
        return {"ref_id": concept_id, "detail": detail}

    job = jobs.start("plan", f"scene · {concept['title']}", work, account_id=account_id)
    return {"job_id": job["id"], "concept_id": concept_id}


class DenyBody(BaseModel):
    reasons: list[str]
    note: Optional[str] = None


@router.post("/concepts/{concept_id}/deny")
def concept_deny(concept_id: int, body: DenyBody, account_id: int = Depends(auth.current_account_id)):
    """Deny records WHY, then vacates the slot: the reasons + note become
    a correction the next generation's spark folds in (autonomy's
    human_note channel, consumed once), and the same text is written to
    the RAG 'denials' shelf as evidence. The correction always lands;
    the chunk is best-effort -- a down store must not lose the label."""
    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    reasons = [r for r in body.reasons if r in DENY_REASONS]
    if not reasons:
        return _error(400, "invalid_reasons",
                      f"reasons must be one or more of: {', '.join(DENY_REASONS)}")
    note = (body.note or "").strip()

    summary = f"Denied \"{concept['title']}\": {', '.join(reasons)}"
    if note:
        summary += f" — {note}"
    correction_id = autonomy.add_correction(summary)

    chunk_written = 0
    chunk_error = None
    text = "\n".join(filter(None, [
        f"DENIED CONCEPT: {concept['title']}",
        f"Reasons: {', '.join(reasons)}",
        f"Note: {note}" if note else None,
        f"Logline: {concept.get('logline') or ''}",
        f"Spark: {concept.get('spark') or ''}",
        f"Brand: {concept.get('brand') or ''}",
    ]))
    try:
        conn = rag.connect()
        try:
            rag.init_store(conn)
            # project is the TENANT that taught the lesson, not the brand
            # (src/rag.py's docstring says why the brand was the wrong key)
            chunk_written = rag.ingest_records(
                [{"source": f"denials/concept-{concept_id}", "text": text,
                  "domain": "denials",
                  "project": accounts.slug_of(account_id),
                  "source_ref": None}],
                rag.make_client(), conn,
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        chunk_error = str(e)

    preprod.delete_concept(concept_id, account_id=account_id)
    return {
        "denied": concept_id,
        "correction_id": correction_id,
        "chunks_written": chunk_written,
        "chunk_error": chunk_error,
    }


# --- holds ------------------------------------------------------------------

@router.get("/holds")
def holds_list(channel: Optional[str] = None,
               account_id: int = Depends(auth.current_account_id)):
    """This account's hold queue. `channel` is the brand pill's filter
    and filters INSIDE the tenant, never across it."""
    held = autonomy.list_hold(status="held", account_id=account_id)
    if channel:
        held = [h for h in held if h["channel"] == channel]
    return {
        "items": held,
        "agreement": autonomy.evaluator_agreement(account_id=account_id),
        "gate": autonomy.prompt_gate_agreement(),
        "pass_rate": autonomy.first_try_pass_rate(),
        "channels": autonomy.list_channels(),
        "killed": autonomy.killed(),
    }


class ResolveBody(BaseModel):
    status: str


@router.post("/holds/{hold_id}/resolve")
def holds_resolve(hold_id: int, body: ResolveBody,
                  account_id: int = Depends(auth.current_account_id)):
    row = autonomy.get_hold(hold_id, account_id=account_id)
    if row is None:
        return _error(404, "not_found", "no such hold")
    try:
        autonomy.resolve_hold(hold_id, body.status,
                              account_id=account_id)
    except ValueError as e:
        return _error(400, "invalid_status", str(e))
    # Mirror /holds' grading: the human verdict lands next to the gate's.
    run_id = (row.get("payload") or {}).get("run_id") \
        if isinstance(row.get("payload"), dict) else None
    if run_id and body.status in ("approved", "rejected"):
        autonomy.set_prompt_verdicts(
            run_id, "post" if body.status == "approved" else "reject")
    return {"id": hold_id, "status": body.status}


@router.post("/holds/{hold_id}/post")
def holds_post(hold_id: int, account_id: int = Depends(auth.current_account_id)):
    """The explicit 'post now' -- moved here from the retired /holds dev
    page (2026-08-26) so /ui's hold queue keeps the whole ritual. One
    post action per channel target, through autopilot's gate; until
    credentials and real media exist it reports exactly what's missing
    rather than pretending.

    THE GATE, named (2026-09-02): this is the most expensive
    irreversible action in the product, and until the dry run it took
    no account at all -- `def holds_post(hold_id)`, an unscoped lookup,
    then execute(approve=True, dry_run=False). What stands between a
    caller and a post now:
      * ownership -- the hold must be this account's (404 otherwise),
        the one fact here that is about the CALLER;
      * ZEROPAGE_POST_OK=1, the per-run approval in the render tools'
        SPEND_OK shape (autopilot.POST_ENV), checked inside the
        executor so nothing posts around it;
      * ZEROPAGE_AUTOPILOT, the platform credentials, and the
        data/autopilot.off kill switch -- three facts about the
        INSTALLATION, unchanged.
    The `approve=True` below is this click. What is still not checked
    is whether this person may publish AS the installation, whose
    credentials every post goes out under -- that is the role system
    this project deliberately does not have (see autopilot.POST_ENV)."""
    row = autonomy.get_hold(hold_id, account_id=account_id)
    if row is None:
        return _error(404, "not_found", "no such hold")
    channel = autonomy.get_channel(row.get("channel", "")) or {}
    targets = [t.strip() for t in (channel.get("targets") or "").split(",") if t.strip()]
    if not targets:
        return _error(400, "no_targets", "this channel has no post targets")

    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    caption = row.get("caption") or ""
    image_url = (payload.get("image_url") or "").strip()
    if image_url:
        actions = [{
            "kind": "post", "platform": platform, "concept_id": row.get("concept_id"),
            "caption": caption, "image_url": image_url,
        } for platform in targets]
    else:
        clips = payload.get("clips") or []
        media_url = next((c.get("url") for c in clips if c.get("url")), "") or ""
        is_local = bool(media_url) and not media_url.startswith("http")
        actions = [{
            "kind": "post", "platform": platform, "concept_id": row.get("concept_id"),
            "caption": caption,
            "video_url": media_url,
            "video_path": media_url if is_local else "",
        } for platform in targets]

    try:
        result = autopilot.execute({"actions": actions}, approve=True, dry_run=False)
    except Exception as e:
        return _error(502, "post_failed", str(e))

    mode = result.get("mode")
    if mode == "live" and result.get("executed"):
        autonomy.resolve_hold(hold_id, "posted", account_id=account_id)
        return {"id": hold_id, "posted": True, "targets": targets, "mode": mode}
    if mode == "live":
        detail = "; ".join(result.get("skipped") or ["no rendered media to post yet"])
    elif mode == "disabled":
        detail = "posting is OFF — set ZEROPAGE_AUTOPILOT=1 and the platform credentials"
    elif mode == "post-unapproved":
        detail = (f"posting is not approved for this run — set {autopilot.POST_ENV}=1 "
                  "on the serve command (per run, never in .env)")
    elif mode == "killed":
        detail = "autopilot kill switch is on (data/autopilot.off)"
    else:
        detail = f"posting mode: {mode}"
    return {"id": hold_id, "posted": False, "mode": mode, "detail": detail}


# --- evals ------------------------------------------------------------------

@router.get("/evals/golden")
def evals_golden(account_id: int = Depends(auth.current_account_id)):
    return {"items": evalstore.list_golden()}


class GoldenBody(BaseModel):
    query: str
    relevant: list[str]
    source: str = "probe"


@router.post("/evals/golden")
def evals_golden_add(body: GoldenBody, account_id: int = Depends(auth.current_account_id)):
    try:
        golden_id = evalstore.add_golden(body.query, body.relevant,
                                         source=body.source)
    except ValueError as e:
        return _error(400, "invalid_golden", str(e))
    return {"id": golden_id}


@router.delete("/evals/golden/{golden_id}")
def evals_golden_delete(golden_id: int, account_id: int = Depends(auth.current_account_id)):
    evalstore.delete_golden(golden_id)
    return {"deleted": golden_id}


@router.get("/evals/runs")
def evals_runs(account_id: int = Depends(auth.current_account_id)):
    return {"items": evalstore.list_runs()}


@router.get("/evals/runs/{run_id}")
def evals_run_detail(run_id: int, account_id: int = Depends(auth.current_account_id)):
    run = evalstore.get_run(run_id)
    if run is None:
        return _error(404, "not_found", "no such run")
    return run


class EvalRunBody(BaseModel):
    label: Optional[str] = None


@router.post("/evals/run")
def evals_run(body: EvalRunBody, account_id: int = Depends(auth.current_account_id)):
    """Compare one-shot retrieval with the complete CRAG retry path.

    Every metric is computed server-side and stored with the exact golden
    set, model, threshold, and reference-library identity that produced it.
    """
    golden = evalstore.list_golden()
    if not golden:
        return _error(400, "empty_golden", "the golden set is empty")
    api_key = _gemini_key()
    if not (api_key and _rag_reachable()):
        return _error(503, "evals_unavailable",
                      "needs the RAG store and GEMINI_API_KEY")
    cases = [{"query": g["query"], "relevant": g["relevant"]} for g in golden]
    # the view already appends "· n queries · k=…", so the default label
    # stays bare to avoid stuttering
    label = (body.label or "").strip() or "run"
    k = _eval_k()

    def work(job):
        conn = rag.connect()
        try:
            client = rag.make_client()
            times: list[float] = []
            done = {"n": 0}

            total_steps = len(cases) * 2

            def base_retrieve(query_text, k):
                jobs.check_cancelled(job)
                started = time.perf_counter()
                hits = rag.query(query_text, client, conn, k=k)
                times.append((time.perf_counter() - started) * 1000)
                done["n"] += 1
                jobs.progress(job, done["n"] / total_steps,
                              f"{done['n']}/{total_steps} retrieval checks")
                return hits

            def crag_retrieve(query_text, k):
                jobs.check_cancelled(job)
                started = time.perf_counter()
                outcome = crag.retrieve_with_crag(
                    query_text, client, CRAG_REWRITE_MODEL, k=k,
                    threshold=settings.grade_threshold(),
                    record_telemetry=False,
                )
                times.append((time.perf_counter() - started) * 1000)
                done["n"] += 1
                jobs.progress(job, done["n"] / total_steps,
                              f"{done['n']}/{total_steps} retrieval checks")
                return outcome

            result = rag_eval.evaluate_comparison(
                cases, base_retrieve, crag_retrieve, k=k)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        p50 = int(statistics.median(times)) if times else None
        library = rag.reference_library_identity()
        set_fingerprint = rag_eval.case_set_fingerprint(cases)
        result.update({
            "mode": "comparison",
            "library_count": library["count"],
            "library_fingerprint": library["fingerprint"],
            "set_fingerprint": set_fingerprint,
        })
        threshold = settings.grade_threshold()
        run_id = evalstore.save_run(
            label, result, p50_ms=p50,
            config={
                "k": k, "model": rag.EMBED_MODEL,
                "rewrite_model": CRAG_REWRITE_MODEL, "mode": "comparison",
                "threshold": threshold,
                "library_count": library["count"],
                "library_fingerprint": library["fingerprint"],
                "set_fingerprint": set_fingerprint,
            })
        return {"ref_id": run_id,
                "detail": f"CRAG hit@{k} {result['hit_rate']:.2f} · "
                          f"base {result['base_hit_rate']:.2f} · "
                          f"re-query {result['requery_rate']:.0%}"}

    job = jobs.start("eval", f"eval · {len(cases)} queries", work, account_id=account_id,
                     cancellable=True)
    return {"job_id": job["id"]}


# --- analytics --------------------------------------------------------------

def _brand_rows(brand: Optional[str], account_id: Optional[int] = None) -> list:
    rows = db.latest_metrics_by_video(account_id=account_id)
    if brand in preprod.BRANDS:
        # NULL-inclusive, same as /analytics: untagged legacy videos stay.
        rows = [r for r in rows if r.get("brand") in (None, brand)]
    return rows


@router.get("/analytics/summary")
def analytics_summary(brand: Optional[str] = None, platform: Optional[str] = None,
        account_id: int = Depends(auth.current_account_id)):
    rows = _brand_rows(brand, account_id)
    counts = {"all": len(rows)}
    for p in db.PLATFORMS:
        counts[p] = sum(1 for r in rows if r["platform"] == p)
    if platform in db.PLATFORMS:
        rows = [r for r in rows if r["platform"] == platform]
    return {
        "tiles": {
            "views": sum(r["views"] or 0 for r in rows),
            "likes": sum(r["likes"] or 0 for r in rows),
            "comments": sum(r["comments"] or 0 for r in rows),
            "saves": sum(r["saves"] or 0 for r in rows),
            "videos": len(rows),
        },
        "platform_counts": counts,
    }


@router.get("/analytics/posts")
def analytics_posts(brand: Optional[str] = None, platform: Optional[str] = None,
        account_id: int = Depends(auth.current_account_id)):
    rows = _brand_rows(brand, account_id)
    if platform in db.PLATFORMS:
        rows = [r for r in rows if r["platform"] == platform]
    ranked = sorted(rows, key=lambda r: (r["views"] is None, -(r["views"] or 0)))
    max_views = next((r["views"] for r in ranked if r["views"] is not None), 0)
    return {"items": [
        {**r, "pct": round((r["views"] or 0) / max_views * 100, 1) if max_views else 0}
        for r in ranked
    ]}


@router.get("/costs")
def costs_summary(runs: int = 14, account_id: int = Depends(auth.current_account_id)):
    """The cost tracker's numbers for this account (src/costs.summary):
    cost per kept clip per tool, cost per stage per night from the LLM
    meter, wasted spend, and today against the caps. Estimates."""
    from src import costs
    return costs.summary(account_id=account_id,
                         runs=max(1, min(int(runs), 90)))


@router.get("/analytics/accounts")
def analytics_accounts(account_id: int = Depends(auth.current_account_id)):
    """What is actually connected: platform key presence (real config, not
    a wish list) plus the autonomy channels and their levels."""
    return {
        "apis": [
            {"platform": "youtube", "label": "YouTube Data API v3",
             "configured": bool(os.environ.get("YOUTUBE_API_KEY"))},
            {"platform": "instagram", "label": "Instagram Graph API",
             "configured": bool(instagram.access_token())},
        ],
        "channels": autonomy.list_channels(),
    }


@router.post("/videos/{video_id}/refresh")
def video_refresh(video_id: int, account_id: int = Depends(auth.current_account_id)):
    video = db.get_video(video_id, account_id=account_id)
    if video is None:
        return _error(404, "not_found", "video not found")
    if video["platform"] == "instagram":
        result = instagram.refresh_metrics_for_video(
            video, token=instagram.access_token(), db_path=None)
    else:
        result = youtube.refresh_metrics_for_video(
            video, api_key=os.environ.get("YOUTUBE_API_KEY"), db_path=None)
    if not result.get("ok"):
        return _error(502, "refresh_failed", str(result.get("error")))
    return result


# --- workflows --------------------------------------------------------------
# The node-graph canvas. A workflow row is LiteGraph's serialize() JSON
# stored whole; execution (Run all) walks it server-side in topological
# order through app/workflow_runner.py, one node at a time -- billed
# calls are sequential on purpose. The Generate node goes through
# runway.generate_from_prompt. Its spend gate still lives inside
# generate_video so this surface cannot become a second route that
# spends around it -- what satisfies the gate here is the person running
# the canvas (approved=True), not an environment variable.

class WorkflowBody(BaseModel):
    name: Optional[str] = None
    graph: Optional[dict] = None
    brand: Optional[str] = None


@router.get("/workflows")
def workflows_list(brand: Optional[str] = None,
                   account_id: int = Depends(auth.current_account_id)):
    """This account's canvases. `brand` filters inside the tenant --
    account_id is ownership, brand is the label the pill filters by."""
    return {"items": workflows.list_workflows(brand=brand or None,
                                              account_id=account_id)}


@router.post("/workflows")
def workflows_create(body: WorkflowBody, request: Request,
                     account_id: int = Depends(auth.current_account_id)):
    brand = body.brand if body.brand in preprod.BRANDS else (
        request.cookies.get("brand")
        if request.cookies.get("brand") in preprod.BRANDS else "antihero")
    workflow_id = workflows.create_workflow(
        body.name or "Untitled workflow", body.graph or {},
        brand=brand, account_id=account_id)
    return {"id": workflow_id}


# the exec routes sit above /workflows/{workflow_id} so "exec" is never
# read as an id -- the /jobs/stream registration-order rule.

class GroundBody(BaseModel):
    spark: str = ""


@router.post("/workflows/exec/ground")
def workflow_exec_ground(body: GroundBody, account_id: int = Depends(auth.current_account_id)):
    """The Ground in References node: the existing RAG-grounding step
    (shootgen.reference_block) as a visible, wireable call. Degrades to
    "" with the store down, same as everywhere else."""
    from src import shootgen

    references = shootgen.reference_block(
        spark=body.spark.strip() or None, db_path=None)
    return {"references": references}


class EnhanceBody(BaseModel):
    system: str = ""
    user: str = ""
    images: list[str] = []
    references: str = ""
    ground: bool = False   # pull the RAG block server-side (Director chain)


@router.post("/workflows/exec/enhance")
def workflow_exec_enhance(body: EnhanceBody, account_id: int = Depends(auth.current_account_id)):
    """The Gemini 2.5 Flash enhance node's own Run: one billed Gemini
    call through generate_with_retry, images riding as vision input and
    the Ground node's references folded in as grounding. A job, so the
    canvas lights the node from the same SSE feed everything uses."""
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        from google import genai

        from src import shootgen
        references = body.references
        if body.ground and not references:
            jobs.progress(job, 0.15, "grounding in references")
            references = shootgen.reference_block(
                spark=body.user.strip() or None, db_path=None)
        jobs.progress(job, 0.3, "enhancing prompt")
        text = workflow_runner.enhance(
            body.system, body.user, images=body.images or None,
            references=references,
            gemini_client=genai.Client(api_key=api_key),
            resolve_photo=_resolve_asset_photo)
        return {"detail": text[:80], "output": text}

    job = jobs.start("enhance", f"enhance · {(body.user or body.system)[:50]}", work,
                     account_id=account_id)
    return {"job_id": job["id"]}


class WfGenerateBody(BaseModel):
    prompt: str
    image: Optional[str] = None
    # The canvas posts the node's WHOLE reference list as `images`
    # (workflows.js referenceUrls), the same shape the enhance node
    # sends. Declaring only `image` meant pydantic dropped it without a
    # word, so a per-node Run on Nano Banana or Generate rendered with
    # no references at all -- the face, the jacket and the bike arrived
    # as a sentence and never as pixels (2026-08-28). `image` stays for
    # any caller that sends one.
    images: Optional[list[str]] = None
    # Optional: which renderer to spend on. Unset -- the canvas today --
    # means whatever this account can render (providers.renderer_for).
    provider: Optional[str] = None
    model: Optional[str] = None
    # Optional: the shot this node belongs to. Named, the render checks
    # the concept is this account's BEFORE any job starts, falls back to
    # the shot's own refs when the node posts none, and attaches its
    # output to the shot when it finishes -- a render that completes
    # after the browser closed still lands where the Director expects it.
    concept_id: Optional[int] = None
    shot_n: Optional[int] = None

    def reference_urls(self) -> list[str]:
        urls, seen = [], set()
        for url in [*(self.images or []), self.image]:
            if isinstance(url, str) and url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls


_NO_SUCH_SHOT = object()


def _exec_shot(body: "WfGenerateBody", account_id: Optional[int]):
    """The shot a per-node render belongs to: None when the node is
    free-standing (no concept named), the shot dict when it is this
    account's, and _NO_SUCH_SHOT when the concept is not -- someone
    else's concept is a 404, the same as a missing one, checked before a
    single billed call. A named concept whose shot number is wrong
    still runs free-standing rather than failing a render over a
    stale n; there is just nothing to attach to."""
    if body.concept_id is None:
        return None
    concept = preprod.get_concept(body.concept_id, account_id=account_id)
    if concept is None:
        return _NO_SUCH_SHOT
    return next((s for s in (concept.get("shots") or [])
                 if s.get("n") == body.shot_n), None)


def _shot_refs(shot) -> list:
    """The references stored on the shot -- read at run time, the rule
    workflow_runner.shot_reference_urls states -- as the fallback when
    the node posted none."""
    if not shot:
        return []
    return [str(u) for u in (shot.get("refs") or []) if u]


@router.post("/workflows/exec/generate")
def workflow_exec_generate(body: WfGenerateBody, account_id: int = Depends(auth.current_account_id)):
    """The Generate node's own Run: one clip from a free-standing prompt
    + optional reference, on WHATEVER RENDERER THIS ACCOUNT CAN USE
    (2026-09-11) -- providers.renderer_for, the same resolver the Queue
    uses, so an account with a Higgsfield key and no Runway key renders
    instead of being told about a key it never meant to hold. Billed and
    capped; the click is the spend approval (2026-09-09) -- the gate
    still lives inside each adapter's generate_video."""
    shot = _exec_shot(body, account_id)
    if shot is _NO_SUCH_SHOT:
        return _error(404, "not_found", "no such concept")
    pick = providers.renderer_for(account_id, body.provider, body.model,
                                  needs="generate_from_prompt")
    if pick is None:
        return _error(503, "renderer_unavailable",
                      "no video renderer key is available for this account — "
                      "add a Runway, Higgsfield or fal key")
    label = providers.RENDER_LABELS.get(pick["provider"], pick["provider"])

    def work(job):
        jobs.progress(job, 0.2, f"rendering via {label} ({pick['model']})")
        # Every adapter anchors on exactly ONE frame, so of the references
        # the node carries only the first is usable -- same rule as the
        # graph runner's Generate branch.
        urls = body.reference_urls() or _shot_refs(shot)
        result = workflow_runner.render_generate_node(
            pick, body.prompt, urls[0] if urls else None,
            resolve_photo=_resolve_asset_photo, db_path=None,
            account_id=account_id)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "render failed")
        if shot is not None:
            preprod.set_shot_media_url(body.concept_id, body.shot_n,
                                       result["media_url"], account_id=account_id)
        return {"detail": f"clip rendered via {label} ({pick['model']})",
                "output": result["media_url"]}

    job = jobs.start("render", f"{label.lower()} · {body.prompt[:50]}", work,
                     account_id=account_id)
    return {"job_id": job["id"]}


@router.post("/workflows/exec/nano")
def workflow_exec_nano(body: WfGenerateBody, account_id: int = Depends(auth.current_account_id)):
    """The Nano Banana node's own Run: one Gemini image render from a
    free-standing prompt + optional reference. Billed on the same
    GEMINI_API_KEY as everything else, capped by NANO_DAILY_CAP inside
    generate_from_prompt -- no separate spend gate, an image costs
    cents where a Runway render burns credits."""
    from src import nano_banana

    shot = _exec_shot(body, account_id)
    if shot is _NO_SUCH_SHOT:
        return _error(404, "not_found", "no such concept")
    if not nano_banana.has_key():
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        jobs.progress(job, 0.2, "rendering via Nano Banana")
        # every reference, not just one: the face AND the jacket AND the
        # bike, matching the graph runner's Nano branch
        reference = [
            data for data in (
                imagery.image_bytes_for_gemini(
                    url, resolve_photo=_resolve_asset_photo)
                for url in (body.reference_urls() or _shot_refs(shot)))
            if data
        ]
        result = nano_banana.generate_from_prompt(
            body.prompt, reference_image=reference, db_path=None)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "render failed")
        if shot is not None:
            preprod.set_shot_reference_image(body.concept_id, body.shot_n,
                                             result["media_url"], account_id=account_id)
        return {"detail": "image rendered", "output": result["media_url"]}

    job = jobs.start("render", f"nano · {body.prompt[:50]}", work, account_id=account_id)
    return {"job_id": job["id"]}


@router.get("/workflows/{workflow_id}")
def workflows_get(workflow_id: int, account_id: int = Depends(auth.current_account_id)):
    workflow = workflows.get_workflow(workflow_id, account_id=account_id)
    if workflow is None:
        return _error(404, "not_found", "no such workflow")
    return workflow


@router.put("/workflows/{workflow_id}")
def workflows_update(workflow_id: int, body: WorkflowBody,
                     account_id: int = Depends(auth.current_account_id)):
    if not workflows.update_workflow(workflow_id, name=body.name,
                                     graph=body.graph,
                                     account_id=account_id):
        return _error(404, "not_found", "no such workflow")
    return {"id": workflow_id}


@router.delete("/workflows/{workflow_id}")
def workflows_delete(workflow_id: int, account_id: int = Depends(auth.current_account_id)):
    if not workflows.delete_workflow(workflow_id, account_id=account_id):
        return _error(404, "not_found", "no such workflow")
    return {"deleted": workflow_id}


@router.post("/workflows/{workflow_id}/run")
def workflows_run(workflow_id: int, account_id: int = Depends(auth.current_account_id)):
    """Run all: topological order over the SAVED graph (the client saves
    before it runs), sequential, every node's state pushed over the jobs
    SSE feed so the canvas lights up as nodes complete."""
    workflow = workflows.get_workflow(workflow_id, account_id=account_id)
    if workflow is None:
        return _error(404, "not_found", "no such workflow")
    graph = workflow.get("graph") or {}
    if not graph.get("nodes"):
        return _error(400, "empty_graph", "the workflow has no nodes to run")
    api_key = _gemini_key()

    def work(job):
        gemini_client = None
        if api_key:
            from google import genai
            gemini_client = genai.Client(api_key=api_key)

        def emit(states, fraction, detail):
            jobs.update(job["id"], node_states=states)
            jobs.progress(job, fraction, detail)

        result = workflow_runner.execute_graph(
            graph, gemini_client=gemini_client,
            resolve_photo=_resolve_asset_photo, db_path=None,
            emit=emit, check_cancelled=lambda: jobs.check_cancelled(job),
            account_id=account_id)
        jobs.update(job["id"], node_states=result["nodes"])
        failed = [s for s in result["nodes"].values() if s["status"] == "failed"]
        if failed:
            raise RuntimeError(f"{len(failed)} node(s) failed — "
                               + (failed[0].get("error") or "see the board"))
        done = sum(1 for s in result["nodes"].values() if s["status"] == "done")
        return {"ref_id": workflow_id, "detail": f"{done} node(s) executed"}

    job = jobs.start("workflow", f"workflow · {workflow['name']}", work,
                     cancellable=True, account_id=account_id)
    return {"job_id": job["id"]}


# --- jobs -------------------------------------------------------------------

@router.get("/jobs")
def jobs_list(active: Optional[bool] = None,
              account_id: int = Depends(auth.current_account_id)):
    return {"items": jobs.list_jobs(active=active, account_id=account_id)}


@router.get("/jobs/stream")
async def jobs_stream(account_id: int = Depends(auth.current_account_id)):
    """SSE. The job rail, the queue view, and the pipeline cards all
    subscribe here -- the only push channel, nothing polls. Registered
    before /jobs/{job_id} so 'stream' isn't captured as an id.

    The registry publishes every job to every subscriber; the filter
    is here, at the one place the account is known, so a subscriber
    only ever sees its own."""
    queue = jobs.subscribe()

    async def gen():
        import asyncio
        try:
            # current state first, so a fresh subscriber isn't blind
            for job in jobs.list_jobs(account_id=account_id):
                yield f"event: job\ndata: {json.dumps(job)}\n\n"
            while True:
                try:
                    job = await asyncio.wait_for(queue.get(), timeout=25)
                    if not jobs.owned_by(job, account_id):
                        continue
                    yield f"event: job\ndata: {json.dumps(job)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            jobs.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, account_id: int = Depends(auth.current_account_id)):
    job = jobs.get(job_id, account_id=account_id)
    if job is None:
        return _error(404, "not_found", "no such job")
    return job


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: int, account_id: int = Depends(auth.current_account_id)):
    job = jobs.cancel(job_id, account_id=account_id)
    if job is None:
        return _error(404, "not_found", "no such job")
    return jobs.snapshot(job)


@router.delete("/jobs/{job_id}")
def job_clear(job_id: int, account_id: int = Depends(auth.current_account_id)):
    removed = jobs.remove(job_id, account_id=account_id)
    if removed is None:
        return _error(404, "not_found", "no such job")
    if not removed:
        return _error(409, "not_finished", "only finished jobs can be cleared")
    return {"deleted": job_id}
