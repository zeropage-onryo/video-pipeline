"""Global search: the studio's ⌘K palette asks ONE question (2026-10-08).

The gap list against LTX Studio and invideo (items 1 and 2): search lived
per page -- the Projects board, the Assets wall, the composer's element
shelf, the editor's footage index -- and the Queue and Elements had none,
so finding "the ridge scene" meant knowing which page it was on. This is
the one place that looks everywhere a person makes things, for ONE
account:

- projects   title and brief
- scenes     title, card line, logline, spark, and the scene PROMPT (shot 0
             -- the prompt is what a person remembers a scene by, and it
             is what "search prompts" means)
- elements   characters, props (and products) and places, by name and notes
- renders    the Assets wall, by the prompt that drew them
- cuts       the editor's projects, by title

An empty query answers what was touched last (projects and open scenes),
which is what the palette shows before anything is typed.

Matching is every whitespace-separated word, case-insensitively, anywhere
in the row's searchable text (ILIKE, with %/_/\\ escaped so a typed "50%"
is a literal). Rows are fetched newest first and then RANKED in Python: a
title that starts with the query, then a title holding every word, then
the rest -- so "ridge" puts "Ridge Line" above a scene that only mentions a
ridge in its prompt, without a full-text index this table size does not
need.

Everything here reads stored values only. A cover or a photo is returned as
the STORED string (the scene's still or first reference, a render's
media_url); minting a drawable thumbnail is the route's job (app/api.py),
because `src/` never imports `app/`. Every query is scoped by account_id in
the same SQL literal that names its table (tests/test_tenancy.py). Nothing
here spends or writes.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from . import db

GROUP_LIMIT = 5
MAX_GROUP_LIMIT = 20
RECENT_LIMIT = 4
# how many rows a group reads before ranking: enough that a title match
# further down the recency order still surfaces, small enough to stay lean
_FETCH = 40
_MAX_TOKENS = 6
_SNIPPET = 96


def tokens(q: Optional[str]) -> list[str]:
    """The words a query is matched on: lowercased, at most six, each at
    most 64 characters."""
    words = [w[:64] for w in (q or "").lower().split() if w.strip()]
    return words[:_MAX_TOKENS]


def _like(token: str) -> str:
    """A token as an ILIKE pattern that means the literal text."""
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _match(haystack: str, words: list[str]) -> tuple[str, list[str]]:
    """` AND <haystack> ILIKE %s` once per word. `haystack` is a SQL
    expression built here from fixed column names, never from input."""
    return "".join(f" AND {haystack} ILIKE %s" for _ in words), [_like(w) for w in words]


def _rank(rows: list[dict], words: list[str], q: str, title_key: str = "title") -> list[dict]:
    """Live rows before archived ones (a scene passed on, a project put
    away); within each, title-starts-with first, then all-words-in-title,
    then the rest -- each tier keeping the recency order the rows arrived
    in."""
    needle = q.strip().lower()

    def tier(row: dict) -> tuple[bool, int]:
        title = (row.get(title_key) or "").lower()
        if needle and title.startswith(needle):
            rank = 0
        elif words and all(w in title for w in words):
            rank = 1
        else:
            rank = 2
        return (bool(row.get("archived_at")), rank)

    return sorted(rows, key=tier)


def snippet(text: Optional[str], words: list[str], width: int = _SNIPPET) -> str:
    """The stretch of `text` around the first word that matched, on one
    line, with an ellipsis where it was cut."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    if len(flat) <= width:
        return flat
    low = flat.lower()
    hits = [low.find(w) for w in words if w and low.find(w) >= 0]
    at = min(hits) if hits else 0
    start = max(0, at - width // 3)
    end = min(len(flat), start + width)
    start = max(0, end - width)
    out = flat[start:end].strip()
    return ("…" if start > 0 else "") + out + ("…" if end < len(flat) else "")


def _first_line(text: Optional[str], width: int = 90) -> str:
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    return line if len(line) <= width else line[: width - 1].rstrip() + "…"


def _shot0(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


# --------------------------------------------------------------------------
# the groups
# --------------------------------------------------------------------------

def _projects(conn, account_id: Optional[int], words: list[str], q: str, limit: int) -> list[dict]:
    from . import projects

    if not db.table_exists(conn, "projects"):
        return []
    where, params = _match("(coalesce(title, '') || ' ' || coalesce(brief, ''))", words)
    if not words:
        where += " AND archived_at IS NULL"
    rows = conn.execute(
        "SELECT id, title, brief, archived_at FROM projects "
        "WHERE account_id IS NOT DISTINCT FROM %s" + where
        + " ORDER BY archived_at IS NOT NULL, updated_at DESC, id DESC LIMIT %s",
        (account_id, *params, _FETCH)).fetchall()
    rows = _rank([dict(r) for r in rows], words, q)[:limit]
    covers = projects._covers(conn, [r["id"] for r in rows], account_id) if rows else {}
    return [{"id": r["id"], "title": r["title"] or "Untitled project",
             "sub": _first_line(r.get("brief")),
             "archived": bool(r.get("archived_at")),
             "cover": covers.get(r["id"])}
            for r in rows]


_SCENE_TEXT = ("(coalesce(c.title, '') || ' ' || coalesce(c.card_line, '') || ' ' || "
               "coalesce(c.logline, '') || ' ' || coalesce(c.spark, '') || ' ' || "
               "coalesce((c.shots_json::jsonb) -> 0 ->> 'prompt', ''))")


def _scenes(conn, account_id: Optional[int], words: list[str], q: str, limit: int) -> list[dict]:
    from .projects import _shot_cover

    if not db.table_exists(conn, "shoot_concepts"):
        return []
    has_projects = db.table_exists(conn, "projects")
    where, params = _match(_SCENE_TEXT, words)
    if not words:
        where += " AND c.archived_at IS NULL"
    # the project's title rides on the hit (one LEFT JOIN, same owner) so
    # the palette can say where a scene lives without a second request
    join = ("LEFT JOIN projects p ON p.id = c.project_id "
            "AND p.account_id IS NOT DISTINCT FROM c.account_id ") if has_projects else ""
    project_title = "p.title AS project_title" if has_projects else "NULL AS project_title"
    project_id = "c.project_id" if has_projects else "NULL AS project_id"
    rows = conn.execute(
        f"SELECT c.id, c.title, c.card_line, c.logline, c.spark, {project_id}, "
        f"{project_title}, c.picked_at, c.archived_at, (c.shots_json::jsonb) -> 0 AS shot "
        f"FROM shoot_concepts c {join}"
        "WHERE c.account_id IS NOT DISTINCT FROM %s" + where
        + " ORDER BY c.archived_at IS NOT NULL, c.id DESC LIMIT %s",
        (account_id, *params, _FETCH)).fetchall()
    out = []
    for r in _rank([dict(r) for r in rows], words, q)[:limit]:
        shot = _shot0(r.get("shot"))
        prompt = shot.get("prompt") or ""
        title_has_all = bool(words) and all(w in (r.get("title") or "").lower() for w in words)
        out.append({
            "id": r["id"], "n": f"SHOOT-{r['id']:02d}",
            "title": r.get("title") or "Untitled scene",
            # what the scene says, or where in its prompt the words matched
            "sub": (_first_line(r.get("card_line") or r.get("logline"))
                    if not words or title_has_all else snippet(prompt, words)) or _first_line(prompt),
            "project_id": r.get("project_id"), "project_title": r.get("project_title"),
            "picked": bool(r.get("picked_at")), "archived": bool(r.get("archived_at")),
            "rendered": bool(shot.get("media_url")),
            "cover": _shot_cover(shot),
        })
    return out


# (table, kind, haystack, sub column). A prop whose category is "product"
# is shown as a product, the four kinds the Elements page draws.
_ELEMENT_TABLES = (
    ("characters", "character",
     "(coalesce(name, '') || ' ' || coalesce(role, '') || ' ' || coalesce(notes, ''))", "role"),
    ("props", "prop",
     "(coalesce(name, '') || ' ' || coalesce(category, '') || ' ' || coalesce(notes, ''))", "category"),
    ("locations", "place", "(coalesce(name, '') || ' ' || coalesce(notes, ''))", None),
)


def _elements(conn, account_id: Optional[int], words: list[str], q: str, limit: int) -> list[dict]:
    if not words:
        return []
    found: list[dict] = []
    for table, kind, haystack, sub in _ELEMENT_TABLES:
        if not db.table_exists(conn, table):
            continue
        where, params = _match(haystack, words)
        extra = f", {sub}" if sub else ""
        # one literal per table, each naming its owner (tests/test_tenancy.py)
        if table == "characters":
            sql = ("SELECT id, name, notes, created_at" + extra
                   + " FROM characters WHERE account_id IS NOT DISTINCT FROM %s")
        elif table == "props":
            sql = ("SELECT id, name, notes, created_at" + extra
                   + " FROM props WHERE account_id IS NOT DISTINCT FROM %s")
        else:
            sql = "SELECT id, name, notes, created_at FROM locations WHERE account_id IS NOT DISTINCT FROM %s"
        rows = conn.execute(sql + where + " ORDER BY id DESC LIMIT %s",
                            (account_id, *params, _FETCH)).fetchall()
        for r in rows:
            r = dict(r)
            k = "product" if kind == "prop" and (r.get("category") or "").lower() == "product" else kind
            prefix = {"character": "character", "prop": "prop", "product": "prop", "place": "location"}[k]
            found.append({"id": f"{prefix}-{r['id']}", "kind": k, "name": r["name"],
                          "title": r["name"],
                          "sub": _first_line(r.get("notes") or (r.get(sub) if sub else "") or ""),
                          "created_at": str(r.get("created_at") or "")})
    found.sort(key=lambda e: e["created_at"], reverse=True)
    ranked = _rank(found, words, q)[:limit]
    for e in ranked:
        e.pop("created_at", None)
        e.pop("title", None)
    return ranked


def _renders(conn, account_id: Optional[int], words: list[str], q: str, limit: int) -> list[dict]:
    from .render_assets import _label

    if not words or not db.table_exists(conn, "generated_assets"):
        return []
    where, params = _match("coalesce(prompt, '')", words)
    rows = conn.execute(
        "SELECT id, tool, model, media_kind, prompt, media_url, concept_id FROM generated_assets "
        "WHERE account_id IS NOT DISTINCT FROM %s AND deleted_at IS NULL" + where
        + " ORDER BY id DESC LIMIT %s",
        (account_id, *params, limit)).fetchall()
    return [{"id": r["id"], "kind": r["media_kind"],
             "label": _label(r["tool"] or "", r["model"] or ""),
             "sub": snippet(r["prompt"], words),
             "media_url": r["media_url"], "concept_id": r["concept_id"]}
            for r in rows]


def _cuts(conn, account_id: Optional[int], words: list[str], q: str, limit: int) -> list[dict]:
    if not words or not db.table_exists(conn, "cut_projects"):
        return []
    where, params = _match("coalesce(title, '')", words)
    rows = conn.execute(
        "SELECT id, title, concept_id FROM cut_projects "
        "WHERE account_id IS NOT DISTINCT FROM %s AND deleted_at IS NULL" + where
        + " ORDER BY updated_at DESC, id LIMIT %s",
        (account_id, *params, _FETCH)).fetchall()
    return [{"id": r["id"], "title": r["title"] or "Untitled cut", "concept_id": r["concept_id"]}
            for r in _rank([dict(r) for r in rows], words, q)[:limit]]


GROUPS = ("projects", "scenes", "elements", "renders", "cuts")


def run(q: Optional[str], *, account_id: Optional[int], limit: int = GROUP_LIMIT,
        dsn: Optional[str] = None) -> dict[str, Any]:
    """Every group for one account. An empty query is the recent list:
    the newest projects and open scenes, nothing else."""
    words = tokens(q)
    text = (q or "").strip()
    limit = max(1, min(int(limit or GROUP_LIMIT), MAX_GROUP_LIMIT))
    if not words:
        limit = min(limit, RECENT_LIMIT)
    with db.connect(dsn) as conn:
        groups = {
            "projects": _projects(conn, account_id, words, text, limit),
            "scenes": _scenes(conn, account_id, words, text, limit),
            "elements": _elements(conn, account_id, words, text, limit),
            "renders": _renders(conn, account_id, words, text, limit),
            "cuts": _cuts(conn, account_id, words, text, limit),
        }
    return {"q": text, "recent": not words, "groups": groups}


__all__ = ["GROUPS", "GROUP_LIMIT", "MAX_GROUP_LIMIT", "run", "snippet", "tokens"]
