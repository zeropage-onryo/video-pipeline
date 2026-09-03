"""
Format-trend feed for Zero Page.

Zero Page rides FORMAT skeletons (the structure that travels), not rooms. This
module ranks the evergreen skeletons (shootgen.ZEROPAGE_FORMATS) by what is
actually working -- counting how often each skeleton's signature shows up in
our proven winners -- so the generator leans into formats with a track record
instead of guessing. A live "spice" list (today's spiking formats/topics,
supplied by hand or a future scraper) is prepended on top.

Contract, same as reference_block / grounding: this is an ENHANCEMENT, never a
gate. Any failure -- no winners table, no data, a bad row -- degrades to the
plain evergreen order. It never raises.

Format-first by design: the ranking is over structural skeletons (evergreen,
reusable), and today's-hot is a spice on top, not the base -- so Zero Page is
never hostage to a news cycle.
"""
from __future__ import annotations

import sys

from src import shootgen, winners

# Signature keywords per evergreen skeleton -- how we detect that a proven
# winner rode this format, from its prompt text and note. Lowercased contains
# checks; overlap is fine (a ranking heuristic, not a classifier).
FORMAT_KEYWORDS = {
    "The Reveal": ("reveal", "revealed", "turns out", "then we see", "then you see"),
    "Slow Push-In": ("push in", "push-in", "slow push", "dolly in", "creep toward", "slowly zoom"),
    "Freeze on the Wrong Thing": ("freeze", "freeze-frame", "hard stop", "still frame", "holds on"),
    "POV Walk-In": ("pov", "first-person", "first person", "walk in", "walking in", "enters the"),
    "Seamless Loop": ("loop", "loops", "seamless", "loopable"),
    "Satisfying, Then Broken": ("satisfying", "asmr", "tactile", "pour", "stack", "pristine"),
    "Text-Hook Cold Open": ("text overlay", "on-screen text", "caption", "title card", "text hook"),
    "The Repetition Break": ("again and again", "pattern", "rhythm", "each time", "repeats", "over and over"),
}


def _win_score(name: str, worked_text: str) -> int:
    """How many times this skeleton's signatures appear across winner text."""
    kws = FORMAT_KEYWORDS.get(name, ())
    return sum(worked_text.count(kw) for kw in kws)


def rank_formats(dsn=None, spice=None, limit: int | None = None) -> list[tuple[str, str]]:
    """
    The skeleton menu Zero Page rides, ranked. Proven formats (those whose
    signatures show up most in worked winners) float to the top; the rest keep
    their evergreen order. `spice` (a list of "Name: how" or plain strings)
    is prepended as today's-hot. Always returns a non-empty list.
    """
    evergreen = list(shootgen.ZEROPAGE_FORMATS)

    ranked = evergreen
    try:
        rows = winners.list_all(dsn=dsn)
        blob = " ".join(
            f"{(w.get('prompt') or '')} {(w.get('note') or '')}".lower()
            for w in rows
            if str(w.get("verdict") or "worked").lower() == "worked"
        )
        if blob.strip():
            # stable sort: higher win-score first, evergreen order breaks ties
            ranked = sorted(
                evergreen,
                key=lambda nf: -_win_score(nf[0], blob),
            )
    except Exception as e:  # never a gate -- degrade to evergreen order
        print(f"note: format feed degraded to evergreens: {e}", file=sys.stderr)
        ranked = evergreen

    out: list[tuple[str, str]] = []
    for item in spice or []:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            out.append((str(item[0]), str(item[1])))
        else:
            out.append((str(item), "TRENDING NOW -- ride this while it's hot."))
    out.extend(ranked)

    if limit is not None:
        out = out[:limit]
    return out or evergreen


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Show Zero Page's ranked format feed.")
    p.add_argument("--spice", nargs="*", default=None,
                   help="today's hot formats/topics to prepend")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)
    for i, (name, how) in enumerate(rank_formats(spice=args.spice, limit=args.limit), 1):
        print(f"{i:>2}. {name}: {how}")


if __name__ == "__main__":
    main()
