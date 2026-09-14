"""
Tests for src/orchestrator.py -- the autonomous content graph.

Hermetic: the billed seams (shootgen.generate_concept, CRAG retrieval,
scheduling.build_caption, the judge client) are patched at their
modules; entities/locations/autonomy run against a throwaway SQLite
database via DATABASE_URL. Every graph test drives the compiled GRAPH through
run(), so the edges and all three conditionals are exercised. The
publish gates are driven directly -- with generate_render a dry-run
stub, the wired graph can't reach publish until renders are real, and
the gate logic still has to be right before that day.
"""
import pytest

from src import autonomy, db, entities, orchestrator, preprod


@pytest.fixture
def tmp_db(pg, monkeypatch):
    """The orchestrator's nodes read DATABASE_URL directly (same as the web
    routes), so point it at a throwaway database."""
    path = pg
    preprod.init(path)
    entities.init(path)
    autonomy.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    # ADVISORY IS THE DEFAULT (2026-09-07), and the suite says so by
    # clearing the switch rather than by setting it: a machine with
    # ZEROPAGE_GATES exported would otherwise pass tests that describe
    # behaviour it isn't running. The hard-mode tests set it themselves.
    monkeypatch.delenv("ZEROPAGE_GATES", raising=False)
    preprod.add_location("hallway", {"space": "narrow hallway"}, photo_count=2, dsn=path, account_id=None)
    # graph tests must not reach the real library or Gemini
    monkeypatch.setattr(orchestrator.crag, "retrieve_with_crag",
                        lambda *a, **k: {"ok": False, "references": [],
                                         "error": "no store in tests"})
    monkeypatch.setattr(orchestrator.scheduling, "build_caption",
                        lambda fallback, db_path=None: fallback)
    monkeypatch.setattr(orchestrator, "_client", lambda: None)
    # the prompt judge is fail-closed and billed; default it to a clean
    # pass so graph tests exercise the line past the gate. Gate tests
    # override this stub themselves.
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda prompt: {"score": 10, "reason": "",
                                        "dims": {d: 2 for d in orchestrator._PROMPT_DIMS}})
    return path


GOOD_PROMPT = ("Extreme macro close-up of a brass door handle slowly turning in a "
               "dark hallway at night, one warm practical light spilling under the "
               "door, heavy film grain, crushed shadows, noir mood, static camera")

REWORKED_PROMPT = ("Extreme macro close-up of a brass door handle slowly turning on its "
                   "own in a dark hallway at night, one warm practical light spilling "
                   "under the door, heavy film grain, crushed shadows, noir mood, "
                   "static locked-off camera, no other motion in frame")

# captured at import, before any fixture stubs it -- for the tests that
# need the real fail-closed judge back
REAL_JUDGE_PROMPT = orchestrator._judge_prompt


SEED_REF = "/refs/seed.jpg"


def make_concept(**overrides):
    """ONE scene, ONE prompt -- what gen_concept has written since
    2026-08-29. A multi-shot concept would be generated, scored and
    keyframed and then invisible to the Queue, which keys on is_scene
    (len(shots) == 1)."""
    concept = {
        "title": "The Waiting",
        "hook": "a hand already on the door handle",
        "logline": "He waits for someone who never knocks.",
        "shots": [
            {"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
             "location": "hallway", "desc": "the handle turns on its own",
             "prompt": GOOD_PROMPT},
        ],
    }
    concept.update(overrides)
    return concept


class _Calls(list):
    """A list that also carries the keyframe calls, so a test can assert
    on both without two return values."""
    keyframes: list


def stage_fakes(monkeypatch, results):
    """Patch generate_scene_concept; record the kwargs of every attempt."""
    queue = list(results)
    calls = _Calls()

    def fake_generate(brand, spark=None, steer="", gemini_client=None, model=None,
                      db_path=None, references="", cast=None, tool=None,
                      image_refs=None, account_id=None, brain=None, seconds=None):
        calls.append({"brand": brand, "spark": spark, "steer": steer,
                      "references": references, "brain": brain, "seconds": seconds,
                      "cast": cast, "image_refs": list(image_refs or [])})
        concept, warnings = queue.pop(0)
        concept_id = _save_scene(None, concept, brand)
        return {"concept_id": concept_id, "concept": concept, "warnings": warnings}

    monkeypatch.setattr(orchestrator.shootgen, "generate_scene_concept", fake_generate)
    # the keyframe node renders a still for every scene whose prompt
    # clears the gate. Patched by name and counted: a miss here is a
    # real billed image call escaping a test.
    keyframes = []

    def fake_keyframe(prompt, *, reference_image=None, db_path=None,
                      concept_id=None, **kw):
        keyframes.append({"prompt": prompt, "concept_id": concept_id})
        return {"ok": True, "media_url": f"https://cdn/key-{concept_id}.png",
                "generation_id": 1, "path": "x", "error": None}

    monkeypatch.setattr(orchestrator.scene_chain.nano_banana,
                        "generate_from_prompt", fake_keyframe)

    # The reference gate (2026-09-08) holds any run whose scene came out
    # with no photographs, so a graph test that wants to reach the right
    # half of the graph has to have something attach. These tests are
    # about the gates and the render lanes, not about grounding -- the
    # gate itself is tested in test_reference_gate.py and in
    # test_an_ungrounded_run_is_archived_and_held below. Patched by NAME
    # for the same reason the keyframe is: a miss here would silently
    # change which branch every one of these tests takes.
    attached = []

    def fake_attach(concept_id, extra=None, *, idea=None, db_path=None,
                    account_id=None):
        attached.append(concept_id)
        return [SEED_REF]

    monkeypatch.setattr(orchestrator.scene_chain, "attach_refs", fake_attach)
    calls.keyframes = keyframes
    calls.attached = attached
    return calls


def _save_scene(path, concept, brand):
    """A real row, because the keyframe node reads the concept back out
    of the DB to persist its prompt and attach its still."""
    return preprod.save_concept(concept, brand=brand, spark="test",
                                prompt_template="T", dsn=path, account_id=None)


# ---------- brand defaults to channel: the hold_queue-13 regression ----------
#
# channel decides where a run gets FILED (hold_queue row, autonomy/rate-cap
# row); brand decides which engine actually GENERATES (real cast/locations
# for Antihero, faceless format-driven for Zero Page). These used to default
# independently -- channel="zeropage", brand="antihero" -- so run(goal) or
# run(goal, channel="zeropage") with nothing else silently generated a full
# Antihero concept (real names, real gear) filed under a card labeled
# ZEROPAGE. That's exactly what produced hold_queue row 13 / concept 111 on
# 2026-08-14 -- a manual trigger invocation set --channel without --brand.

def test_run_with_nothing_specified_generates_and_files_under_the_same_brand(tmp_db, monkeypatch):
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    orchestrator.run("gearing up ritual")
    assert calls[0]["brand"] == "zeropage"  # matches the default channel, not "antihero"


def test_run_channel_only_still_generates_the_matching_brand(tmp_db, monkeypatch):
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    orchestrator.run("gearing up ritual", channel="antihero")
    assert calls[0]["brand"] == "antihero"


def test_run_explicit_brand_can_still_disagree_with_channel_on_purpose(tmp_db, monkeypatch, capsys):
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    orchestrator.run("gearing up ritual", channel="zeropage", brand="antihero")
    assert calls[0]["brand"] == "antihero"
    assert "note:" in capsys.readouterr().err  # the mismatch is logged, not silent


def test_the_scene_length_reaches_the_writer_from_the_graph(tmp_db, monkeypatch):
    """2026-09-10: a scene is written to a total length its timed shots
    fill. An explicit `seconds` wins; with none the night reads
    ZEROPAGE_SCENE_SECONDS, like every other posture it runs on."""
    calls = stage_fakes(monkeypatch, [(make_concept(), []), (make_concept(), [])])
    orchestrator.run("gearing up ritual", seconds=15)
    monkeypatch.setenv("ZEROPAGE_SCENE_SECONDS", "20")
    orchestrator.run("gearing up ritual")
    assert [c["seconds"] for c in calls] == [15, 20]


# ---------- the left third: the original loop, preserved ----------

def test_the_keyframe_pairs_each_prompt_with_its_own_shot(monkeypatch):
    """Joined on `n`, never on list position.

    `shots` is re-derived here from state["concept"], which
    revise_prompts rewrites in place, while `prompts` comes off
    state["prompts"] -- two lists built by two filters that agree today.
    A zip() agrees right up until one of them drops a shot the other
    keeps, and then it renders shot A's prompt onto shot B: silently, at
    full cost, with every card in the Queue looking correct.
    """
    monkeypatch.setenv("ZEROPAGE_KEYFRAME", "0")   # no billed image call
    persisted = []
    monkeypatch.setattr(orchestrator.scene_chain, "persist_prompt",
                        lambda cid, n, text, **kw: persisted.append((n, text)))
    monkeypatch.setattr(orchestrator.scene_chain, "plan_timeline",
                        lambda *a, **kw: None)

    orchestrator.keyframe({
        "concept_id": 7,
        "concept": {"shots": [{"n": 1, "prompt": "one"}, {"n": 2, "prompt": "two"}]},
        # deliberately NOT in shot order -- the order a filter or a rework
        # is free to produce, and the one a zip() gets wrong
        "prompts": [{"n": 2, "prompt": "TWO"}, {"n": 1, "prompt": "ONE"}],
    })

    assert persisted == [(1, "ONE"), (2, "TWO")]


def test_the_keyframe_says_so_when_a_shot_has_no_prompt_of_its_own(monkeypatch):
    """Better a named failure on that shot than a neighbour's prompt."""
    monkeypatch.setenv("ZEROPAGE_KEYFRAME", "0")
    persisted = []
    monkeypatch.setattr(orchestrator.scene_chain, "persist_prompt",
                        lambda cid, n, text, **kw: persisted.append((n, text)))
    monkeypatch.setattr(orchestrator.scene_chain, "plan_timeline",
                        lambda *a, **kw: None)

    out = orchestrator.keyframe({
        "concept_id": 7,
        "concept": {"shots": [{"n": 1, "prompt": "one"}, {"n": 2, "prompt": "two"}]},
        "prompts": [{"n": 1, "prompt": "ONE"}],   # shot 2 was filtered out upstream
    })

    assert persisted == [(1, "ONE")], "shot 2 gets nothing rather than shot 1's prompt"
    assert any(k["n"] == 2 and not k["ok"] for k in out["keyframes"])


def test_the_keyframe_still_pairs_when_no_prompt_carries_a_number(monkeypatch):
    """A state written before structure_prompt stamped `n` still runs."""
    monkeypatch.setenv("ZEROPAGE_KEYFRAME", "0")
    persisted = []
    monkeypatch.setattr(orchestrator.scene_chain, "persist_prompt",
                        lambda cid, n, text, **kw: persisted.append((n, text)))
    monkeypatch.setattr(orchestrator.scene_chain, "plan_timeline",
                        lambda *a, **kw: None)

    orchestrator.keyframe({
        "concept_id": 7,
        "concept": {"shots": [{"n": 1, "prompt": "one"}, {"n": 2, "prompt": "two"}]},
        "prompts": [{"prompt": "ONE"}, {"prompt": "TWO"}],
    })

    assert persisted == [(1, "ONE"), (2, "TWO")]


def test_clean_run_keyframes_the_scene_and_parks_it_for_approval(tmp_db, monkeypatch):
    """What a night actually produces (2026-08-29). It used to end
    "no usable clips (render is a dry-run stub)" -- true, and useless:
    it described the stub rather than anything you could judge. Now the
    scored prompt is stored on the shot, a keyframe is attached, and the
    scene waits in the Queue where approving is what spends."""
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("gearing up ritual")

    assert result["attempts"] == 1
    assert result["critique"]["ok"] is True
    # the AI shot's prompt was extracted...
    assert result["prompts"] == [
        {"n": 1, "tool": "KLING", "prompt": GOOD_PROMPT, "still": ""}]
    # ...one still was rendered from it, and the run parks rather than posting
    assert len(calls.keyframes) == 1
    assert calls.keyframes[0]["prompt"] == GOOD_PROMPT
    assert "keyframe rendered" in result["held_reason"]

    # and the scene itself is now waiting where the money gets spent:
    # its prompt stored, its still attached, parked but not picked
    concept = preprod.get_concept(result["concept_id"], dsn=tmp_db, account_id=None)
    shot = concept["shots"][0]
    assert shot["prompt"] == GOOD_PROMPT
    assert shot["reference_image"].startswith("https://cdn/key-")
    assert concept["parked"] is True
    assert concept["picked"] is False
    [row] = autonomy.list_hold(dsn=tmp_db, account_id=None)
    assert row["status"] == "held"
    assert row["concept_id"] == 1
    assert row["payload"]["prompts"][0]["tool"] == "KLING"


def test_structure_prompt_refines_against_technique_references(tmp_db, monkeypatch):
    """The ai_prompting shelf is a separate retrieval from ground_rag's
    (see orchestrator._technique_references) -- give it its own client
    and its own crag stub, keyed off which domain was asked for, so the
    ideation call and the refinement call can't be confused for each other."""
    monkeypatch.setattr(orchestrator, "_client", lambda: object())

    def fake_crag(query, client, model, domain=None, **kwargs):
        if domain == orchestrator.promptgen.REFINE_DOMAIN:
            return {"ok": True, "references": [
                {"source": "cheat-codes.md", "chunk": "start mid-motion, avoid static bookending"}]}
        return {"ok": False, "references": [], "error": "no store in tests"}

    monkeypatch.setattr(orchestrator.crag, "retrieve_with_crag", fake_crag)
    monkeypatch.setattr(orchestrator.promptgen, "generate_with_retry",
                        lambda client, model, prompt, **_: "REFINED: " + GOOD_PROMPT + ", mid-motion start")
    monkeypatch.setattr(orchestrator, "generate_with_retry", lambda *a, **k: "")  # keep stills harmless
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("gearing up ritual")

    assert result["prompts"] == [
        {"n": 1, "tool": "KLING", "prompt": "REFINED: " + GOOD_PROMPT + ", mid-motion start", "still": ""}]


def test_structure_prompt_keeps_the_original_when_the_shelf_is_empty(tmp_db, monkeypatch):
    # default tmp_db fixture stubs crag.retrieve_with_crag to {"ok": False, ...}
    # for every domain, ai_prompting included -- refinement should no-op.
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("gearing up ritual")

    assert result["prompts"] == [
        {"n": 1, "tool": "KLING", "prompt": GOOD_PROMPT, "still": ""}]


def test_warnings_trigger_a_retry_with_feedback_in_the_spark(tmp_db, monkeypatch):
    calls = stage_fakes(monkeypatch, [
        (make_concept(), ["shot 1: unknown location 'rooftop'"]),
        (make_concept(), []),
    ])

    result = orchestrator.run("gearing up ritual")

    assert result["attempts"] == 2
    assert result["critique"]["ok"] is True
    assert "Fix these issues" in calls[1]["spark"]
    assert "rooftop" in calls[1]["spark"]
    assert "Fix these issues" not in (calls[0]["spark"] or "")


def test_out_of_retries_parks_with_the_eval_reason(tmp_db, monkeypatch):
    bad = (make_concept(), ["concept has no shots"])
    stage_fakes(monkeypatch, [bad] * orchestrator.MAX_ATTEMPTS)

    result = orchestrator.run("ritual")

    assert result["attempts"] == orchestrator.MAX_ATTEMPTS
    assert "eval stop" in result["held_reason"]
    assert "concept has no shots" in result["held_reason"]
    [row] = autonomy.list_hold(dsn=tmp_db, account_id=None)
    assert row["status"] == "held"


def test_no_locations_still_generates(tmp_db, monkeypatch):
    """The ensure_locations gate is retired (2026-08-31, Mike's call).

    It parked a run before any generation when the locations table was
    empty -- refusing to think over described rooms the night's own
    generator never reads: build_scene_brief_prompt's placeholders are
    {brand} {cast} {example} {references} {spark}, with no {locations}
    among them. Since every shot is AI-generated, a room is optional
    named material like cast, and an empty table means "nothing filed
    under places yet", not a reason to refuse.

    Uses tmp_db and empties it rather than building a bare database, so
    the run still gets that fixture's no-network patches -- a test that
    reaches ground_rag without them builds a real genai client.
    """
    with db.connect() as conn:
        conn.execute("DELETE FROM locations")
    assert preprod.list_locations(account_id=None) == []
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert calls, "generation never ran with an empty locations table"
    assert "No described locations" not in (result.get("held_reason") or "")


def test_camera_only_concept_parks_with_its_own_reason(tmp_db, monkeypatch):
    camera_only = make_concept(shots=[
        {"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
         "location": "hallway", "desc": "x"},
    ])
    stage_fakes(monkeypatch, [(camera_only, [])])

    result = orchestrator.run("ritual")

    assert result["prompts"] == []
    assert "no AI shots" in result["held_reason"]


# ---------- grounding ----------

def test_ground_entities_uses_only_the_picked_character(tmp_db, monkeypatch):
    mike = entities.add_character("Mike — on camera", role="protagonist", dsn=tmp_db, account_id=None)
    entities.add_character("Guest — bartender", role="guest", dsn=tmp_db, account_id=None)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    # antihero explicitly: this covers picked-vs-default, and Zero Page
    # gets no cast block at all now (see cast_for), which would make the
    # assertion below pass for the wrong reason.
    orchestrator.run("ritual", brand="antihero", channel="antihero",
                     picked_characters=[mike])

    assert "Mike — on camera" in calls[0]["cast"]
    assert "Guest — bartender" not in calls[0]["cast"]


def test_ground_entities_defaults_to_nothing_on_file(tmp_db, monkeypatch):
    """2026-09-03, Mike's call: an unattended run should stay only as
    wide as the spark actually calls for -- it must not default to
    showing the writer every character and prop on file just because
    nobody picked anything. Neither asset has a photo here, so a name
    match wouldn't fire either way; see the sibling test below for that
    half."""
    entities.add_character("Mike — on camera", dsn=tmp_db, account_id=None)
    entities.add_prop("Ducati Panigale V2", category="vehicle", dsn=tmp_db, account_id=None)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual", brand="antihero", channel="antihero")

    assert "Mike — on camera" not in calls[0]["cast"]
    assert "Ducati Panigale V2" not in calls[0]["cast"]


def test_ground_entities_names_an_asset_the_spark_mentions(tmp_db, monkeypatch, tmp_path):
    """With nobody there to pick anything, the spark text itself is the
    only other way an unattended run can reach for a real asset -- the
    same in_scope() rule scene_chain.ground() gives Studio's Create
    button and Director's brief composer."""
    from src import asset_shelf
    dirs = {}
    for kind in ("location", "character", "prop"):
        d = tmp_path / (kind + "s")
        d.mkdir()
        dirs[kind] = d
    monkeypatch.setattr(asset_shelf, "PHOTO_DIRS", dirs)
    entities.add_character("Mike — on camera", dsn=tmp_db, account_id=None)
    (dirs["character"] / "mike--on-camera").mkdir(parents=True)
    (dirs["character"] / "mike--on-camera" / "a.png").write_bytes(b"\x89PNG\r\n")
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("Mike — on camera gears up for the ritual",
                     brand="antihero", channel="antihero")

    assert "Mike — on camera" in calls[0]["cast"]


def test_ground_rag_auto_grounds_only_in_craft_advice_domains(tmp_db, monkeypatch):
    """
    The marketing shelf (platform mechanics, structuring advice) is one
    automatic layer. The STYLE shelves (personal_brand, cinematography)
    stay opt-in via picked_references (narrowed 2026-08-20); performance
    history joined the automatic side 2026-09-02 and has its own tests
    below.
    """
    calls = []

    def fake_crag(query, client, model, domain=None, **kwargs):
        calls.append(domain)
        return {"ok": False, "references": [], "error": "not exercised"}

    monkeypatch.setattr(orchestrator.crag, "retrieve_with_crag", fake_crag)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("gearing up ritual")

    assert orchestrator.shootgen.AUTO_IDEATION_DOMAINS in calls
    assert orchestrator.shootgen.AUTO_IDEATION_DOMAINS == ("marketing",)


def test_ground_rag_auto_pulls_craft_advice_with_nothing_picked(tmp_db, monkeypatch):
    def fake_crag(query, client, model, domain=None, **kwargs):
        if domain == orchestrator.shootgen.AUTO_IDEATION_DOMAINS:
            return {"ok": True, "references": [
                {"source": "short-form-video.md", "chunk": "hook in the first second"}]}
        return {"ok": False, "references": [], "error": "not exercised"}

    monkeypatch.setattr(orchestrator.crag, "retrieve_with_crag", fake_crag)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("gearing up ritual")

    assert "short-form-video.md" in calls[0]["references"]
    assert "hook in the first second" in calls[0]["references"]


def test_ground_rag_pulls_only_the_selected_asset_sources(tmp_db, monkeypatch):
    monkeypatch.setattr(
        orchestrator.rag, "fetch_by_sources",
        lambda sources, **k: (
            {"ok": True, "references": [
                {"source": "brief.txt", "chunk": "still, patient, one move"}]}
            if sources == ["brief.txt"] else {"ok": True, "references": []}
        ),
    )
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual", picked_references=["brief.txt"])

    assert "brief.txt" in calls[0]["references"]
    assert "still, patient, one move" in calls[0]["references"]


def test_ground_rag_never_touches_asset_shelves_with_nothing_picked(tmp_db, monkeypatch):
    # asset grounding is opt-in (2026-08-20): nothing picked means
    # fetch_by_sources is never even called, not just that its result
    # gets discarded. The default tmp_db fixture already fails the
    # crag stub closed, so this also proves no asset text leaks in.
    called = []
    monkeypatch.setattr(
        orchestrator.rag, "fetch_by_sources",
        lambda sources, **k: called.append(sources) or {"ok": True, "references": [
            {"source": "brief.txt", "chunk": "should never surface"}]},
    )
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual")

    assert "brief.txt" not in calls[0]["references"]
    assert called == []


def test_ground_rag_degrades_when_the_asset_store_is_unreachable(tmp_db, monkeypatch):
    monkeypatch.setattr(
        orchestrator.rag, "fetch_by_sources",
        lambda sources, **k: {"ok": False, "references": [], "error": "no store in tests"},
    )
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual", picked_references=["brief.txt"])

    assert "brief.txt" not in calls[0]["references"]


# ---------- the render credit gate + qc ----------

def test_render_stays_dry_without_the_credit_gate(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_RENDER", raising=False)
    called = []
    monkeypatch.setattr(orchestrator, "veo", None, raising=False)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert all(c["ok"] is False and c["url"] is None for c in result["clips"])
    assert called == []


def test_render_gate_open_routes_veo_prompts_through_the_connector(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    clip = tmp_path / "cand1.mp4"
    clip.write_bytes(b"\x00" * 2048)
    from src import veo as veo_module
    calls = []
    monkeypatch.setattr(
        veo_module, "generate_candidates",
        lambda prompt, out_dir, n=1, **k: calls.append(prompt) or
        {"ok": True, "candidates": [{"path": str(clip)}], "error": None},
    )
    monkeypatch.setattr(orchestrator, "_clip_passes_qc", lambda url: bool(url))
    veo_concept = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "VEO",
         "location": "hallway", "desc": "x", "prompt": GOOD_PROMPT},
    ])
    stage_fakes(monkeypatch, [(veo_concept, [])])

    result = orchestrator.run("ritual")

    assert calls == [GOOD_PROMPT]
    assert result["clips"][0]["ok"] is True
    # with a clip through QC, the run reached publish and held for your
    # queue approval -- Zero Page's default posture (DEFAULT_CHANNELS)
    assert "awaiting your approval to post" in result["held_reason"]
    assert "instagram + youtube" in result["held_reason"]


def test_render_gate_open_but_a_tool_with_no_connector_stays_dry(tmp_db, monkeypatch):
    """OPENART is the last platform with a prompt renderer and no
    execution adapter (it has no public API -- see CLAUDE.md), so it is
    what "no adapter wired" now means. This test used to use KLING, which
    stopped being unadapted on 2026-09-08 when fal.py wired it, along with
    LTX, WAN and SEEDANCE."""
    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    concept = make_concept()
    concept["shots"][0]["tool"] = "OPENART"
    stage_fakes(monkeypatch, [(concept, [])])

    result = orchestrator.run("ritual")

    assert result["clips"][0]["ok"] is False
    assert "no adapter" in result["clips"][0]["error"]


def test_an_adapted_tool_with_no_key_stays_dry_but_says_so_honestly(tmp_db, monkeypatch):
    """A KLING shot reaches fal.py now instead of parking as unadapted --
    and with no FAL_KEY and no spend approval in a test run it still costs
    nothing. The difference that matters is the REASON on the card: "not
    configured", something someone can act on, rather than "no adapter
    wired for KLING", which was a standing indictment of the pipeline."""
    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)
    monkeypatch.delenv("FAL_SPEND_OK", raising=False)
    stage_fakes(monkeypatch, [(make_concept(), [])])   # KLING shot

    result = orchestrator.run("ritual")

    clip = result["clips"][0]
    assert clip["ok"] is False
    assert "no adapter" not in clip["error"]
    assert "fal" in clip["error"]


def test_render_failover_switches_to_a_usable_provider_when_the_assigned_one_fails(
    tmp_db, monkeypatch, tmp_path,
):
    """The aggregator registry (providers.py, 2026-09-04) is wired into
    generate_render as a FAILOVER, not a tool-choice override: shootgen
    still names RUNWAY, runway.generate_candidates still runs first and
    still fails on its own here (no key in tests) -- but instead of
    parking the shot, the router's next-best usable provider gets one
    retry, and the clip records which tool actually rendered it."""
    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    from src import providers as providers_module
    from src import veo as veo_module

    clip = tmp_path / "fallback.mp4"
    clip.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(
        veo_module, "generate_candidates",
        lambda prompt, out_dir, n=1, **k:
            {"ok": True, "candidates": [{"path": str(clip)}], "error": None},
    )
    monkeypatch.setattr(providers_module, "choose_provider",
                        lambda account_id, exclude=(): "veo")
    monkeypatch.setattr(orchestrator, "_clip_passes_qc", lambda url: bool(url))
    runway_concept = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
         "location": "hallway", "desc": "x", "prompt": GOOD_PROMPT},
    ])
    stage_fakes(monkeypatch, [(runway_concept, [])])

    result = orchestrator.run("ritual")

    clip_result = result["clips"][0]
    assert clip_result["ok"] is True
    assert clip_result["tool"] == "VEO"
    assert clip_result["failover_from"] == "RUNWAY"


def test_render_failover_leaves_the_original_error_when_nothing_else_is_usable(
    tmp_db, monkeypatch,
):
    """No usable fallback (the router's real usable() check, unmocked --
    no key/spend approval in tests) means the shot parks on the
    ORIGINAL failure's own reason, same as before the registry existed."""
    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    from src import runway as runway_module

    monkeypatch.setattr(
        runway_module, "generate_candidates",
        lambda prompt, out_dir, n=1, **k:
            {"ok": False, "candidates": [], "error": "credit spend not approved"},
    )
    runway_concept = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
         "location": "hallway", "desc": "x", "prompt": GOOD_PROMPT},
    ])
    stage_fakes(monkeypatch, [(runway_concept, [])])

    result = orchestrator.run("ritual")

    clip_result = result["clips"][0]
    assert clip_result["ok"] is False
    assert clip_result["error"] == "credit spend not approved"


def test_qc_rejects_missing_and_tiny_files(tmp_path):
    assert orchestrator._clip_passes_qc(None) is False
    assert orchestrator._clip_passes_qc(str(tmp_path / "nope.mp4")) is False
    tiny = tmp_path / "tiny.mp4"
    tiny.write_bytes(b"x")
    assert orchestrator._clip_passes_qc(str(tiny)) is False


# ---------- human_note: corrections steer the next generation ----------

def test_pending_corrections_steer_once_and_never_touch_the_spark(tmp_db, monkeypatch):
    """Corrections steer the generation and are consumed so each note
    steers exactly once. They ride in `steer`, not `spark` (2026-09-01):
    the spark column is the direction the board prints and _spark_key
    hashes, and a note folded into it made the same idea look new."""
    autonomy.add_correction("less neon, more silence", dsn=tmp_db)
    calls = stage_fakes(monkeypatch, [(make_concept(), []), (make_concept(), [])])

    orchestrator.run("ritual")
    assert "less neon, more silence" in calls[0]["steer"]
    assert "less neon" not in (calls[0]["spark"] or ""), "note leaked into the spark"
    assert autonomy.pending_corrections(dsn=tmp_db) == []   # consumed

    orchestrator.run("ritual")                               # next night
    assert "less neon" not in (calls[1]["steer"] or "")      # steered once


# ---------- the prompt gate (the credit gate) ----------

def test_structural_floor_catches_the_cheap_failures():
    ok, why = orchestrator._structural_check("")
    assert not ok and "too thin" in why
    ok, why = orchestrator._structural_check(
        "a long enough prompt with a leftover {location} token in it "
        "plus more words to clear the length floor easily today")
    assert not ok and "placeholder" in why
    ok, why = orchestrator._structural_check(GOOD_PROMPT)
    assert ok


def test_structural_floor_has_no_upper_length_bound():
    """A long prompt is the judge's call, not the floor's. This layer
    catches broken output; length is a quality judgment, and six of the
    first eight judge failures were too LITTLE detail, not too much."""
    ok, why = orchestrator._structural_check("a door " * 70)   # 140 words
    assert ok and why == ""
    ok, why = orchestrator._structural_check("a door " * 300)  # 600 words
    assert ok and why == ""


# The gate tests below run in HARD mode (ZEROPAGE_GATES=hard), which is
# what they always tested -- the pre-2026-09-07 hold-on-judge behaviour,
# kept as the way back. They are not stale: the whole argument for the
# inversion is that reverting it is one env var, and an untested way back
# is not one. The advisory-mode behaviour they used to describe has its
# own section further down.

def test_thin_prompt_fails_the_floor_without_a_judge_call(tmp_db, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_GATES", "hard")
    judged = []
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: judged.append(p) or {"score": 10, "reason": "", "dims": {}})
    thin = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
         "location": "hallway", "desc": "x", "prompt": "a door"},
    ])
    stage_fakes(monkeypatch, [(thin, [])])

    result = orchestrator.run("ritual")

    assert judged == []                       # layer 1 never billed layer 2
    assert result["prompt_scores"][0]["pass"] is False
    assert "prompt gate" in result["held_reason"]
    assert "too thin" in result["held_reason"]


def test_low_judge_score_holds_with_the_judges_reason(tmp_db, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_GATES", "hard")
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: {"score": 4, "reason": "no camera direction",
                                   "dims": {"camera": 0}})
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["prompt_scores"][0]["pass"] is False
    assert "prompt gate: no camera direction (4/10)" in result["held_reason"]


def test_unreadable_judge_fails_closed(tmp_db, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_GATES", "hard")
    monkeypatch.setattr(orchestrator, "_judge_prompt", REAL_JUDGE_PROMPT)
    # Long enough to clear the structural floor on the rework pass too, but
    # still not JSON -- proves fail-closed survives a rework attempt rather
    # than being masked by the structural check short-circuiting it.
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: (
                            "I think it's pretty good actually, no notes, ship it "
                            "as-is, looks totally fine to me honestly"))
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["prompt_scores"][0]["score"] == 0
    assert "failed closed" in result["prompt_scores"][0]["reason"]
    assert "prompt gate" in result["held_reason"]


def test_a_failed_shot_gets_two_rework_passes_before_holding(tmp_db, monkeypatch):
    """A bad score isn't an automatic hold: the judge already names what's
    weak, so the failing shot earns rewrite passes against that exact
    diagnosis before the whole concept -- including the shot that already
    passed -- gets thrown away over one fixable line. If the rework still
    doesn't clear the bar after MAX_PROMPT_REWORKS attempts, THEN it holds
    (bounded, not infinite) -- raised 1 -> 2 on 2026-09-03: a single generic
    rework attempt was landing on the SAME verdict for the "too many
    sequential actions" failure shape (concept 180 in the live database,
    byte-for-byte identical reason before and after its one rework), so one
    attempt was never enough to prove the mechanism works. (The other half
    of that fix, collapsing a staged prompt to one beat, is gone since
    2026-09-10: timed shots are rendered one by one now -- src/timeline.py
    -- and the rework keeps them.)"""
    monkeypatch.setenv("ZEROPAGE_GATES", "hard")
    scores = iter([
        {"score": 10, "reason": "", "dims": {}},                             # shot 1, first pass
        {"score": 3, "reason": "competing motions", "dims": {"motion": 0}},  # shot 2, first pass
        {"score": 4, "reason": "still ambiguous", "dims": {"motion": 0}},    # shot 2, after rework 1
        {"score": 5, "reason": "still ambiguous", "dims": {"motion": 0}},    # shot 2, after rework 2
    ])
    monkeypatch.setattr(orchestrator, "_judge_prompt", lambda p: next(scores))
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: REWORKED_PROMPT)
    two_ai = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
         "location": "hallway", "desc": "x", "prompt": GOOD_PROMPT},
        {"n": 2, "type": "BROLL", "source": "AI", "tool": "VEO",
         "location": "hallway", "desc": "y", "prompt": GOOD_PROMPT},
    ])
    stage_fakes(monkeypatch, [(two_ai, [])])

    result = orchestrator.run("ritual")

    assert [x["pass"] for x in result["prompt_scores"]] == [True, False]
    # it really got rewritten -- and the scene bible (title/logline/grade)
    # is re-anchored onto it, same as generate_concept prepends up front,
    # so a rework can't quietly drift the shot out of the concept's scene.
    bible = orchestrator.shootgen.derive_scene_bible(
        two_ai["title"], two_ai["logline"], two_ai.get("grade"))
    assert result["prompt_scores"][1]["prompt"] == f"{bible}. {REWORKED_PROMPT}"
    assert result["prompt_rework_attempts"] == 2          # exactly two bounded attempts, not infinite
    assert "still ambiguous" in result["held_reason"]      # no half-rendered credit burn


def test_a_successful_rework_rescues_the_run(tmp_db, monkeypatch):
    """When the rewrite actually fixes the named weakness, the run
    proceeds past the gate instead of holding over a since-fixed
    problem."""
    scores = iter([
        {"score": 10, "reason": "", "dims": {}},
        {"score": 3, "reason": "competing motions", "dims": {"motion": 0}},
        {"score": 8, "reason": "", "dims": {"motion": 2}},   # rework fixed it
    ])
    monkeypatch.setattr(orchestrator, "_judge_prompt", lambda p: next(scores))
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: REWORKED_PROMPT)
    two_ai = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
         "location": "hallway", "desc": "x", "prompt": GOOD_PROMPT},
        {"n": 2, "type": "BROLL", "source": "AI", "tool": "VEO",
         "location": "hallway", "desc": "y", "prompt": GOOD_PROMPT},
    ])
    stage_fakes(monkeypatch, [(two_ai, [])])

    result = orchestrator.run("ritual")

    assert all(x["pass"] for x in result["prompt_scores"])
    bible = orchestrator.shootgen.derive_scene_bible(
        two_ai["title"], two_ai["logline"], two_ai.get("grade"))
    assert result["prompts"][1]["prompt"] == f"{bible}. {REWORKED_PROMPT}"
    # cleared the gate -- now parked only because render is the dry-run
    # stub, not because of the prompt gate
    assert "keyframe rendered" in result["held_reason"]


def test_rework_that_errors_keeps_the_original_score_and_still_holds(tmp_db, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_GATES", "hard")
    """A rework call that blows up (bad JSON, network error, whatever)
    must not crash the run -- it degrades to the original failing score,
    same as every other best-effort seam in this pipeline."""
    scores = iter([{"score": 10, "reason": "", "dims": {}},
                   {"score": 3, "reason": "competing motions", "dims": {"motion": 0}}])
    monkeypatch.setattr(orchestrator, "_judge_prompt", lambda p: next(scores))
    def broken_retry(client, model, contents):
        raise RuntimeError("upstream 503")
    monkeypatch.setattr(orchestrator, "generate_with_retry", broken_retry)
    two_ai = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
         "location": "hallway", "desc": "x", "prompt": GOOD_PROMPT},
        {"n": 2, "type": "BROLL", "source": "AI", "tool": "VEO",
         "location": "hallway", "desc": "y", "prompt": GOOD_PROMPT},
    ])
    stage_fakes(monkeypatch, [(two_ai, [])])

    result = orchestrator.run("ritual")

    assert result["prompt_scores"][1]["prompt"] == GOOD_PROMPT  # unchanged, rework failed
    assert "competing motions" in result["held_reason"]


def test_every_score_is_logged_before_any_credit(tmp_db, monkeypatch):
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    with db.connect(tmp_db) as conn:
        [row] = conn.execute("SELECT * FROM prompt_scores").fetchall()
    assert row["run_id"] == result["run_id"]
    assert row["passed"] == 1
    assert row["human_verdict"] is None       # yours comes later, on /holds
    assert autonomy.first_try_pass_rate(dsn=tmp_db)["rate"] == 1.0


def test_judge_parses_fenced_json_and_clamps_dims():
    class FakeOK:
        pass
    def fake_retry(client, model, contents, **_):
        return 'sure thing:\n```json\n{"subject":2,"camera":9,"motion":-3,' \
               '"lighting":2,"coherence":2,"reason":"camera overclaimed"}\n```'
    import src.orchestrator as o
    orig_retry, orig_client = o.generate_with_retry, o._client
    o.generate_with_retry = fake_retry
    # _judge_prompt builds a real genai.Client() before ever reaching the
    # patched generate_with_retry call; with no GEMINI_API_KEY in the `test`
    # job's env (only `eval-gate` sets one), that construction itself raises,
    # _judge_prompt's fail-closed except swallows it, and dims comes back {}.
    # Stub it out the same way the tmp_db fixture does for every other test.
    o._client = lambda: None
    try:
        verdict = o._judge_prompt("x")
    finally:
        o.generate_with_retry = orig_retry
        o._client = orig_client
    assert verdict["dims"]["camera"] == 2      # clamped to 0..2
    assert verdict["dims"]["motion"] == 0
    assert verdict["score"] == 8


# ---------- the inversion: advisory gates (the default since 2026-09-07) ----------
#
# The measured fact behind all of this: over the graded holds, the prompt
# gate agreed with Mike's own would-post verdict ~38% of the time -- near
# chance -- and no dimension of its rubric separated what he would post
# from what he would not. Predicting the clip from the prompt is the wrong
# lever, so the judges still score, still store, and no longer route; the
# selection moves after the render. What stays hard is everything code
# enforces.

def test_gates_mode_defaults_to_advisory(monkeypatch):
    monkeypatch.delenv("ZEROPAGE_GATES", raising=False)
    assert orchestrator.gates_mode() == orchestrator.GATES_ADVISORY


def test_gates_mode_reads_hard_case_and_whitespace_insensitively(monkeypatch):
    monkeypatch.setenv("ZEROPAGE_GATES", "  HARD ")
    assert orchestrator.gates_mode() == orchestrator.GATES_HARD


def test_a_typo_never_silently_re_arms_the_gate(monkeypatch):
    """Fails toward advisory, deliberately. Every other gate in this
    pipeline fails closed because the cost of being wrong is a spent
    credit; here the cost of being wrong is re-arming a judge that agreed
    with Mike 38% of the time, and "hard" is a decision somebody makes on
    purpose, not something a mistyped env var does to a night."""
    for value in ("hardd", "Hard mode", "1", "true", "strict", ""):
        monkeypatch.setenv("ZEROPAGE_GATES", value)
        assert orchestrator.gates_mode() == orchestrator.GATES_ADVISORY, value


def test_advisory_lets_a_failing_prompt_reach_the_keyframe_with_the_verdict_on_the_card(
        tmp_db, monkeypatch):
    """The whole inversion in one run: a 4/10 prompt still gets its
    bounded rework, still fails, and then gets an image anyway -- with
    the judge's verdict in the parked reason, so /holds shows what the
    gate thought beside the still Mike is actually judging."""
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: {"score": 4, "reason": "no camera direction",
                                   "dims": {"camera": 0}})
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: REWORKED_PROMPT)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["prompt_scores"][0]["pass"] is False          # the judge still says no
    assert len(calls.keyframes) == 1                            # and the still gets rendered
    assert "keyframe rendered" in result["held_reason"]
    assert "advisory: prompt gate 4/10 — no camera direction" in result["held_reason"]
    # the same text is on the scene's own card, not only in the hold row
    concept = preprod.get_concept(result["concept_id"], dsn=tmp_db, account_id=None)
    assert "advisory: prompt gate 4/10" in concept["shots"][0]["park_reason"]


def test_advisory_still_spends_the_bounded_rework_before_it_proceeds(tmp_db, monkeypatch):
    """The rework pass is kept in advisory mode on purpose: it is two
    cheap text calls and it measurably improves the prompt, which is
    worth having whether or not anything is gated on the result."""
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: {"score": 4, "reason": "no camera direction",
                                   "dims": {"camera": 0}})
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: REWORKED_PROMPT)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["prompt_rework_attempts"] == orchestrator.MAX_PROMPT_REWORKS
    assert "keyframe rendered" in result["held_reason"]


def test_advisory_keeps_the_gate_vs_you_number_honest(tmp_db, monkeypatch):
    """The statistic must keep measuring the JUDGE, not the pipeline.

    A run that proceeds through advisory still logs `passed = 0` for the
    shot the gate failed, so `prompt_gate_agreement` compares the gate's
    verdict against the human grade exactly as before. If the row said
    "passed" because the run carried on, gate-vs-you would drift to 100%
    and the evidence that justified the inversion would erase itself."""
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: {"score": 4, "reason": "no camera direction",
                                   "dims": {"camera": 0}})
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: REWORKED_PROMPT)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    with db.connect(tmp_db) as conn:
        rows = conn.execute("SELECT passed FROM prompt_scores ORDER BY id").fetchall()
    assert rows and all(r["passed"] == 0 for r in rows)
    assert autonomy.first_try_pass_rate(dsn=tmp_db)["rate"] == 0.0

    # and the human grade lands next to it, so the disagreement is counted
    autonomy.set_prompt_verdicts(result["run_id"], "post", dsn=tmp_db)
    gate = autonomy.prompt_gate_agreement(dsn=tmp_db)
    assert gate["held_but_posted"] == len(rows)      # the cheap disagreement
    assert gate["agreement"] == 0.0


def test_a_structurally_broken_prompt_still_holds_in_advisory(tmp_db, monkeypatch):
    """Layer 1 is not part of the inversion. `_structural_check` is code
    -- empty, too thin, a leftover {token} -- and a prompt with an
    unfilled placeholder renders garbage whatever the judge thinks of the
    writing. Same line route_after_eval draws around validate_concept's
    warnings: structure is not taste. It still gets its rework first,
    because a rewrite that fills the token is the cheapest possible fix."""
    judged = []
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: judged.append(p) or {"score": 10, "reason": "", "dims": {}})
    # every rework comes back just as broken -- a leftover template token
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: (
                            "a brass door handle turning in a dark {location} at night "
                            "with one warm practical light under the door, film grain"))
    thin = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
         "location": "hallway", "desc": "x", "prompt": "a door"},
    ])
    calls = stage_fakes(monkeypatch, [(thin, [])])

    result = orchestrator.run("ritual")

    assert judged == []                      # layer 1 never billed layer 2
    assert result["prompt_rework_attempts"] == orchestrator.MAX_PROMPT_REWORKS
    assert calls.keyframes == []             # no still for a broken prompt
    assert "prompt gate" in result["held_reason"]
    assert "placeholder" in result["held_reason"]
    # and it isn't dressed up as an advisory note on a run that carried on
    assert result.get("advisory", []) == []


def test_only_the_taste_judge_goes_advisory(tmp_db, monkeypatch):
    """The two layers, side by side, in one mode: a 4/10 rubric verdict
    proceeds to the keyframe, a structurally broken prompt holds."""
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: REWORKED_PROMPT)

    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: {"score": 4, "reason": "no camera direction",
                                   "dims": {"camera": 0}})
    stage_fakes(monkeypatch, [(make_concept(), [])])
    judged_low = orchestrator.run("ritual")

    thin = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
         "location": "hallway", "desc": "x", "prompt": "a door"},
    ])
    # the rework returns something long enough but still not a prompt
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: "TODO " * 40)
    stage_fakes(monkeypatch, [(thin, [])])
    structurally_broken = orchestrator.run("ritual")

    assert "keyframe rendered" in judged_low["held_reason"]
    assert "prompt gate" in structurally_broken["held_reason"]
    assert "keyframe" not in structurally_broken["held_reason"]


def test_a_rework_that_fixes_the_structure_still_reaches_the_keyframe(tmp_db, monkeypatch):
    """The flag follows the CURRENT text, not the run: a prompt that was
    too thin and comes back whole is judged on its merits like any
    other, and a merely low score no longer holds."""
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: {"score": 4, "reason": "no camera direction",
                                   "dims": {"camera": 0}})
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: REWORKED_PROMPT)
    thin = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
         "location": "hallway", "desc": "x", "prompt": "a door"},
    ])
    calls = stage_fakes(monkeypatch, [(thin, [])])

    result = orchestrator.run("ritual")

    assert result["prompt_scores"][0].get("structural") is None   # rebuilt, not inherited
    assert len(calls.keyframes) == 1
    assert "advisory: prompt gate 4/10 — no camera direction" in result["held_reason"]


def test_advisory_still_holds_a_camera_only_concept(tmp_db, monkeypatch):
    """Nothing to keyframe, nothing to render -- that hold is code, not
    taste, so the inversion leaves it exactly where it was."""
    camera_only = make_concept(shots=[
        {"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
         "location": "hallway", "desc": "x"},
    ])
    calls = stage_fakes(monkeypatch, [(camera_only, [])])

    result = orchestrator.run("ritual")

    assert result["prompts"] == []
    assert calls.keyframes == []
    assert "no AI shots" in result["held_reason"]


def test_advisory_still_retries_and_holds_on_code_enforced_warnings(tmp_db, monkeypatch):
    """`warnings` is validate_concept's, not a judge's: a shot naming a
    room that doesn't exist is broken output. It retries in both modes,
    and still holds when the retries run out."""
    bad = (make_concept(), ["shot 1: unknown location 'rooftop'"])
    calls = stage_fakes(monkeypatch, [bad] * orchestrator.MAX_ATTEMPTS)

    result = orchestrator.run("ritual")

    assert result["attempts"] == orchestrator.MAX_ATTEMPTS
    assert calls.keyframes == []
    assert "eval stop" in result["held_reason"]


def test_a_low_concept_judge_score_alone_no_longer_holds(tmp_db, monkeypatch):
    """The other half of route_after_eval: with JUDGE=1 and no warnings,
    a failing LLM verdict is recorded in `critique` and carried onto the
    card, and the run goes on."""
    monkeypatch.setenv("JUDGE", "1")
    monkeypatch.setattr(orchestrator, "_judge",
                        lambda concept: (0.1, ["needs a crew"]))
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["attempts"] == 1                     # no corrective re-run
    assert result["critique"]["ok"] is False           # the verdict is unchanged
    assert result["critique"]["issues"] == ["needs a crew"]
    assert len(calls.keyframes) == 1
    assert "advisory: concept judge" in result["held_reason"]
    assert "needs a crew" in result["held_reason"]


def test_hard_mode_still_retries_and_holds_on_a_low_concept_judge_score(tmp_db, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_GATES", "hard")
    monkeypatch.setenv("JUDGE", "1")
    monkeypatch.setattr(orchestrator, "_judge",
                        lambda concept: (0.1, ["needs a crew"]))
    calls = stage_fakes(monkeypatch, [(make_concept(), [])] * orchestrator.MAX_ATTEMPTS)

    result = orchestrator.run("ritual")

    assert result["attempts"] == orchestrator.MAX_ATTEMPTS
    assert calls.keyframes == []
    assert "eval stop" in result["held_reason"]
    assert "needs a crew" in result["held_reason"]


def test_the_advisory_verdicts_reach_the_hold_payload(tmp_db, monkeypatch):
    """Nothing is lost for the grade queue: the payload is the replayable
    record of a run, and a gate that stops routing must not also stop
    being visible."""
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: {"score": 4, "reason": "no camera direction",
                                   "dims": {"camera": 0}})
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: REWORKED_PROMPT)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual")

    [row] = autonomy.list_hold(dsn=tmp_db, account_id=None)
    assert row["payload"]["advisory"] == [
        "advisory: prompt gate 4/10 — no camera direction"]
    assert row["payload"]["prompt_scores"][0]["pass"] is False


def test_a_rework_replaces_its_own_advisory_note_rather_than_stacking_one(
        tmp_db, monkeypatch):
    """Two contradictory lines on one card is worse than none, so the
    latest verdict replaces the previous one."""
    scores = iter([
        {"score": 3, "reason": "competing motions", "dims": {"motion": 0}},
        {"score": 5, "reason": "still ambiguous", "dims": {"motion": 1}},
        {"score": 6, "reason": "still ambiguous", "dims": {"motion": 1}},
    ])
    monkeypatch.setattr(orchestrator, "_judge_prompt", lambda p: next(scores))
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents, **_: REWORKED_PROMPT)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["advisory"] == ["advisory: prompt gate 6/10 — still ambiguous"]
    assert "competing motions" not in result["held_reason"]


# ---------- select_clip: the selection, moved after the render ----------

def _fake_clip(tmp_path, name, size, ok=True):
    path = tmp_path / name
    path.write_bytes(b"0" * size)
    return {"tool": "RUNWAY", "prompt": "p", "url": str(path), "ok": ok}


def test_select_clip_is_a_no_op_on_one_clip(tmp_path):
    one = [_fake_clip(tmp_path, "a.mp4", 2048)]
    out = orchestrator.select_clip({"clips": one})
    assert out == {"clip_candidates": one}       # clips untouched, nothing chosen


def test_select_clip_prefers_the_longest_and_keeps_every_candidate(tmp_path, monkeypatch):
    """Duration outranks size deliberately: a short render is usually a
    generation that gave up early, while a big file is often just a
    noisier one."""
    short_big = _fake_clip(tmp_path, "a.mp4", 4096)
    long_small = _fake_clip(tmp_path, "b.mp4", 1024)
    monkeypatch.setattr(orchestrator, "_clip_duration",
                        lambda url: 6.0 if url.endswith("b.mp4") else 2.0)

    out = orchestrator.select_clip({"clips": [short_big, long_small]})

    assert out["clips"] == [long_small]
    assert out["clip_candidates"] == [short_big, long_small]   # the losers survive


def test_select_clip_breaks_a_duration_tie_on_size(tmp_path, monkeypatch):
    small = _fake_clip(tmp_path, "a.mp4", 1024)
    big = _fake_clip(tmp_path, "b.mp4", 8192)
    monkeypatch.setattr(orchestrator, "_clip_duration", lambda url: 4.0)

    out = orchestrator.select_clip({"clips": [small, big]})

    assert out["clips"] == [big]


def test_select_clip_never_picks_a_clip_that_failed_qc(tmp_path, monkeypatch):
    """QC is code and it comes first: a file that isn't a video can't be
    the pick however long it claims to be."""
    failed = _fake_clip(tmp_path, "a.mp4", 8192, ok=False)
    passed = _fake_clip(tmp_path, "b.mp4", 1024)
    monkeypatch.setattr(orchestrator, "_clip_duration",
                        lambda url: 30.0 if url.endswith("a.mp4") else 1.0)

    out = orchestrator.select_clip({"clips": [failed, passed]})

    assert out["clips"] == [passed]


def test_a_video_judge_can_take_over_the_pick(tmp_path, monkeypatch):
    """The documented seam for the model that can actually answer the
    question the prompt gate was guessing at."""
    first = _fake_clip(tmp_path, "a.mp4", 1024)
    second = _fake_clip(tmp_path, "b.mp4", 8192)
    monkeypatch.setattr(orchestrator, "_clip_duration", lambda url: 4.0)
    seen = []

    def judge(candidates):
        seen.append(list(candidates))
        return candidates[0]                       # not what the heuristic would pick

    monkeypatch.setattr(orchestrator, "JUDGE", judge)

    out = orchestrator.select_clip({"clips": [first, second]})

    assert out["clips"] == [first]
    assert len(seen[0]) == 2                       # it sees every candidate


def test_a_broken_video_judge_loses_its_say_rather_than_the_run(tmp_path, monkeypatch, capsys):
    first = _fake_clip(tmp_path, "a.mp4", 1024)
    second = _fake_clip(tmp_path, "b.mp4", 8192)
    monkeypatch.setattr(orchestrator, "_clip_duration", lambda url: 4.0)

    def judge(candidates):
        raise RuntimeError("upstream 503")

    monkeypatch.setattr(orchestrator, "JUDGE", judge)

    out = orchestrator.select_clip({"clips": [first, second]})

    assert out["clips"] == [second]                 # the code pick stands
    assert "clip judge failed" in capsys.readouterr().err


def test_a_video_judge_answering_off_the_menu_is_ignored(tmp_path, monkeypatch, capsys):
    first = _fake_clip(tmp_path, "a.mp4", 1024)
    second = _fake_clip(tmp_path, "b.mp4", 8192)
    monkeypatch.setattr(orchestrator, "_clip_duration", lambda url: 4.0)
    monkeypatch.setattr(orchestrator, "JUDGE",
                        lambda candidates: {"url": "/somewhere/else.mp4", "ok": True})

    out = orchestrator.select_clip({"clips": [first, second]})

    assert out["clips"] == [second]
    assert "not one of the candidates" in capsys.readouterr().err


def test_select_clip_sits_between_qc_and_caption(tmp_db):
    """Wired, not just defined -- a node nothing routes through is a
    function with a docstring."""
    graph = orchestrator.GRAPH.get_graph()
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("qc_clip", "select_clip") in edges
    assert ("select_clip", "caption") in edges
    assert ("qc_clip", "caption") not in edges


# ---------- the publish gates (driven directly; render stub blocks the wire) ----------

def ready_state(tmp_db, channel="zeropage", **overrides):
    state = {
        "channel": channel,
        "concept": make_concept(),
        "concept_id": 1,
        "prompts": [{"tool": "KLING", "prompt": "p"}],
        "clips": [{"tool": "KLING", "prompt": "p", "url": "file:///clip.mp4", "ok": True}],
        "caption": "a caption",
    }
    state.update(overrides)
    return state


def test_publish_holds_when_killed(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    autonomy.kill("bad night", dsn=tmp_db)

    result = orchestrator.publish(ready_state(tmp_db))

    assert "kill switch" in result["held_reason"]


def test_publish_shadow_holds_for_grading(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    # antihero is the channel that defaults to shadow (zeropage now
    # defaults to queue -- see DEFAULT_CHANNELS)
    result = orchestrator.publish(ready_state(tmp_db, channel="antihero"))
    assert "shadow" in result["held_reason"]


def test_publish_queue_holds_for_approval(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    autonomy.set_autonomy("zeropage", "queue", dsn=tmp_db)
    result = orchestrator.publish(ready_state(tmp_db))
    assert "awaiting your approval" in result["held_reason"]


def test_publish_auto_still_parks_because_no_api_is_wired(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    autonomy.set_autonomy("zeropage", "auto", dsn=tmp_db)
    result = orchestrator.publish(ready_state(tmp_db))
    assert "posting adapter not wired" in result["held_reason"]
    assert "instagram + youtube" in result["held_reason"]


def test_post_gate_rejects_failed_qc_empty_caption_and_warnings(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    bad_clip = ready_state(tmp_db, clips=[{"ok": False, "url": None}])
    assert "clip QC failed" in orchestrator.publish(bad_clip)["held_reason"]

    no_caption = ready_state(tmp_db, caption="  ")
    assert "caption is empty" in orchestrator.publish(no_caption)["held_reason"]

    warned = ready_state(tmp_db, concept=make_concept(warnings=["shot 1: bad room"]))
    assert "concept carries warnings" in orchestrator.publish(warned)["held_reason"]


def test_post_gate_enforces_the_rate_cap(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    autonomy.to_hold("zeropage", "already posted", status="posted", dsn=tmp_db, account_id=None)

    result = orchestrator.publish(ready_state(tmp_db))

    assert "rate cap" in result["held_reason"]


def test_every_shot_with_a_prompt_is_ai_eligible(tmp_db, monkeypatch):
    """The all-AI move (2026-08-20): source == "CAMERA" now means Michael
    captures reference material that anchors the generation, not that the
    shot escapes the pipeline. A camera-source shot carrying a prompt is
    structured and scored like any other; its real capture rides along to
    the hold card, and the Midjourney still is skipped -- the capture IS
    the anchor frame a still would otherwise have to invent."""
    # an explicit two-shot concept: gen_concept writes one-scene concepts
    # now, but a legacy row still has to structure and score correctly
    concept = make_concept(shots=[
        {"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
         "location": "hallway", "desc": "low angle, he steps into frame",
         "prompt": GOOD_PROMPT, "tool": "SEEDANCE",
         "reference_image": "https://cdn.example/take.jpg"},
        {"n": 2, "type": "BROLL", "source": "AI", "tool": "KLING",
         "location": "hallway", "desc": "the handle turns on its own",
         "prompt": GOOD_PROMPT},
    ])
    stage_fakes(monkeypatch, [(concept, [])])

    result = orchestrator.run("gearing up ritual")

    assert [p["tool"] for p in result["prompts"]] == ["SEEDANCE", "KLING"]
    anchored, plain = result["prompts"]
    assert anchored["reference_image"] == "https://cdn.example/take.jpg"
    assert anchored["still"] == ""
    # a shot with no capture carries no key at all, same as the shot dict
    assert "reference_image" not in plain
    # the capture reaches the hold card next to the prompt it anchors
    [row] = autonomy.list_hold(dsn=tmp_db, account_id=None)
    assert row["payload"]["prompts"][0]["reference_image"] == "https://cdn.example/take.jpg"
    scores = row["payload"].get("prompt_scores") or []
    if scores:
        assert scores[0].get("reference_image") == "https://cdn.example/take.jpg"


def test_a_shot_with_no_prompt_still_drops_out(tmp_db, monkeypatch):
    """No prompt means there is nothing to structure -- the default
    make_concept camera shot has no prompt yet, so only the AI shot
    lands in prompts (this is the old filter's surviving half)."""
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("gearing up ritual")

    assert [p["tool"] for p in result["prompts"]] == ["KLING"]


# --- the on-brand gate actually gets fed (2026-08-31) -----------------------
#
# uncanny_judge.py was written, tested, and never called from src/ or app/ --
# only from tests. autopilot.plan reads the verdict it was meant to write
# ("the gate fails closed, so unjudged == held"), so every Zero Page concept
# was permanently ineligible to auto-post and the pipeline never posted
# anything. These pin the wire, because the failure mode is silence.

def _judge_spy(monkeypatch, passed=True):
    calls = []

    def fake(concept, gemini_client=None):
        calls.append(concept.get("title"))
        return {"overall": 9.0 if passed else 3.0, "passed": passed,
                "reasons": [], "graded": True, "uncanny_hook": 9.0,
                "grounded": 9.0, "format_fit": 9.0, "faceless": 9.0}

    monkeypatch.setattr(orchestrator.uncanny_judge, "score_concept", fake)
    return calls


def test_a_zeropage_run_leaves_the_concept_judged(tmp_db, monkeypatch):
    """The autopilot cannot auto-post an unjudged concept. If this stops
    passing, nothing Zero Page generates can ever reach an audience."""
    calls = _judge_spy(monkeypatch)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual", brand="zeropage", channel="zeropage")

    assert calls, "the uncanny judge was never called"
    row = preprod.get_concept(result["concept_id"], account_id=None)
    assert row["uncanny_passed"], "the verdict never reached the row autopilot reads"


def test_antihero_never_pays_for_the_gate(tmp_db, monkeypatch):
    """Antihero is review-gated forever and never enters an auto-post
    plan, so judging it is spend on a number nothing reads."""
    calls = _judge_spy(monkeypatch)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual", brand="antihero", channel="antihero")

    assert calls == []


def test_a_failed_verdict_does_not_park_the_run(tmp_db, monkeypatch):
    """brand_gate records, it never routes. A concept that misses the
    brand is still worth keeping and learning from -- parking it here
    would destroy the negative signal the grade queue exists for."""
    _judge_spy(monkeypatch, passed=False)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual", brand="zeropage", channel="zeropage")

    assert result["concept_id"], "a failed brand verdict stopped the run"
    row = preprod.get_concept(result["concept_id"], account_id=None)
    assert row["uncanny_passed"] == 0


def test_a_broken_judge_leaves_the_concept_unjudged(tmp_db, monkeypatch):
    """Fails CLOSED and loudly. An exception here must not take the run
    down, and must not silently mark the concept post-eligible."""
    def boom(concept, gemini_client=None):
        raise RuntimeError("judge is down")

    monkeypatch.setattr(orchestrator.uncanny_judge, "score_concept", boom)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual", brand="zeropage", channel="zeropage")

    row = preprod.get_concept(result["concept_id"], account_id=None)
    assert not row["uncanny_passed"]


# ---------- a scouted night arrives with its photographs --------------------
#
# The half of the research contract that was wired at both ends and
# connected in the middle by nothing. `orchestrator.scout` returned the
# spark alone, so `reference_photos` was empty on every unattended run:
# the crawl downloaded images into data/refs, banked them against the
# finding, and no concept the graph wrote could see one. Every scene
# generated on 2026-09-01 (concepts 141-148) came back grounded on the
# same five asset-bank photos of the cast whatever direction it ran on --
# research reached the WORDS of the prompt and never the pictures.

def test_a_scouted_run_writes_the_scene_from_the_images_it_researched(
        tmp_db, monkeypatch, tmp_path):
    from src import asset_shelf, refbin, scene_chain, scout

    # Captured BEFORE stage_fakes stubs it out -- reading it afterwards
    # off the module hands back the stub, which is how the first attempt
    # at this "restore" quietly restored the fake onto itself.
    real_attach_refs = scene_chain.attach_refs

    monkeypatch.setattr(refbin, "REFS_DIR", tmp_path / "refs")
    # an empty asset bank on disk: this scene names nothing, so the only
    # references it can possibly get are the researched ones
    monkeypatch.setattr(asset_shelf, "PHOTO_DIRS",
                        {kind: tmp_path / plural for kind, plural in
                         (("character", "characters"), ("prop", "props"),
                          ("location", "locations"))})
    jpeg = b"\xff\xd8\xff" + b"a banked frame"
    banked = refbin.save(jpeg)

    scout.record("zeropage", {"spark": "a hand already on the handle",
                              "score": 0.9}, pass_id="p", dsn=tmp_db)
    scout.bin_add("zeropage", "p", banked,
                  source_url="https://example.com/post", dsn=tmp_db)

    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    # THIS test is the one that needs the real attacher: stage_fakes
    # stubs attach_refs out (it returns SEED_REF and writes nothing) so
    # the other graph tests clear the reference gate without a bank, and
    # with the stub in place the assertion below reads a shot nothing
    # ever attached to -- a KeyError, not a grounding failure.
    monkeypatch.setattr(orchestrator.scene_chain, "attach_refs",
                        real_attach_refs)
    out = orchestrator.run("the rotation", brand="zeropage", channel="zeropage",
                           scout=True)

    assert out["spark"] == "a hand already on the handle"
    # the WRITER saw the photograph, rather than being told one existed
    assert calls[0]["image_refs"], \
        "the scene was written from the spark's words and none of its images"
    data, _mime, _label = calls[0]["image_refs"][0]
    assert data == jpeg
    # and it landed on the shot, which is what the keyframe and clip read
    assert banked in preprod.get_concept(
        out["concept_id"], dsn=tmp_db, account_id=None)["shots"][0]["refs"]


def test_a_rotation_night_is_untouched_by_any_of_this(tmp_db, monkeypatch):
    """A run that did not ask to scout must reach the writer exactly as
    it always did -- no bank read, no photographs, no change."""
    from src import scout

    scout.record("zeropage", {"spark": "a crawled idea", "score": 0.99},
                 pass_id="p", dsn=tmp_db)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    out = orchestrator.run("the last check before leaving", brand="zeropage",
                           channel="zeropage")

    assert out["spark"] == "the last check before leaving"
    assert calls[0]["image_refs"] == []


# --- which brain the NIGHT writes with (2026-09-09) --------------------------
# The composer's picker and the walk share one table (gemini_utils.BRAINS)
# and deliberately not one default. A walk is NIGHTLY_SPARKS x 2 brands =
# 10 runs, so the expensive tier has to be something somebody turns on.

def test_the_night_writes_on_the_fast_tier_unless_told_otherwise(tmp_db, monkeypatch):
    from src import gemini_utils

    monkeypatch.delenv("ZEROPAGE_BRAIN", raising=False)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    orchestrator.run("a spark", brand="zeropage", channel="zeropage")
    assert calls[0]["brain"] == gemini_utils.DEFAULT_BRAIN == "fast"


def test_a_walk_can_be_put_on_the_reasoning_tier_on_purpose(tmp_db, monkeypatch):
    """Two doors, and both are deliberate acts: the env var for the cron
    box, an explicit argument for a caller that named one."""
    monkeypatch.setenv("ZEROPAGE_BRAIN", "reasoning")
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    orchestrator.run("a spark", brand="zeropage", channel="zeropage")
    assert calls[0]["brain"] == "reasoning"

    monkeypatch.delenv("ZEROPAGE_BRAIN", raising=False)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    orchestrator.run("a spark", brand="zeropage", channel="zeropage",
                     brain="reasoning")
    assert calls[0]["brain"] == "reasoning"


def test_a_typo_in_the_env_var_does_not_lose_the_night(tmp_db, monkeypatch):
    """Nobody is watching at 3:30am, and brain_default is read there."""
    monkeypatch.setenv("ZEROPAGE_BRAIN", "resoning")
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    orchestrator.run("a spark", brand="zeropage", channel="zeropage")
    assert calls[0]["brain"] == "fast"


def test_avoid_guidance_steers_without_becoming_the_spark(tmp_db, monkeypatch):
    """The spark column is the DIRECTION, not the scaffolding (2026-09-01).

    gen_concept used to concatenate winners.avoid_guidance onto `spark`
    and pass one string, which the generator then stored -- so every
    graph-written row carried ~1500 characters of craft notes in the
    column the board prints, archive_batch groups by, and
    scout._spark_key hashes. Novelty detection compared the notes along
    with the idea, so the same direction on a night with a different
    avoid-list looked new. The advice still has to REACH the model,
    which is why this checks both halves.
    """
    monkeypatch.setattr(orchestrator.winners, "avoid_guidance",
                        lambda **k: "AVOID: no glossy CGI")
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("a routine performed wrong", brand="zeropage",
                     channel="zeropage")

    [call] = calls
    assert call["spark"] == "a routine performed wrong", \
        "the avoid block leaked back into the stored spark"
    assert "AVOID: no glossy CGI" in call["steer"], \
        "the advice stopped reaching the model"


def test_a_zeropage_run_is_handed_no_cast(tmp_db, monkeypatch):
    """The faceless brand must not be told to name a recurring person.

    Every Zero Page concept on the board named Michael, Cyclops or the
    Ducati, because ground_entities handed the shared {cast} socket every
    asset on file regardless of brand — and that socket says "reference
    the uploaded photos as the EXACT face ... name them", flatly against
    concept_zeropage.txt's "FACELESS -- no recurring person".
    """
    entities.add_character("Mike — on camera", dsn=tmp_db, account_id=None)
    entities.add_prop("Ducati Panigale V2", category="vehicle", dsn=tmp_db,
                      account_id=None)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual", brand="zeropage", channel="zeropage")

    assert calls[0]["cast"] == "", "the faceless brand was handed a cast"


def test_run_with_a_finding_id_claims_it_under_this_runs_id(tmp_db, monkeypatch):
    """The MCP door names the finding instead of asking the scout node
    to choose one; planner must still stamp it used, or the same spark
    is served again tomorrow with its photographs."""
    from src import scout
    scout.init(tmp_db)
    fid = scout.record("zeropage", {"spark": "gearing up ritual", "score": 0.9}, dsn=tmp_db)
    stage_fakes(monkeypatch, [(make_concept(), [])])
    result = orchestrator.run("gearing up ritual", scout_finding_id=fid)
    assert result.get("scout_finding_id") == fid
    row = scout.get_finding(fid, dsn=tmp_db)
    assert row["used_at"] and row["run_id"] == result["run_id"]


# --- performance history grounds every run (Mike, 2026-09-02) ---------------
#
# proven_results and winning_prompts sat in the opt-in set, which made them
# dead on the only path that matters: an unattended run picks nothing, so
# fetch_by_sources was never called, so no nightly concept was ever written
# against what actually travelled. refresh_metrics -> promote_winners -> RAG
# filled the shelf every morning and nothing read it.

def test_performance_history_is_pulled_with_nothing_picked(tmp_db, monkeypatch):
    def fake_crag(query, client, model, domain=None, **kwargs):
        if domain == orchestrator.shootgen.PERFORMANCE_DOMAINS:
            return {"ok": True, "references": [
                {"source": "proven_results/video-42.txt",
                 "chunk": "the loop cut on the wrong beat -- 4.1x median"}]}
        return {"ok": False, "references": [], "error": "not exercised"}

    monkeypatch.setattr(orchestrator.crag, "retrieve_with_crag", fake_crag)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("gearing up ritual")          # nothing picked

    assert "proven_results/video-42.txt" in calls[0]["references"]
    assert "4.1x median" in calls[0]["references"]


def test_performance_history_is_evidence_not_style(tmp_db, monkeypatch):
    """Only the two evidence shelves went automatic. Voice and look are
    still a person's choice, so they must not ride along."""
    assert orchestrator.shootgen.PERFORMANCE_DOMAINS == (
        "proven_results", "winning_prompts")
    for style in ("personal_brand", "cinematography"):
        assert style not in orchestrator.shootgen.PERFORMANCE_DOMAINS
        assert style in orchestrator.shootgen.ASSET_IDEATION_DOMAINS


def test_both_automatic_layers_are_retrieved_separately(tmp_db, monkeypatch):
    """Craft and performance are two retrievals, not one query against a
    merged shelf: "how do videos travel" and "how did OURS travel" are
    different questions and rank differently."""
    domains = []

    def fake_crag(query, client, model, domain=None, **kwargs):
        domains.append(domain)
        return {"ok": False, "references": [], "error": "not exercised"}

    monkeypatch.setattr(orchestrator.crag, "retrieve_with_crag", fake_crag)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("gearing up ritual")

    assert orchestrator.shootgen.AUTO_IDEATION_DOMAINS in domains
    assert orchestrator.shootgen.PERFORMANCE_DOMAINS in domains


def test_a_dead_performance_shelf_still_generates(tmp_db, monkeypatch):
    """Same never-raises contract as the craft layer: an unreachable store
    means this layer contributes nothing, never a crash."""
    def fake_crag(query, client, model, domain=None, **kwargs):
        if domain == orchestrator.shootgen.PERFORMANCE_DOMAINS:
            raise RuntimeError("this must never reach the caller")
        return {"ok": False, "references": [], "error": "not exercised"}

    monkeypatch.setattr(
        orchestrator.crag, "retrieve_with_crag",
        lambda *a, **k: {"ok": False, "references": [], "error": "no store"})
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual")

    assert calls, "the run must still produce a concept"


# ---------- the nightly render bills the account that asked for it ----------

def _one_prompt_state(account_id):
    return {"concept_id": 7, "account_id": account_id,
            "prompts": [{"n": 1, "tool": "RUNWAY", "prompt": GOOD_PROMPT}]}


def test_the_nightly_render_carries_the_owner_into_the_connector(monkeypatch):
    """generate_render read account_id off the state and handed it to
    choose_provider, then called the connector WITHOUT it -- so every
    nightly clip wrote generations.account_id = NULL, counted its cap
    against the unowned pool rather than this account's, and resolved
    the provider key from the environment even for an account with its
    own stored one (BYOK). The owner has to reach the call that spends
    the money, not only the one that picks who spends it.
    """
    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    from src import runway as runway_module

    seen = {}

    def fake_candidates(prompt, out_dir, n=1, **kwargs):
        seen.update(kwargs)
        return {"ok": False, "candidates": [], "error": "no key in tests"}

    monkeypatch.setattr(runway_module, "generate_candidates", fake_candidates)
    monkeypatch.setattr("src.providers.choose_provider",
                        lambda account_id=None, **k: None)

    orchestrator.generate_render(_one_prompt_state(42))

    assert seen.get("account_id") == 42, (
        "the assigned connector was called with account_id="
        f"{seen.get('account_id')!r} -- the clip is billed to nobody")


def test_the_failover_render_carries_the_owner_too(monkeypatch, tmp_path):
    """The retry through the registry spends exactly as much money as
    the first attempt, so it needs exactly as much ownership."""
    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    from src import providers as providers_module
    from src import runway as runway_module
    from src import veo as veo_module

    clip = tmp_path / "fallback.mp4"
    clip.write_bytes(b"\x00" * 2048)
    seen = {}

    def fake_veo(prompt, out_dir, n=1, **kwargs):
        seen.update(kwargs)
        return {"ok": True, "candidates": [{"path": str(clip)}], "error": None}

    monkeypatch.setattr(
        runway_module, "generate_candidates",
        lambda prompt, out_dir, n=1, **k: {"ok": False, "candidates": [],
                                           "error": "no key in tests"})
    monkeypatch.setattr(veo_module, "generate_candidates", fake_veo)
    monkeypatch.setattr(providers_module, "choose_provider",
                        lambda account_id=None, exclude=(), db_path=None: "veo")

    orchestrator.generate_render(_one_prompt_state(42))

    assert seen.get("account_id") == 42, (
        "the failover connector was called with account_id="
        f"{seen.get('account_id')!r} -- the retry is billed to nobody")
