"""The assistant's brain: what makes a Guide turn reason, not just chat (2026-09-26).

Mike: "the agent is supposed to be intelligent, how would it come up with
reasoning and responses like invideo's" -> "go ahead, mimic the brain with
what I have".

invideo's agent is not one clever model. Read off their app (claude/
invideo_referencer_vs_scout_2026-09-24.md, guide_brain_tiers_2026-09-18.md),
it is five things wrapped around an ordinary frontier model:

1. a PLAYBOOK per step -- a markdown file saying what to ask, what to do
   and what done looks like, with a <=3 question intake;
2. MEMORY -- the project and what is already decided, so it never asks
   twice;
3. TOOLS -- it acts (searches, looks, generates) instead of only talking;
4. EYES -- a vision pass over what it found before you see it;
5. a bigger model on the steps that write, a cheap one on the chatter.

Every one of those already exists in this repo under another name. This
module is the wiring, and nothing here is a new capability:

| invideo            | here                                                    |
|--------------------|---------------------------------------------------------|
| playbook per step  | prompts/stages/<stage>.md (our words, not theirs)       |
| memory             | the brand's look + anti-reference list + the board's    |
|                    | picks / passes (taste_judge.gather_signals, the ONE     |
|                    | "what does he like" reader -- taste_signal.md)          |
| tools              | guide_tools' board tools + find_references here         |
| eyes               | refcheck looks at every frame a hunt brings back        |
| checking loop      | story_judge grades each direction before it is shown    |
| tiers              | gemini_utils.BRAINS, picked per step when set to "auto" |

The rules that do not move, all inherited:
- nothing here spends. find_references banks NOTHING; keep_references is a
  WRITE tool, so it only ever runs on a person's click, and what it does is
  copy frames into this install's own /refs bin (no credits).
- ids, never URLs. The model sees candidate ids and reasons; the URLs stay
  server-side (imagesearch.remember/get), exactly as images_for works.
- a face is never hunted on the web (reference_needs routes it to Elements).
- nothing here raises into a turn: a dead lane, a missing key, a failed
  judge degrade the answer and say so.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
STAGES_DIR = ROOT / "prompts" / "stages"

# The steps, in order. The assistant REPORTS which one the conversation is
# on; it does not own a project table yet (that is the next build block).
STAGES = ("brief", "story", "cast", "references", "shots", "stills", "clips")

# How it talks. Three presets and nothing free-text, on purpose: a
# personality box a user types into is a door straight into this system
# prompt (spec, "Honest notes").
TONES = {
    "direct": "Talk straight: short sentences, the recommendation first, no filler or cheerleading.",
    "friendly": "Talk warmly and plainly, like a collaborator who is glad to be here -- still brief.",
    "hype": "Talk with energy -- punchy, confident, a little swagger -- but never at the cost of a clear next step.",
}
DEFAULT_TONE = "direct"
DEFAULT_NAME = "Guide"

# The steps whose turn WRITES something a person keeps (a story, a shot
# plan). "auto" puts those on the reasoning tier and everything else --
# intake, chatter, reading the board -- on fast. invideo's Lite/Pro/Ultra
# is the same split sold as a menu.
WRITING_STAGES = ("story", "shots")
_WRITE_ASK = re.compile(
    r"(?i)\b(write|draft|rewrite|pitch|brief|story|stories|directions?|script|shot ?list|plan the shots)\b")

# find_references budget for ONE chat turn -- smaller than a page hunt
# (reference_hunt.NEEDS_PER_HUNT = 4) because the person is waiting on it.
CHAT_NEEDS = 3
CHAT_CANDIDATES = 6
CHAT_KEEPERS = 3
MAX_KEEP = 12            # reference_cap.md: Create takes up to 12 images


# --- persona -----------------------------------------------------------------

_NAME_OK = re.compile(r"[^A-Za-z0-9 '\-]")


def clean_name(name) -> str:
    """A person's name for their assistant, safe to put in a prompt:
    letters, digits, spaces, apostrophes and hyphens, 24 characters."""
    name = _NAME_OK.sub("", str(name or "")).strip()
    name = " ".join(name.split())[:24].strip()
    return name or DEFAULT_NAME


def clean_tone(tone) -> str:
    tone = str(tone or "").strip().lower()
    return tone if tone in TONES else DEFAULT_TONE


def clean_stage(stage) -> str:
    stage = str(stage or "").strip().lower()
    return stage if stage in STAGES else ""


def clean_page(page) -> str:
    """The studio route the pill is floating over, e.g. "/studio/queue".
    Only the path shape survives -- it goes into a prompt."""
    page = str(page or "").strip()
    page = page.split("?", 1)[0].split("#", 1)[0]
    if not re.fullmatch(r"/[A-Za-z0-9/_\-]{0,80}", page or "-"):
        return ""
    return page


# --- playbooks ----------------------------------------------------------------

def playbook(stage: str) -> str:
    """The step's playbook text, or "" when there is none. Never raises."""
    stage = clean_stage(stage)
    if not stage:
        return ""
    try:
        return (STAGES_DIR / f"{stage}.md").read_text().strip()
    except OSError:
        return ""


# --- tiers --------------------------------------------------------------------

def pick_brain(requested, stage: str = "", last_message: str = "") -> str:
    """Which gemini_utils.BRAINS tier answers.

    An explicit "fast" / "reasoning" from the pill always wins -- the
    person's choice is the person's. "auto" (or nothing) decides from the
    step and the ask: a writing step, or a message asking for something
    to be written, gets reasoning; the rest gets fast.
    """
    from . import gemini_utils

    requested = str(requested or "").strip().lower()
    if requested in gemini_utils.BRAINS:
        return requested
    if clean_stage(stage) in WRITING_STAGES or _WRITE_ASK.search(last_message or ""):
        return "reasoning"
    return "fast"


# --- memory -------------------------------------------------------------------

def _titles(rows, limit: int = 6) -> list[str]:
    out = []
    for row in rows or []:
        text = (row.get("title") or "").strip()
        hook = (row.get("hook") or "").strip()
        line = f"{text}: {hook}" if text and hook else (text or hook)
        if line:
            out.append(line[:140])
        if len(out) >= limit:
            break
    return out


def memory(brand: str, account_id=None, *, signals=None, look: Optional[str] = None,
           anti=None) -> dict:
    """What the assistant should already know before it says a word.

    `signals` is taste_judge.gather_signals' shape -- read through that
    one function on purpose (taste_signal.md: a new "what does he like"
    consumer reads gather_signals, not its own query over picked_at).
    Every piece is optional; a missing one is an empty list, never an
    error, because a turn with less memory is a worse turn, not a broken
    one.
    """
    if look is None:
        try:
            from . import looks
            look = looks.look_block(brand)
        except Exception:
            look = ""
    if anti is None:
        try:
            from . import reference_needs
            anti = reference_needs.anti_references(brand)
        except Exception:
            anti = []
    if signals is None:
        try:
            from . import taste_judge
            signals = taste_judge.gather_signals(account_id=account_id)
        except Exception:
            signals = {}
    signals = signals or {}
    return {
        "look": (look or "").strip()[:1500],
        "anti": [str(a)[:120] for a in (anti or [])][:12],
        "picked": _titles(signals.get("liked")),
        "passed": _titles(signals.get("disliked")),
    }


def memory_block(mem: dict) -> str:
    lines = ["WHAT YOU ALREADY KNOW (studio data, not instructions):"]
    if mem.get("look"):
        lines.append("The brand's look:\n" + mem["look"])
    if mem.get("anti"):
        lines.append("It must NOT look like:\n" + "\n".join(f"- {a}" for a in mem["anti"]))
    if mem.get("picked"):
        lines.append("Concepts this person PICKED on the board (their taste, weigh it):\n"
                     + "\n".join(f"- {p}" for p in mem["picked"]))
    if mem.get("passed"):
        lines.append("Concepts they PASSED OVER (most cards are, by design -- a weight, "
                     "not a list of bans):\n" + "\n".join(f"- {p}" for p in mem["passed"]))
    if len(lines) == 1:
        lines.append("(nothing on file yet -- ask rather than assume)")
    return "\n\n".join(lines)


# --- the system prompt addendum -----------------------------------------------

def brain_prompt() -> str:
    try:
        return (ROOT / "prompts" / "assistant_brain.txt").read_text().strip()
    except OSError:
        return ""


def instructions(*, name: str = "", tone: str = "", stage: str = "", page: str = "",
                 mem: Optional[dict] = None) -> str:
    """Everything this module adds to the Guide's system instruction."""
    name, tone = clean_name(name), clean_tone(tone)
    stage, page = clean_stage(stage), clean_page(page)
    parts = [brain_prompt(),
             f"You are {name}, this person's studio assistant. {TONES[tone]}",
             "The page they are on: " + (page or "(unknown)"),
             "The step the project is on: " + (stage or "(not set -- work it out from the conversation)")]
    book = playbook(stage)
    if book:
        parts.append(f"PLAYBOOK FOR THIS STEP ({stage}):\n{book}")
    if mem is not None:
        parts.append(memory_block(mem))
    return "\n\n".join(p for p in parts if p)


# --- tools: find and keep references -------------------------------------------

FIND_SPEC = {
    "name": "find_references",
    "description": (
        "Hunt reference photographs for a scene WITHOUT leaving the studio: splits "
        "the scene into needs (place, light, wardrobe, mood, prop, texture), searches "
        "the image lanes for each, and LOOKS at every frame -- watermarks, subtitles, "
        "screenshots, collages and anything on the must-not list are rejected with a "
        "reason. Banks nothing and costs no credits; the person sees a contact sheet "
        "and keeps what they like. Faces are never hunted -- they come from Elements. "
        "Returns candidate ids (never URLs) with what each frame is good for."),
    "input_schema": {
        "type": "object",
        "properties": {
            "scene": {"type": "string",
                      "description": "The scene in plain words, as agreed so far."},
            "departments": {"type": "array", "items": {"type": "string"},
                            "description": "Optional subset of: place, light, wardrobe, "
                                           "mood, prop, texture."},
            "avoid": {"type": "array", "items": {"type": "string"},
                      "description": "What it must NOT look like, in the person's words."},
        },
        "required": ["scene"],
    },
    "write": False,
}

KEEP_SPEC = {
    "name": "keep_references",
    "description": (
        "Keep frames from a find_references contact sheet: copies them into the "
        "studio's own reference bin and attaches them to the composer. WRITE -- the "
        "person confirms on a card. Takes candidate_ids that came back from "
        "find_references in this conversation, never URLs."),
    "input_schema": {
        "type": "object",
        "properties": {"candidate_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["candidate_ids"],
    },
    "write": True,
}

LOCAL_READ = ("find_references",)
LOCAL_WRITE = ("keep_references",)
LOCAL_SPECS = (FIND_SPEC, KEEP_SPEC)
WRITE_LABELS = {"keep_references": "Keep these references and attach them to the composer"}


def _need_line(entry: dict) -> str:
    keep = ", ".join(f"{k['id']} ({(k.get('kept_for') or k.get('title') or '').strip()[:60]})"
                     for k in entry["keepers"]) or "none"
    rej = "; ".join(f"{r.get('why') or 'rejected'}" for r in entry["rejected"][:3])
    return (f"- {entry['role']} -- {entry['query']}: kept {keep}"
            + (f" | rejected: {rej}" if rej else "")
            + (f" | {entry['note']}" if entry.get("note") and not entry["keepers"] else ""))


def find_references(scene: str, *, brand: str = "", account_id=None,
                    departments=None, avoid=None, dsn=None, client=None,
                    plan=None, search=None, screen=None) -> dict:
    """A contact sheet for a scene that is not a banked spark yet.

    `reference_hunt.propose` hunts for a spark by id; a chat is usually
    about a scene nobody has banked, so this is the same three steps
    (map -> search -> look) over free text, with the bank step dropped
    entirely. Returns {"ok", "sheet", "note", "checked"}; `sheet` is one
    entry per need with `keepers` and `rejected` (each carrying `why`).
    Never raises.
    """
    from . import reference_needs

    scene = " ".join(str(scene or "").split())[:2000]
    if not scene:
        return {"ok": False, "sheet": [], "checked": True, "note": "no scene to hunt for"}
    anti = list(reference_needs.anti_references(brand)) + [
        " ".join(str(a).split())[:120] for a in (avoid or []) if str(a).strip()][:8]
    if plan is None:
        plan = reference_needs.plan
    if search is None:
        from .imagesearch import search
    if screen is None:
        from .refcheck import screen

    try:
        mapped = plan(scene, brand=brand, client=client, anti=anti, account_id=account_id)
    except Exception as e:                               # pragma: no cover - plan never raises
        return {"ok": False, "sheet": [], "checked": True, "note": f"could not read the scene: {e}"}
    needs = reference_needs.open_needs(mapped.get("needs") or [])
    wanted = {str(d).strip().lower() for d in (departments or []) if str(d).strip()}
    if wanted:
        needs = [n for n in needs if n.get("role") in wanted] or needs
    needs = needs[:CHAT_NEEDS]
    faces = [n for n in (mapped.get("needs") or []) if n.get("source") == "elements"]
    if not needs:
        return {"ok": False, "sheet": [], "checked": True, "faces": len(faces),
                "note": "nothing in this scene needs a photograph off the web"}

    sheet, unchecked = [], 0
    for need in needs:
        entry = {"role": need.get("role", ""), "query": need.get("query", ""),
                 "keepers": [], "rejected": [], "note": ""}
        try:
            candidates = []
            for query in _broader(need["query"]):
                candidates = search(query, brand, limit=CHAT_CANDIDATES, dsn=dsn)
                if candidates:
                    entry["query"] = query
                    break
        except Exception as e:
            entry["note"] = f"search failed: {e}"
            sheet.append(entry)
            continue
        if not candidates:
            entry["note"] = "no lane configured, or nothing matched"
            sheet.append(entry)
            continue
        try:
            looked = screen(candidates, need, brand=brand, client=client,
                            anti=anti, account_id=account_id)
        except Exception as e:
            looked = {"checked": False, "keepers": [], "rejected": [], "note": str(e)}
        if not looked.get("checked"):
            # reference_hunt's rule: a frame nobody looked at is not offered.
            unchecked += 1
            entry["note"] = f"not looked at -- {looked.get('note', '')}".strip(" -")
            sheet.append(entry)
            continue
        entry["keepers"] = [_public(k) for k in (looked.get("keepers") or [])[:CHAT_KEEPERS]]
        entry["rejected"] = [_public(r) for r in (looked.get("rejected") or [])]
        entry["note"] = looked.get("note", "")
        sheet.append(entry)

    kept = sum(len(e["keepers"]) for e in sheet)
    looked_at = kept + sum(len(e["rejected"]) for e in sheet)
    return {"ok": kept > 0, "sheet": sheet, "checked": unchecked == 0,
            "faces": len(faces),
            "note": (f"looked at {looked_at} frame(s), kept {kept} across {len(sheet)} need(s)"
                     + (f"; {unchecked} need(s) could not be looked at" if unchecked else ""))}


def _broader(query: str) -> list[str]:
    """The query, then shorter prefixes of it. The keyless floor lane
    (Openverse) matches every word, so the planner's eight-word queries
    ("empty weathered wood bar counter teal amber night") found nothing
    while their first four found six frames (measured live 2026-09-26).
    Longest first: a broader query is only asked when a narrower one
    came back empty."""
    words = " ".join(str(query or "").split()).split(" ")
    out = [" ".join(words)]
    for n in (4, 3):
        if len(words) > n:
            out.append(" ".join(words[:n]))
    return [q for q in out if q]


def _public(row: dict) -> dict:
    """The fields a contact-sheet card draws. `image_url` rides along for
    the THUMBNAIL (the browser has to load something); the model is never
    shown this dict -- it gets `sheet_for_model`."""
    return {"id": str(row.get("id") or ""), "image_url": row.get("image_url") or "",
            "source_url": row.get("source_url") or "", "source": row.get("source") or "",
            "title": (row.get("title") or "")[:120], "kept_for": (row.get("kept_for") or "")[:160],
            "why": (row.get("why") or "")[:160], "flags": list(row.get("flags") or [])[:6]}


def sheet_for_model(result: dict) -> str:
    """What the MODEL sees of a hunt: ids and reasons, no URLs."""
    lines = [result.get("note") or ""]
    if not any(e.get("keepers") for e in result.get("sheet") or []):
        # A live turn (2026-09-26) got a sheet with 0 frames back and
        # still told the person it had "pulled a contact sheet of the
        # keepers". The pill draws the sheet's own note beside the
        # message; this is the model's half of the same truth.
        lines.append("NO FRAMES WERE FOUND. Say so plainly; do not claim a contact sheet or keepers.")
    if result.get("faces"):
        lines.append(f"{result['faces']} face need(s) skipped -- faces come from Elements, never the web.")
    lines += [_need_line(e) for e in result.get("sheet") or []]
    return "\n".join(line for line in lines if line)


def keep_references(candidate_ids, *, account_id=None, dsn=None, get=None, fetch=None) -> dict:
    """Copy kept frames into /refs and hand back the paths the composer
    sends as `asset_photos` (asset_shelf.resolve_photo reads /refs/<sha>.jpg).

    The fabrication rule, again: an id this install never served is
    refused, not fetched. Returns {"kept": [...], "refused": [...]}.
    """
    if get is None:
        from .imagesearch import get
    if fetch is None:
        from .refbin import fetch
    kept, refused, seen = [], [], set()
    for cid in list(candidate_ids or [])[:MAX_KEEP]:
        cid = str(cid or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        candidate = get(cid, dsn=dsn) if dsn is not None else get(cid)
        if not candidate:
            refused.append({"id": cid, "error": "not an id a hunt served"})
            continue
        path = fetch(candidate.get("image_url") or "")
        if not path:
            refused.append({"id": cid, "error": "the image could not be fetched"})
            continue
        kept.append({"id": cid, "url": path, "source_url": candidate.get("source_url") or "",
                     "title": candidate.get("title") or ""})
    return {"kept": kept, "refused": refused}


def run_local(name: str, args: dict, *, brand: str = "", account_id=None,
              dsn=None, attachments: Optional[dict] = None) -> str:
    """Run one of this module's tools and return the text a model (or a
    card) sees. The full contact sheet goes into `attachments["sheet"]`
    for the reply -- the thread draws it; the model only reads ids."""
    args = dict(args or {})
    if name == "find_references":
        result = find_references(args.get("scene") or "", brand=brand, account_id=account_id,
                                 departments=args.get("departments"), avoid=args.get("avoid"),
                                 dsn=dsn)
        if attachments is not None:
            attachments["sheet"] = result
        return sheet_for_model(result)
    if name == "keep_references":
        return json.dumps(keep_references(args.get("candidate_ids"), account_id=account_id,
                                          dsn=dsn))
    raise ValueError(f"unknown local tool {name}")


# --- the checking step ------------------------------------------------------------

def check_directions(directions, *, client, model: str = "",
                     judge: Optional[Callable] = None) -> list[dict]:
    """Grade each proposed story direction with the independent judge
    before the person sees it -- a writer grading its own homework is the
    bug story_judge was built for. Best first; unscored ones keep their
    place after the scored. Never raises and never drops a direction: a
    judge that could not run leaves `score` None and says why.
    """
    directions = [dict(d) for d in (directions or [])]
    if not directions:
        return []
    if judge is None:
        from .story_judge import judge_spark as judge
    if not model:
        from . import gemini_utils
        model = gemini_utils.FAST_MODEL
    for d in directions:
        text = " ".join(x for x in (d.get("title"), d.get("logline")) if x)
        try:
            verdict = judge(text, d.get("turn") or "", client, model)
        except Exception as e:
            verdict = {"ok": False, "error": str(e)}
        if verdict.get("ok"):
            d["score"] = verdict.get("score")
            d["verdict"] = (verdict.get("verdict") or "")[:300]
        else:
            d["score"] = None
            d["verdict"] = ""
    scored = sorted([d for d in directions if d["score"] is not None],
                    key=lambda d: -float(d["score"]))
    return scored + [d for d in directions if d["score"] is None]
