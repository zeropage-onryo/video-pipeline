"""
Camera / framing presets for the Generate tab and Director-mode nodes.

The presets live in prompts/presets.json -- data, not code, same
philosophy as prompts/brands.txt: the wording is the highest-frequency
edit surface, so it's editable without touching Python. A preset is
{"id", "label", "how"}; picking one folds its `how` text into the
Enhance step's instructions (the same fixed-menu-not-free-invention
move ZEROPAGE_FORMATS makes for concept structure).

Loading never raises -- a missing or broken file means no presets, an
enhancement degraded, never a dead endpoint.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRESETS_PATH = PROJECT_ROOT / "prompts" / "presets.json"


def load_presets(path: Optional[Path] = None) -> list[dict]:
    """Every preset with a non-empty id, label, and how. [] on any
    failure, with a stderr note -- the degrade contract."""
    try:
        data = json.loads((path or PRESETS_PATH).read_text())
        presets = data.get("presets") or []
        return [p for p in presets
                if (p.get("id") or "").strip()
                and (p.get("label") or "").strip()
                and (p.get("how") or "").strip()]
    except Exception as e:
        print(f"note: presets unavailable: {e}", file=sys.stderr)
        return []


def get_preset(preset_id, path: Optional[Path] = None) -> Optional[dict]:
    """One preset by id, or None -- an unknown id is a caller mistake
    that degrades to no scaffold, never an error."""
    if not preset_id:
        return None
    return next((p for p in load_presets(path) if p["id"] == preset_id), None)
