"""
Tests for src/orchestrator.py -- the autonomous content graph.

Hermetic: the billed seams (shootgen.generate_concept, CRAG retrieval,
scheduling.build_caption, the judge client) are patched at their
modules; entities/locations/autonomy run against a throwaway SQLite
file via db.DB_PATH. Every graph test drives the compiled GRAPH through
run(), so the edges and all three conditionals are exercised. The
publish gates are driven directly -- with generate_render a dry-run
stub, the wired graph can't reach publish until renders are real, and
the gate logic still has to be right before that day.
"""
import pytest

from src import autonomy, db, entities, orchestrator, preprod


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """The orchestrator's nodes read db.DB_PATH directly (same as the web
    routes), so point it at a throwaway database."""
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    autonomy.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    preprod.add_location("hallway", {"space": "narrow hallway"}, photo_count=2, path=path, account_id=None)
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
                      image_refs=None, account_id=None):
        calls.append({"brand": brand, "spark": spark, "steer": steer,
                      "references": references,
                      "cast": cast, "image_refs": list(image_refs or [])})
        concept, warnings = queue.pop(0)
        concept_id = _save_scene(db.DB_PATH, concept, brand)
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
    calls.keyframes = keyframes
    return calls


def _save_scene(path, concept, brand):
    """A real row, because the keyframe node reads the concept back out
    of the DB to persist its prompt and attach its still."""
    return preprod.save_concept(concept, brand=brand, spark="test",
                                prompt_template="T", path=path, account_id=None)


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


# ---------- the left third: the original loop, preserved ----------

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
        {"tool": "KLING", "prompt": GOOD_PROMPT, "still": ""}]
    # ...one still was rendered from it, and the run parks rather than posting
    assert len(calls.keyframes) == 1
    assert calls.keyframes[0]["prompt"] == GOOD_PROMPT
    assert "keyframe rendered" in result["held_reason"]

    # and the scene itself is now waiting where the money gets spent:
    # its prompt stored, its still attached, parked but not picked
    concept = preprod.get_concept(result["concept_id"], path=tmp_db, account_id=None)
    shot = concept["shots"][0]
    assert shot["prompt"] == GOOD_PROMPT
    assert shot["reference_image"].startswith("https://cdn/key-")
    assert concept["parked"] is True
    assert concept["picked"] is False
    [row] = autonomy.list_hold(path=tmp_db, account_id=None)
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
                        lambda client, model, prompt: "REFINED: " + GOOD_PROMPT + ", mid-motion start")
    monkeypatch.setattr(orchestrator, "generate_with_retry", lambda *a, **k: "")  # keep stills harmless
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("gearing up ritual")

    assert result["prompts"] == [
        {"tool": "KLING", "prompt": "REFINED: " + GOOD_PROMPT + ", mid-motion start", "still": ""}]


def test_structure_prompt_keeps_the_original_when_the_shelf_is_empty(tmp_db, monkeypatch):
    # default tmp_db fixture stubs crag.retrieve_with_crag to {"ok": False, ...}
    # for every domain, ai_prompting included -- refinement should no-op.
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("gearing up ritual")

    assert result["prompts"] == [
        {"tool": "KLING", "prompt": GOOD_PROMPT, "still": ""}]


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
    [row] = autonomy.list_hold(path=tmp_db, account_id=None)
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
    with db.connect(db.DB_PATH) as conn:
        conn.execute("DELETE FROM locations")
    assert preprod.list_locations(path=db.DB_PATH, account_id=None) == []
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
    mike = entities.add_character("Mike — on camera", role="protagonist", path=tmp_db, account_id=None)
    entities.add_character("Guest — bartender", role="guest", path=tmp_db, account_id=None)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    # antihero explicitly: this covers picked-vs-default, and Zero Page
    # gets no cast block at all now (see cast_for), which would make the
    # assertion below pass for the wrong reason.
    orchestrator.run("ritual", brand="antihero", channel="antihero",
                     picked_characters=[mike])

    assert "Mike — on camera" in calls[0]["cast"]
    assert "Guest — bartender" not in calls[0]["cast"]


def test_ground_entities_defaults_to_everything_on_file(tmp_db, monkeypatch):
    entities.add_character("Mike — on camera", path=tmp_db, account_id=None)
    entities.add_prop("Ducati Panigale V2", category="vehicle", path=tmp_db, account_id=None)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual", brand="antihero", channel="antihero")

    assert "Mike — on camera" in calls[0]["cast"]
    assert "Ducati Panigale V2" in calls[0]["cast"]


def test_ground_rag_auto_grounds_only_in_craft_advice_domains(tmp_db, monkeypatch):
    """
    The marketing shelf (platform mechanics, structuring advice) is the
    automatic layer -- never the brand's own assets (personal_brand,
    cinematography, proven_results, winning_prompts), which stay
    opt-in via picked_references (narrowed 2026-08-20).
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


def test_render_gate_open_but_unadapted_tool_stays_dry(tmp_db, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    stage_fakes(monkeypatch, [(make_concept(), [])])   # KLING shot

    result = orchestrator.run("ritual")

    assert result["clips"][0]["ok"] is False
    assert "no adapter" in result["clips"][0]["error"]


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
    autonomy.add_correction("less neon, more silence", path=tmp_db)
    calls = stage_fakes(monkeypatch, [(make_concept(), []), (make_concept(), [])])

    orchestrator.run("ritual")
    assert "less neon, more silence" in calls[0]["steer"]
    assert "less neon" not in (calls[0]["spark"] or ""), "note leaked into the spark"
    assert autonomy.pending_corrections(path=tmp_db) == []   # consumed

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


def test_thin_prompt_fails_the_floor_without_a_judge_call(tmp_db, monkeypatch):
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
    monkeypatch.setattr(orchestrator, "_judge_prompt",
                        lambda p: {"score": 4, "reason": "no camera direction",
                                   "dims": {"camera": 0}})
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["prompt_scores"][0]["pass"] is False
    assert "prompt gate: no camera direction (4/10)" in result["held_reason"]


def test_unreadable_judge_fails_closed(tmp_db, monkeypatch):
    monkeypatch.setattr(orchestrator, "_judge_prompt", REAL_JUDGE_PROMPT)
    # Long enough to clear the structural floor on the rework pass too, but
    # still not JSON -- proves fail-closed survives a rework attempt rather
    # than being masked by the structural check short-circuiting it.
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents: (
                            "I think it's pretty good actually, no notes, ship it "
                            "as-is, looks totally fine to me honestly"))
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["prompt_scores"][0]["score"] == 0
    assert "failed closed" in result["prompt_scores"][0]["reason"]
    assert "prompt gate" in result["held_reason"]


def test_a_failed_shot_gets_one_rework_pass_before_holding(tmp_db, monkeypatch):
    """A bad score isn't an automatic hold: the judge already names what's
    weak, so the failing shot earns one rewrite pass against that exact
    diagnosis before the whole concept -- including the shot that already
    passed -- gets thrown away over one fixable line. If the rework still
    doesn't clear the bar, THEN it holds (bounded, not infinite)."""
    scores = iter([
        {"score": 10, "reason": "", "dims": {}},                             # shot 1, first pass
        {"score": 3, "reason": "competing motions", "dims": {"motion": 0}},  # shot 2, first pass
        {"score": 4, "reason": "still ambiguous", "dims": {"motion": 0}},    # shot 2, after rework
    ])
    monkeypatch.setattr(orchestrator, "_judge_prompt", lambda p: next(scores))
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents: REWORKED_PROMPT)
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
    assert result["prompt_rework_attempts"] == 1          # exactly one bounded attempt, not infinite
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
                        lambda client, model, contents: REWORKED_PROMPT)
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
    assert autonomy.first_try_pass_rate(path=tmp_db)["rate"] == 1.0


def test_judge_parses_fenced_json_and_clamps_dims():
    class FakeOK:
        pass
    def fake_retry(client, model, contents):
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
    autonomy.kill("bad night", path=tmp_db)

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
    autonomy.set_autonomy("zeropage", "queue", path=tmp_db)
    result = orchestrator.publish(ready_state(tmp_db))
    assert "awaiting your approval" in result["held_reason"]


def test_publish_auto_still_parks_because_no_api_is_wired(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    autonomy.set_autonomy("zeropage", "auto", path=tmp_db)
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
    autonomy.to_hold("zeropage", "already posted", status="posted", path=tmp_db, account_id=None)

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
    [row] = autonomy.list_hold(path=tmp_db, account_id=None)
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
    row = preprod.get_concept(result["concept_id"], path=db.DB_PATH, account_id=None)
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
    row = preprod.get_concept(result["concept_id"], path=db.DB_PATH, account_id=None)
    assert row["uncanny_passed"] == 0


def test_a_broken_judge_leaves_the_concept_unjudged(tmp_db, monkeypatch):
    """Fails CLOSED and loudly. An exception here must not take the run
    down, and must not silently mark the concept post-eligible."""
    def boom(concept, gemini_client=None):
        raise RuntimeError("judge is down")

    monkeypatch.setattr(orchestrator.uncanny_judge, "score_concept", boom)
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual", brand="zeropage", channel="zeropage")

    row = preprod.get_concept(result["concept_id"], path=db.DB_PATH, account_id=None)
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
    from src import asset_shelf, refbin, scout

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
                              "score": 0.9}, pass_id="p", path=tmp_db)
    scout.bin_add("zeropage", "p", banked,
                  source_url="https://example.com/post", path=tmp_db)

    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
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
        out["concept_id"], path=tmp_db, account_id=None)["shots"][0]["refs"]


def test_a_rotation_night_is_untouched_by_any_of_this(tmp_db, monkeypatch):
    """A run that did not ask to scout must reach the writer exactly as
    it always did -- no bank read, no photographs, no change."""
    from src import scout

    scout.record("zeropage", {"spark": "a crawled idea", "score": 0.99},
                 pass_id="p", path=tmp_db)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])
    out = orchestrator.run("the last check before leaving", brand="zeropage",
                           channel="zeropage")

    assert out["spark"] == "the last check before leaving"
    assert calls[0]["image_refs"] == []


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
    entities.add_character("Mike — on camera", path=tmp_db, account_id=None)
    entities.add_prop("Ducati Panigale V2", category="vehicle", path=tmp_db,
                      account_id=None)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual", brand="zeropage", channel="zeropage")

    assert calls[0]["cast"] == "", "the faceless brand was handed a cast"
