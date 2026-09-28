"""
src/cut/projects.py -- the editor's projects, and the one door an edit
comes through (docs/CUT_EDITOR.md 5.1-5.2, phase B, 2026-09-28).

A project is a `cut_projects` row (store.py) naming the `timeline_key`
its versions live under. Two ways one comes into being (Mike's D2):

- SCRATCH: a blank starter cut (V1 picture, A1 the clips' own sound,
  A2 music) at the canvas the person picked, version 1 by "user",
  "new project". Its key is `cut:<the project's uuid>`.
- A CONCEPT'S CUT: create-or-return the project whose key is
  `concept:<id>`, so it shares the history Assemble already wrote. When
  that history is empty, version 1 is the cut Assemble would make --
  built from `assemble.plan` + the CACHED probe, never rendered -- or,
  when a clip is missing or its file cannot be measured, the empty
  starter cut with the reason as a note. An editor that refused to open
  a half-rendered concept would be a worse editor than an empty timeline.

`edit` is the one door every hand edit takes: the base version the
client edited must still be the head (else StaleEdit, the client
refetches), the op runs through `ops.apply` against measured media, and
the result is saved as a new version whose parent is that base. Undo and
redo move the head pointer (store.undo / store.redo); nothing is ever
deleted.

The measuring rule, which is the part worth knowing: a handle ALREADY on
the timeline whose file cannot be measured right now is passed to the
validator as known-but-unmeasured (None) -- one unreachable file must not
freeze the whole cut -- while a handle an op would ADD must be measured,
or the edit is refused. Nothing is inserted on faith.

Every function takes `account_id` keyword-only with no default, the
store's rule; someone else's project is None, exactly like a missing one.
"""
from __future__ import annotations

from typing import Any, Optional

from . import doc as d
from . import ops, sources, store


class StaleEdit(RuntimeError):
    def __init__(self, head_id: Optional[int]):
        self.head_id = head_id
        super().__init__("this cut has changed since you loaded it")


class MediaRefused(ops.OpError):
    """An op that would ADD media that is not this account's, or cannot
    be read. An OpError, so the route answers it like any other invalid
    edit."""


# --------------------------------------------------------------------------
# creating
# --------------------------------------------------------------------------

def create_scratch(*, account_id: Optional[int], title: Optional[str] = None,
                   aspect: str = "9:16", dsn: Optional[str] = None) -> dict[str, Any]:
    size = d.ASPECT_SIZES.get(aspect)
    if size is None:
        raise ValueError(f"aspect must be one of {list(d.ASPECT_SIZES)}")
    row = store.create_project(account_id=account_id, title=(title or "").strip() or "Untitled cut",
                               fps=d.DEFAULT_FPS, dsn=dsn)
    store.save_version(row["timeline_key"], d.starter_doc(d.DEFAULT_FPS, size),
                       account_id=account_id, author="user", op_summary="new project", dsn=dsn)
    return row


def _first_cut(concept_id: int, *, account_id: Optional[int],
               dsn: Optional[str]) -> tuple[dict, str, str, list[str]]:
    """(doc, author, op_summary, notes) for a concept whose cut has no
    history yet. Assemble's plan, measured from the cache -- no file is
    rendered, and a file is only fetched the first time it is measured."""
    from . import assemble
    starter = d.starter_doc()
    try:
        planned = assemble.plan(concept_id, account_id=account_id, dsn=dsn)
    except assemble.AssembleError as e:
        return starter, "user", "new project", [str(e)]
    if planned["missing"] or not planned["clips"]:
        return starter, "user", "new project", planned["missing"] or ["no clips to assemble"]
    handles = [c["handle"] for c in planned["clips"]]
    media = sources.measure(handles, account_id=account_id, fps=d.DEFAULT_FPS, dsn=dsn)
    unread = [h for h in handles if not media.get(h)]
    if unread:
        return starter, "user", "new project", [f"could not read {', '.join(unread)} -- "
                                                "started from an empty timeline"]
    doc, notes = assemble.build_doc(planned["clips"], media, fps=d.DEFAULT_FPS)
    for tid, role in (("A1", "sfx"), ("A2", "music")):
        if d.track(doc, tid) is None:
            doc["tracks"].append({"id": tid, "kind": "audio", "role": role, "clips": []})
    return (doc, "assemble", f"assembled {len(planned['clips'])} clip(s)",
            planned["notes"] + notes)


def open_concept(concept_id: int, *, account_id: Optional[int],
                 dsn: Optional[str] = None) -> dict[str, Any]:
    """Create-or-return the project on `concept:<id>`. LookupError when
    the concept is not this account's."""
    import psycopg

    from .. import preprod
    concept = preprod.get_concept(concept_id, dsn, account_id=account_id)
    if concept is None:
        raise LookupError(f"no concept {concept_id}")
    existing = store.project_for_concept_id(concept_id, account_id=account_id, dsn=dsn)
    if existing:
        return existing
    key = store.project_for_concept(concept_id)
    head = store.head(key, account_id=account_id, dsn=dsn)
    fps = int(head["doc"]["fps"]) if head else d.DEFAULT_FPS
    if head is None:
        doc, author, summary, _notes = _first_cut(concept_id, account_id=account_id, dsn=dsn)
        fps = doc["fps"]
        store.save_version(key, doc, account_id=account_id, author=author,
                           op_summary=summary, dsn=dsn)
    title = concept.get("title") or f"Concept #{concept_id}"
    try:
        return store.create_project(account_id=account_id, title=title, timeline_key=key,
                                    concept_id=concept_id, fps=fps, dsn=dsn)
    except psycopg.errors.UniqueViolation:
        # two opens at once: the other one won, and it is the same project
        return store.project_for_concept_id(concept_id, account_id=account_id, dsn=dsn)


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def poster_urls(handles, *, account_id: Optional[int], dsn: Optional[str] = None) -> dict[str, str]:
    """handle -> a still to put on a card: the image itself, the Asset
    Bank's poster derivative for a clip, else a preview poster this
    module drew. Two queries for any number of cards."""
    from .. import media
    handles = [h for h in dict.fromkeys(handles) if h]
    rows = store.handle_sources(handles, account_id=account_id, dsn=dsn)
    cache = store.cached(list(rows), account_id=account_id, dsn=dsn)
    out = {}
    for h, row in rows.items():
        url = row.get("media_url") or ""
        if row.get("kind") == "image":
            out[h] = media.url_for(url, account_id)
            continue
        poster = media.thumb_url_for(url, account_id) if url else None
        if not poster and (cache.get(h) or {}).get("poster_url"):
            poster = media.url_for(cache[h]["poster_url"], account_id)
        if poster:
            out[h] = poster
    return out


def _mint(stored: Optional[str], account_id: Optional[int]) -> Optional[str]:
    if not stored:
        return None
    from .. import media
    return media.url_for(stored, account_id)


def card(row: dict, *, account_id: Optional[int], poster: Optional[str] = None,
         head: Optional[dict] = None) -> dict[str, Any]:
    """A project row (+ its head's fields) -> the P shape every route
    returns. `head` is a full head version when the caller has one; else
    the row carries list_projects' lean columns."""
    if head is not None:
        size, duration = head["doc"].get("size"), head["doc"].get("duration")
        version, export = head.get("version"), head.get("export_url")
    else:
        size, duration = row.get("size"), row.get("duration")
        version, export = row.get("version"), row.get("export_url")
    size = list(size) if size else list(d.DEFAULT_SIZE)
    return {"id": row["id"], "title": row["title"], "timeline_key": row["timeline_key"],
            "concept_id": row.get("concept_id"), "fps": row["fps"], "size": size,
            "aspect": d.aspect_of(size), "duration": int(duration or 0),
            "version": version, "poster": poster, "export_url": _mint(export, account_id),
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def cards(*, account_id: Optional[int], dsn: Optional[str] = None) -> list[dict[str, Any]]:
    rows = store.list_projects(account_id=account_id, dsn=dsn)
    posters = poster_urls([r.get("poster_handle") for r in rows],
                           account_id=account_id, dsn=dsn)
    return [card(r, account_id=account_id, poster=posters.get(r.get("poster_handle")))
            for r in rows]


def first_picture(doc: dict) -> Optional[str]:
    for t in d.tracks_of(doc, "video"):
        for c in sorted(t.get("clips") or [], key=lambda c: c["at"]):
            return c.get("media")
    return None


def head_view(head: dict, *, account_id: Optional[int]) -> dict[str, Any]:
    """H: the head version as the editor reads it (V is this minus doc)."""
    return {"id": head["id"], "version": head["version"], "parent_id": head.get("parent_id"),
            "author": head["author"], "op_summary": head["op_summary"],
            "created_at": head["created_at"],
            "export_url": _mint(head.get("export_url"), account_id), "doc": head["doc"]}


def version_view(row: dict, *, account_id: Optional[int]) -> dict[str, Any]:
    return {"id": row["id"], "version": row["version"], "parent_id": row.get("parent_id"),
            "author": row["author"], "op_summary": row["op_summary"],
            "created_at": row["created_at"],
            "export_url": _mint(row.get("export_url"), account_id)}


def media_view(doc: dict, *, account_id: Optional[int],
               dsn: Optional[str] = None) -> dict[str, dict[str, Any]]:
    """{handle: {"frames", "video", "audio", "seconds"}} for every handle
    the doc names that could be measured (at the doc's fps). One that
    could not is left out -- the client draws it as unknown length."""
    measured = sources.measure(d.handles(doc), account_id=account_id, fps=doc["fps"], dsn=dsn)
    return {h: {"frames": m["frames"], "video": bool(m["video"]), "audio": bool(m["audio"]),
                "seconds": round(float(m["seconds"] or 0), 3)}
            for h, m in measured.items() if m}


def state(project: dict, head: dict, *, account_id: Optional[int],
          dsn: Optional[str] = None) -> dict[str, Any]:
    """What /ops, /undo, /redo and /rollback all answer."""
    return {"head": head_view(head, account_id=account_id),
            "can_undo": head.get("parent_id") is not None,
            "can_redo": head.get("redo_id") is not None,
            "media": media_view(head["doc"], account_id=account_id, dsn=dsn)}


# --------------------------------------------------------------------------
# editing
# --------------------------------------------------------------------------

def _arg_handles(args: Any) -> list[str]:
    """Every media handle an op's args name (today only insert's
    clip.media, but read generically so the next op that adds media is
    covered without remembering to come here)."""
    found: list[str] = []
    if isinstance(args, dict):
        for k, val in args.items():
            if k == "media" and isinstance(val, str):
                found.append(val)
            else:
                found += _arg_handles(val)
    elif isinstance(args, list):
        for item in args:
            found += _arg_handles(item)
    return found


def edit(project: dict, *, base_id: int, op: str, args: Optional[dict],
         account_id: Optional[int], dsn: Optional[str] = None) -> dict[str, Any]:
    """Apply one op to the head and save it as a new version. Raises
    StaleEdit (the head is not `base_id`), ops.OpError (with .problems)."""
    key = project["timeline_key"]
    head = store.head(key, account_id=account_id, dsn=dsn)
    if head is None or head["id"] != base_id:
        raise StaleEdit(head["id"] if head else None)
    doc = head["doc"]
    on_timeline = set(d.handles(doc))
    adding = [h for h in _arg_handles(args or {}) if h not in on_timeline]
    measured = sources.measure(list(on_timeline) + adding, account_id=account_id,
                               fps=doc["fps"], dsn=dsn)
    refused = []
    for h in adding:
        if d.parse_handle(h) is None:
            continue                      # the validator names a non-handle itself
        if h not in measured:
            refused.append(f"unknown media handle {h}")
        elif measured[h] is None:
            refused.append(f"could not read {h} -- it cannot be added until its file is reachable")
    if refused:
        raise MediaRefused(refused[0], refused)
    media = {h: measured.get(h) for h in on_timeline}   # absent -> None: unmeasured, known
    media.update({h: measured[h] for h in adding if h in measured})
    new = ops.apply(doc, op, args or {}, media=media)
    try:
        saved = store.save_version(key, new, account_id=account_id, author="user",
                                   op_summary=ops.describe(op, args, doc["fps"]),
                                   parent_id=head["id"], expect_head=head["id"], dsn=dsn)
    except store.StaleHead as e:
        raise StaleEdit(e.head_id) from None
    store.update_project(project["id"], account_id=account_id, dsn=dsn)
    return store.head(key, account_id=account_id, dsn=dsn) or saved
