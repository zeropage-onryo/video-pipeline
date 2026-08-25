# Task — Reference-grounded ideation (increment 1)

Wire the RAG reference library into **idea and concept generation**, exactly the
way `src/pitch.py` already grounds pitches. After this, every `shootgen` idea /
concept run queries the pgvector library (grounded on the spark + the mood of
the active rooms) and injects the closest chunks into the prompt — and degrades
to ungrounded, with a stderr note, when Postgres is down or the library is empty.

## Contracts to preserve (do not break)

1. **Graceful degradation.** A missing key / Postgres / empty library must never
   raise inside a generate call — it just generates ungrounded and says so on
   stderr. `rag.retrieve_references` already guarantees "never raises"; keep it
   the only retrieval entry point.
2. **Hermetic tests.** Retrieval must sit at the *edges* (CLI + web routes), and
   the tested generate functions must be pure w.r.t. RAG (they take a
   `references` string, default `""`). Anything that could touch the store in a
   test is patched at `shootgen.reference_block` or `rag.retrieve_references`
   (never left to hit `rag.connect`, which is below the socket guard — see
   `CLAUDE.md`).
3. **Prompts request, code enforces.** No validation changes; `validate_concept`
   is untouched. This only enriches the prompt.

---

## 1. `src/shootgen.py`

### 1a. Import `rag`

```python
from . import preprod, rag          # was: from . import preprod
```

### 1b. Add the no-references fallback + query builder + edge helper

Put these near the top, after the existing constants (`AI_TOOLS = (...)`):

```python
NO_REFERENCES_NOTE = (
    "(no reference library available -- generate from the rooms and brand alone)"
)


def build_reference_query(locations: list, spark=None, client=None,
                          max_chars: int = 4000) -> str:
    """
    The retrieval query for ideation: the creative direction actually in
    play -- the spark, the client/spec, and the mood of the described
    rooms (their space, textures, constraints) -- so the library returns
    tone/structure notes close to what's being made. The ideation
    analogue of pitch.py's build_reference_query, which queries with the
    footage itself.
    """
    parts: list = []
    if spark:
        parts.append(spark)
    if client:
        parts.append(client)
    for loc in locations:
        description = loc.get("description") or {}
        if description.get("space"):
            parts.append(description["space"])
        for key in ("textures", "constraints"):
            value = description.get(key)
            if isinstance(value, list):
                parts.extend(value)
            elif value:
                parts.append(value)
    return " ".join(str(p) for p in parts)[:max_chars]


def reference_block(spark=None, client=None, db_path=None) -> str:
    """
    Retrieve grounding references for an ideation run and return the
    formatted block, or "" if the library is unavailable. Never raises --
    the same enhancement-not-dependency contract pitch.py keeps. This is
    the *edge* helper: call it from entry points (CLI, web routes), not
    from inside the tested generate functions, so those stay hermetic.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    locations = preprod.list_locations(**kwargs)
    query = build_reference_query(locations, spark=spark, client=client)
    if not query.strip():
        return ""
    retrieval = rag.retrieve_references(query)
    if retrieval["ok"] and retrieval["references"]:
        print(f"Grounding in {len(retrieval['references'])} retrieved reference(s)",
              file=sys.stderr)
        return rag.format_references(retrieval["references"])
    reason = retrieval.get("error", "reference library is empty")
    print(f"note: generating without references: {reason}", file=sys.stderr)
    return ""
```

### 1c. Thread `references` through the two prompt builders

```python
def build_ideas_prompt(locations: list, brand: str, client=None, spark=None,
                       count: int = DEFAULT_IDEA_COUNT, references: str = "") -> str:
    template = (PROMPTS_DIR / "concept_ideas_prompt.txt").read_text()
    return (
        template
        .replace("{locations}", format_locations(locations))
        .replace("{brand}", load_brand(brand))
        .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
        .replace("{spark}", f"CREATIVE SPARK FROM THE FILMMAKER: {spark}" if spark else "")
        .replace("{count}", str(count))
        .replace("{references}", references or NO_REFERENCES_NOTE)
    )


def build_concept_prompt(locations: list, brand: str, client=None, spark=None,
                         use_pov: bool = True, references: str = "") -> str:
    template = apply_pov((PROMPTS_DIR / "concept_prompt.txt").read_text(), use_pov)
    return (
        template
        .replace("{locations}", format_locations(locations))
        .replace("{brand}", load_brand(brand))
        .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
        .replace("{spark}", f"CREATIVE SPARK FROM THE FILMMAKER: {spark}" if spark else "")
        .replace("{references}", references or NO_REFERENCES_NOTE)
    )
```

### 1d. Accept `references` in the two generators and pass it down

In `generate_concept_ideas(...)`, add `references: str = ""` to the signature and
pass it to the builder:

```python
def generate_concept_ideas(brand: str, client=None, spark=None, gemini_client=None,
                           model: str = MODEL, count: int = DEFAULT_IDEA_COUNT,
                           use_pov: bool = True, db_path=None,
                           references: str = "") -> dict:
    ...
    prompt = build_ideas_prompt(locations, brand, client, spark, count,
                                references=references)
    ...
```

In `generate_concept(...)`, same:

```python
def generate_concept(brand: str, client=None, spark=None, gemini_client=None,
                     model: str = MODEL, use_pov: bool = True, db_path=None,
                     references: str = "") -> dict:
    ...
    prompt = build_concept_prompt(locations, brand, client, spark,
                                  use_pov=use_pov, references=references)
    ...
```

### 1e. Ground the CLI (`main`)

In `main()`, right before the `generate_concept_ideas(...)` call in the non-`--shotlist`
branch, retrieve and pass references:

```python
    references = reference_block(spark=args.spark, client=args.client, db_path=path)
    try:
        result = generate_concept_ideas(
            brand=args.brand, client=args.client, spark=args.spark,
            gemini_client=gemini_client, count=args.count, db_path=path,
            references=references,
        )
    except ValueError as e:
        ...
```

---

## 2. Prompt files (creative surface — reword freely, keep the `{references}` token)

### `prompts/concept_ideas_prompt.txt`

Insert this block immediately after the `{spark}` line (i.e. after the `BRAND:` /
`{brand}` / `{client}` / `{spark}` group), before `Generate exactly {count} ...`:

```
REFERENCE LIBRARY (tone and structure to echo — match the sensibility, but
never call for something a reference shows that these rooms can't deliver):
{references}
```

### `prompts/concept_prompt.txt`

Insert the same block immediately after the `{spark}` line, before the
`SHOOT DISCIPLINE ...` section.

---

## 3. Web routes (`app/main.py`) — ground the in-app "Generate"

In **both** `concepts_generate` and `studio_generate`, after `use_pov` is
resolved and before the `try:` that calls the generator, compute references and
pass them in.

`concepts_generate` — ideas branch and concept branch:

```python
    references = shootgen.reference_block(spark=spark, client=client_name, db_path=db.DB_PATH)
    try:
        gemini_client = genai.Client(api_key=api_key)
        if (form.get("mode") or "").strip() == "ideas":
            result = shootgen.generate_concept_ideas(
                brand=brand, client=client_name, spark=spark,
                gemini_client=gemini_client, use_pov=use_pov, db_path=db.DB_PATH,
                references=references,
            )
            ...
        else:
            result = shootgen.generate_concept(
                brand=brand, client=client_name, spark=spark,
                gemini_client=gemini_client, use_pov=use_pov, db_path=db.DB_PATH,
                references=references,
            )
```

`studio_generate` — identical treatment (add the `references = shootgen.reference_block(...)`
line and pass `references=references` into both `generate_concept_ideas` and
`generate_concept`).

---

## 4. Tests — `tests/test_shootgen_references.py` (new)

Patches at `shootgen.rag.retrieve_references` and `shootgen.preprod.list_locations`,
so nothing touches Gemini or Postgres. Fully hermetic.

```python
from src import shootgen


def test_build_ideas_prompt_injects_references():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    prompt = shootgen.build_ideas_prompt(
        locs, "antihero", references="1. [brief.txt] still, patient, one move"
    )
    assert "1. [brief.txt] still, patient, one move" in prompt
    assert "{references}" not in prompt


def test_build_ideas_prompt_falls_back_without_references():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    prompt = shootgen.build_ideas_prompt(locs, "antihero", references="")
    assert shootgen.NO_REFERENCES_NOTE in prompt
    assert "{references}" not in prompt


def test_build_concept_prompt_injects_references():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    prompt = shootgen.build_concept_prompt(
        locs, "antihero", references="1. [kurosawa.txt] hold the frame"
    )
    assert "1. [kurosawa.txt] hold the frame" in prompt
    assert shootgen.NO_REFERENCES_NOTE not in prompt


def test_build_reference_query_uses_spark_and_room_mood():
    locs = [{"name": "shop",
             "description": {"space": "garage", "textures": ["wet metal"],
                             "constraints": "no clean wide"}}]
    q = shootgen.build_reference_query(locs, spark="gearing up ritual", client=None)
    assert "gearing up ritual" in q
    assert "wet metal" in q and "no clean wide" in q


def test_reference_block_formats_hits(monkeypatch):
    monkeypatch.setattr(shootgen.preprod, "list_locations",
                        lambda **k: [{"name": "shop", "description": {"space": "garage"}}])
    monkeypatch.setattr(
        shootgen.rag, "retrieve_references",
        lambda *a, **k: {"ok": True, "references": [
            {"source": "brief.txt", "chunk": "still, patient, one move"}]},
    )
    block = shootgen.reference_block(spark="ritual")
    assert "brief.txt" in block and "still, patient, one move" in block


def test_reference_block_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(shootgen.preprod, "list_locations",
                        lambda **k: [{"name": "shop", "description": {"space": "garage"}}])
    monkeypatch.setattr(
        shootgen.rag, "retrieve_references",
        lambda *a, **k: {"ok": False, "references": [], "error": "no postgres"},
    )
    assert shootgen.reference_block(spark="ritual") == ""


def test_reference_block_empty_when_no_locations(monkeypatch):
    monkeypatch.setattr(shootgen.preprod, "list_locations", lambda **k: [])
    # no rooms -> empty query -> no retrieval attempted, returns ""
    assert shootgen.reference_block(spark="ritual") == ""
```

---

## 5. Update any existing tests that assert full prompt text

Adding the `{references}` slot changes the rendered ideas/concept prompt. If any
existing test asserts an exact prompt string for `build_ideas_prompt` /
`build_concept_prompt`, update the expected text to include the new reference
block (it renders `NO_REFERENCES_NOTE` when `references=""`).

If any **web-route** test exercises `POST /concepts/generate` or
`POST /studio/generate` without patching the generator, add
`monkeypatch.setattr(app.main.shootgen, "reference_block", lambda **k: "")` (or
patch `shootgen.reference_block`) so the route test never reaches the store.

---

## 6. Verify

```bash
venv/bin/python -m pytest tests/ -q          # all green, incl. the new file
venv/bin/ruff check .                        # clean

# live smoke (needs Postgres up + a populated library + GEMINI_API_KEY):
venv/bin/python -m src.rag ingest prompts/brief.txt --domain personal_brand
venv/bin/python -m src.shootgen --spark "gearing up ritual"
#   -> stderr shows: "Grounding in N retrieved reference(s)"
#   with Postgres stopped, same command shows:
#   "note: generating without references: <reason>"  and still produces ideas
```

Done when: tests pass, ruff clean, and the smoke run prints the grounding note
with the library up and the ungrounded note with it down.
