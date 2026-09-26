"""What a scene actually needs photographs OF (2026-09-24, from the
invideo Referencer read — see claude/invideo_referencer_vs_scout).

Until today one spark produced ONE search: `scout.look_query` keeps the
concrete nouns off the whole story and hands them to every lane. That
finds a mood and nothing else, which is why a scene can come back with
three pictures of the same wet street and no idea what the jacket looks
like. The Reference Map is the missing step: read the scene, list every
visual question in it, and say which ones the text already answers.

Three rules, all in code rather than in the prompt:

- **A face is never hunted on the web.** A need whose role is `face`
  comes back with `source="elements"`: identity is the character bank's
  job (see likeness.md — the anchor frame decides whether the clip is
  Michael or a stranger), and a stranger's face off an image lane is the
  most expensive wrong reference this pipeline can attach.
- **A query is surfaces, never plot.** Whatever the model writes is put
  through `scout.look_query` when it runs long: an image lane indexes
  light and materials, and a sentence of story returns nothing — which
  looks exactly like a lane that is dark.
- **It never raises and it always answers.** No key, no client, an
  unreadable verdict: the deterministic split (one `mood` need off
  `look_query`) is used and `planner` says `split`, the
  `timeline.plan` pattern. A map that can fail a pass would be worse
  than the single query it replaces.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PROMPT_PATH = PROMPTS_DIR / "reference_needs.txt"

# The departments, in Mike's vocabulary rather than a film crew's. Order
# is deliberate: it is the order a card shows them in, and `face` first
# because identity is what a clip is judged on.
ROLES = ("face", "wardrobe", "place", "light", "prop", "texture", "mood")

# Everything except identity. `face` is the character bank's, always.
WEB_ROLES = tuple(r for r in ROLES if r != "face")

MAX_NEEDS = 6          # a contact sheet per need; more than six is a chore
MAX_QUERY_WORDS = 12   # scout.look_query's own ceiling


def anti_path(brand: str) -> Path:
    return PROMPTS_DIR / f"anti_references_{(brand or '').strip().lower()}.txt"


def anti_references(brand: str) -> list[str]:
    """What this brand must NOT look like — one line each, '#' comments.

    Their Referencer asks the creator for anti-references before every
    hunt, and it is the cheapest quality lever in the whole design: a
    negative list filters candidates as hard as the positive one, and
    this repo has never had one at the image level. A missing file means
    no anti-references, never an error.
    """
    try:
        raw = anti_path(brand).read_text()
    except Exception:
        return []
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _clean_query(text: str) -> str:
    from . import scout
    words = (text or "").split()
    if len(words) > MAX_QUERY_WORDS:
        return scout.look_query(text)
    return " ".join(words)


def _text(value) -> str:
    """`gemini_utils.generate_with_retry` returns the answer TEXT unless
    raw=True; a response object only comes back from the raw path. Both
    shapes are accepted here because reading `.text` off a string is the
    silent empty-answer bug this cost once already."""
    if isinstance(value, str):
        return value
    return getattr(value, "text", "") or ""


def _need(role: str, query: str, want: str = "", specified: bool = False) -> Optional[dict]:
    role = (role or "").strip().lower()
    query = _clean_query(query)
    if role not in ROLES or not query:
        return None
    return {
        "role": role,
        "query": query,
        "want": " ".join((want or "").split())[:200],
        "specified": bool(specified),
        # The one routing decision this module makes, and code makes it:
        # a model that answers source="web" for a face does not get to.
        "source": "elements" if role == "face" else "web",
    }


def fallback(text: str) -> list[dict]:
    """The deterministic map: today's single query, labelled honestly."""
    from . import scout
    query = scout.look_query(text or "")
    need = _need("mood", query, want="the whole scene, as one search")
    return [need] if need else []


def parse(answer: str) -> list[dict]:
    """Model JSON -> needs. Anything unreadable is [] and the caller
    falls back; anything readable is filtered by the rules above."""
    import json

    from .gemini_utils import strip_fences

    try:
        data = json.loads(strip_fences(answer or ""))
    except Exception:
        return []
    rows = data.get("needs") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        need = _need(row.get("role", ""), row.get("query", ""),
                     row.get("want", ""), row.get("specified", False))
        if not need:
            continue
        key = (need["role"], need["query"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(need)
        if len(out) >= MAX_NEEDS:
            break
    return out


def build_prompt(text: str, *, look: str = "", anti=()) -> str:
    template = PROMPT_PATH.read_text()
    anti_block = "\n".join(f"- {line}" for line in anti) or "- (none given)"
    return template.format(
        scene=(text or "").strip(),
        roles=", ".join(ROLES),
        look=(look or "").strip() or "(no look file for this brand)",
        anti=anti_block,
        count=MAX_NEEDS,
    )


def plan(text: str, *, brand: str = "", client=None, model: str = "",
         look: str = "", anti=None, account_id=None) -> dict:
    """The Reference Map for one scene or spark.

    Returns {"ok", "needs", "planner", "note"}. `planner` is "model" or
    "split"; `ok` False with needs still filled is the honest shape when
    the call failed and the deterministic map stood in.
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "needs": [], "planner": "split",
                "note": "nothing to read"}
    if anti is None:
        anti = anti_references(brand)
    if not look:
        try:
            from . import looks
            look = looks.look_block(brand)
        except Exception:
            look = ""
    if client is None:
        try:
            from . import gemini_utils
            client = gemini_utils.client_for(account_id)
        except Exception as e:
            return {"ok": False, "needs": fallback(text), "planner": "split",
                    "note": f"no model client: {e}"}
    if not model:
        from . import gemini_utils
        model = gemini_utils.FAST_MODEL
    try:
        from . import gemini_utils
        resp = gemini_utils.generate_with_retry(
            client, model, [build_prompt(text, look=look, anti=anti)],
            stage="reference_map", account_id=account_id)
        needs = parse(_text(resp))
    except Exception as e:
        return {"ok": False, "needs": fallback(text), "planner": "split",
                "note": f"planner failed: {e}"}
    if not needs:
        return {"ok": False, "needs": fallback(text), "planner": "split",
                "note": "unreadable map"}
    return {"ok": True, "needs": needs, "planner": "model",
            "note": f"{len(needs)} need(s)"}


def web_needs(needs) -> list[dict]:
    """The needs an image lane may answer. A face is not one of them."""
    return [n for n in (needs or []) if n.get("source") == "web"]


def open_needs(needs) -> list[dict]:
    """Under-specified needs first — their Reference Map's own split:
    what the text already answers needs a photograph less badly than
    what it leaves open."""
    return sorted(web_needs(needs), key=lambda n: bool(n.get("specified")))
