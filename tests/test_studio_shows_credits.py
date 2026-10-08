"""
Credits everywhere (2026-10-08, part 2 of
docs/tasks/task-spend-holes-and-credits.md): a person in the studio sees
CREDITS, never the provider's dollars. Dollars stay on the operator's
pages (/costs, the Dev Studio) and on the marketing site's plan prices,
none of which are scanned here.

- the default renderer's state carries its clip's price in credits, by the
  same conversion pricing.display makes, so no client has to fall back to
  the dollar estimate
- no studio page, no Director component and not the legacy Queue formats a
  dollar figure: a guard over the source, because every dollar label that
  shipped was added by a page that had the number in hand and printed it.
  A Python test rather than a node one so CI runs it (CI runs no web tests).
"""
import re
from pathlib import Path

from app import api
from src import pricing, providers

ROOT = Path(__file__).resolve().parent.parent

# what is scanned: every studio page and component, the Director canvas, the
# shared price text, and the legacy /ui Queue
SCANNED = [
    *sorted((ROOT / "web/src/app/studio").rglob("*.ts*")),
    *sorted((ROOT / "web/src/components/studio").rglob("*.ts*")),
    *sorted((ROOT / "web/src/components/flows").rglob("*.ts*")),
    ROOT / "web/src/lib/render-choice.ts",
    ROOT / "app/static/zpf/queue.js",
]

# a dollar figure being built: "~$", "$${" (a literal $ before an
# interpolation), '$' + ..., or toFixed(2) on a line about usd / estimate
DOLLARS = [
    (re.compile(r"~\$"), "a '~$' label"),
    (re.compile(r"\$\$\{"), "a '$' before an interpolation"),
    (re.compile(r"""['"]\$['"]\s*\+"""), "'$' + a number"),
    (re.compile(r"(?i)(usd|estimate).*toFixed\(2\)|toFixed\(2\).*(usd|estimate)"),
     "toFixed(2) on a dollar estimate"),
]


def _code(line: str) -> bool:
    stripped = line.strip()
    return not stripped.startswith(("//", "*", "/*"))


def test_no_studio_surface_formats_dollars():
    assert all(p.exists() for p in SCANNED[-2:])
    found = []
    for path in SCANNED:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if not _code(line):
                continue
            for pattern, what in DOLLARS:
                if pattern.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{n}: {what}: {line.strip()[:120]}")
    assert not found, "the studio shows credits, never dollars:\n" + "\n".join(found)


def test_the_guard_would_have_caught_the_labels_it_replaced():
    """The lines this pass removed, as they were: each must trip the guard,
    or the guard is guarding nothing."""
    removed = [
        "? `est. $${Number(rw.estimate_usd).toFixed(2)}`",
        "tally.usd ? `~$${tally.usd.toFixed(2)}` : \"\",",
        ": usd === null || usd === undefined ? 'unpriced' : '~$' + usd.toFixed(2)}`;",
        "<b>{rw?.estimate_usd != null ? `$${Number(rw.estimate_usd).toFixed(2)}` : \"—\"}</b>",
    ]
    for line in removed:
        assert any(p.search(line) for p, _ in DOLLARS), line


def test_the_renderer_state_carries_its_clip_in_credits(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "k")
    state = api._render_state(None)
    pick = providers.check_render_choice()
    assert state["estimate_usd"] == pick["estimate_usd"]
    assert state["credits"] == pricing.credits_for(pricing.usd_micros(pick["estimate_usd"]))
    assert state["credits"] >= pricing.CREDIT_FLOOR
