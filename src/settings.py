"""
The tunables the Dev Studio Settings tab edits: the three knobs that
actually govern generation/eval quality, in the shared
`settings` table (the same key/value table autonomy's kill switch
lives in -- one table, namespaced keys, no second store).

Precedence per key: a stored settings row wins, then the env var, then
the code default -- so the env-only workflow (PROMPT_GATE_MIN=8 in
.env) keeps working unchanged until a value is saved from the UI, and
clearing the stored value falls back rather than zeroing anything.

Reads never raise: a missing table or unreadable value returns the
default, because these are consulted from inside the orchestrator and
CRAG grading where "the settings table isn't there" must degrade to
the shipped behavior, not kill the run.
"""
import os
from typing import Any, Optional

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT
);
"""

# key -> how to read, validate, and describe it. `default` is the
# shipped constant each call site used to hardcode.
TUNABLES = {
    "prompt_gate_min": {
        "env": "PROMPT_GATE_MIN", "default": 7, "cast": int, "lo": 0, "hi": 10,
        "label": "Prompt gate minimum",
        "help": "Judge score (of 10) a prompt must clear before the credit "
                "gate lets a run through (src/orchestrator.py).",
    },
    "grade_threshold": {
        "env": "GRADE_THRESHOLD", "default": 0.55, "cast": float, "lo": 0.0, "hi": 1.0,
        "label": "Retrieval grade threshold",
        "help": "Best-hit cosine score below which CRAG calls a retrieval "
                "weak and rewrites the query once (src/crag.py).",
    },
    "eval_k": {
        "env": "EVAL_K", "default": 5, "cast": int, "lo": 1, "hi": 20,
        "label": "Eval k",
        "help": "How many results the retrieval eval scores per query -- "
                "Hit@k and the run's stored config (app/api.py).",
    },
}


def init(dsn=None) -> None:
    with db.connect(dsn) as conn:
        conn.execute(SCHEMA)


def get_raw(key: str, dsn=None) -> Optional[str]:
    """The stored value only -- None when nothing is saved (or the
    table doesn't exist yet). dsn=None resolves DATABASE_URL at call
    time, so a monkeypatched/relocated DB is honoured."""
    try:
        with db.connect(dsn) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
            return row["value"] if row else None
    except Exception:
        return None


def get(key: str, dsn=None) -> Any:
    """The effective typed value: stored setting, else env, else default."""
    spec = TUNABLES[key]
    raw = get_raw(key, dsn=dsn)
    if raw is None and spec["env"]:
        raw = os.environ.get(spec["env"])
    if raw is None:
        return spec["default"]
    try:
        return spec["cast"](raw)
    except (TypeError, ValueError):
        return spec["default"]


def set_value(key: str, raw: str, dsn=None) -> Any:
    """Validate and store one tunable. An empty string clears the stored
    row so the env/default fallback takes over again. Raises ValueError
    on an unknown key or an out-of-range value -- writes are the one
    place this module is strict."""
    if key not in TUNABLES:
        raise ValueError(f"unknown setting {key!r}")
    spec = TUNABLES[key]
    raw = (raw or "").strip()
    if raw == "":
        clear(key, dsn=dsn)
        return get(key, dsn=dsn)
    try:
        value = spec["cast"](raw)
    except (TypeError, ValueError):
        raise ValueError(f"{spec['label']} needs a {spec['cast'].__name__}, got {raw!r}")
    if not (spec["lo"] <= value <= spec["hi"]):
        raise ValueError(
            f"{spec['label']} must be between {spec['lo']} and {spec['hi']}")
    init(dsn=dsn)
    with db.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
    return value


def clear(key: str, dsn=None) -> None:
    try:
        with db.connect(dsn) as conn:
            conn.execute("DELETE FROM settings WHERE key = %s", (key,))
    except Exception:
        pass


def describe(dsn=None) -> list:
    """The Settings form's rows: effective value plus where it came
    from, so the tab can say 'this is the env var talking' honestly."""
    rows = []
    for key, spec in TUNABLES.items():
        stored = get_raw(key, dsn=dsn)
        if stored is not None:
            source = "settings"
        elif spec["env"] and os.environ.get(spec["env"]) is not None:
            source = f"env ({spec['env']})"
        else:
            source = "default"
        rows.append({"key": key, "label": spec["label"], "help": spec["help"],
                     "value": get(key, dsn=dsn), "default": spec["default"],
                     "lo": spec["lo"], "hi": spec["hi"], "source": source})
    return rows


# Typed conveniences for the three call sites.

def prompt_gate_min(dsn=None) -> int:
    return get("prompt_gate_min", dsn=dsn)


def grade_threshold(dsn=None) -> float:
    return get("grade_threshold", dsn=dsn)


def eval_k(dsn=None) -> int:
    return get("eval_k", dsn=dsn)
