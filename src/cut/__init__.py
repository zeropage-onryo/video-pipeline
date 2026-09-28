"""
src/cut -- the ZPF editor, phase 1 of docs/CUT_EDITOR.md (Assemble v0).

Approved Queue clips -> a timeline document -> one finished MP4. The
modules, in the order data moves through them:

    doc.py       the timeline document: integer frames, tracks, handles
    ops.py       pure doc -> doc edits (the only edits an agent may emit)
    validate.py  the safety rail every doc passes before it is stored or rendered
    sources.py   handle -> local file + probe (the only place a URL is read)
    store.py     `timelines` (insert-only versions + a head pointer) and `cut_media`
    assemble.py  a concept's clips, in timeline.py part order -> version 1
    render.py    doc -> one ffmpeg filter_complex -> MP4

The rule copied from invideo and kept everywhere here: an edit is a typed,
validated document, never pixels, and a clip names its media by HANDLE
(`gen:<id>`, `asset:<id>`), never by URL -- every reference bug this repo
has paid for came from storing a URL.
"""
