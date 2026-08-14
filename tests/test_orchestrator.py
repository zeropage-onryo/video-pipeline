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
    preprod.add_location("hallway", {"space": "narrow hallway"}, photo_count=2, path=path)
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

# captured at import, before any fixture stubs it -- for the tests that
# need the real fail-closed judge back
REAL_JUDGE_PROMPT = orchestrator._judge_prompt


def make_concept(**overrides):
    concept = {
        "title": "The Waiting",
        "hook": "a hand already on the door handle",
        "logline": "He waits for someone who never knocks.",
        "shots": [
            {"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
             "location": "hallway", "desc": "low angle, he steps into frame"},
            {"n": 2, "type": "BROLL", "source": "AI", "tool": "KLING",
             "location": "hallway", "desc": "the handle turns on its own",
             "prompt": GOOD_PROMPT},
        ],
    }
    concept.update(overrides)
    return concept


def stage_fakes(monkeypatch, results):
    """Patch generate_concept; record the kwargs of every attempt."""
    queue = list(results)
    calls = []

    def fake_generate(brand, client=None, spark=None, gemini_client=None,
                      model=None, use_pov=True, db_path=None, references="",
                      cast=None):
        calls.append({"spark": spark, "references": references, "cast": cast})
        concept, warnings = queue.pop(0)
        return {"concept_id": len(calls), "concept": concept, "warnings": warnings}

    monkeypatch.setattr(orchestrator.shootgen, "generate_concept", fake_generate)
    return calls


# ---------- the left third: the original loop, preserved ----------

def test_clean_run_parks_in_shadow_with_the_render_stub_reason(tmp_db, monkeypatch):
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("gearing up ritual")

    assert result["attempts"] == 1
    assert result["critique"]["ok"] is True
    # the AI shot's prompt was extracted...
    assert result["prompts"] == [
        {"tool": "KLING", "prompt": GOOD_PROMPT, "still": ""}]
    # ...but render is a stub, so the run parks instead of posting
    assert "render is a dry-run stub" in result["held_reason"]
    [row] = autonomy.list_hold(path=tmp_db)
    assert row["status"] == "held"
    assert row["concept_id"] == 1
    assert row["payload"]["prompts"][0]["tool"] == "KLING"


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
    [row] = autonomy.list_hold(path=tmp_db)
    assert row["status"] == "held"


def test_no_locations_parks_before_any_generation(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    autonomy.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(orchestrator.crag, "retrieve_with_crag",
                        lambda *a, **k: {"ok": False, "references": [], "error": "x"})
    calls = stage_fakes(monkeypatch, [])

    result = orchestrator.run("ritual")

    assert "No described locations" in result["held_reason"]
    assert calls == []                       # generate never ran
    [row] = autonomy.list_hold(path=path)    # even the failure is logged
    assert "No described locations" in row["reason"]


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
    mike = entities.add_character("Mike — on camera", role="protagonist", path=tmp_db)
    entities.add_character("Guest — bartender", role="guest", path=tmp_db)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual", picked_characters=[mike])

    assert "Mike — on camera" in calls[0]["cast"]
    assert "Guest — bartender" not in calls[0]["cast"]


def test_ground_entities_defaults_to_everything_on_file(tmp_db, monkeypatch):
    entities.add_character("Mike — on camera", path=tmp_db)
    entities.add_prop("Ducati Panigale V2", category="vehicle", path=tmp_db)
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual")

    assert "Mike — on camera" in calls[0]["cast"]
    assert "Ducati Panigale V2" in calls[0]["cast"]


def test_ground_rag_formats_crag_hits_into_references(tmp_db, monkeypatch):
    monkeypatch.setattr(
        orchestrator.crag, "retrieve_with_crag",
        lambda *a, **k: {"ok": True, "rewritten_query": None, "references": [
            {"source": "brief.txt", "chunk": "still, patient, one move"}]},
    )
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual")

    assert "brief.txt" in calls[0]["references"]
    assert "still, patient, one move" in calls[0]["references"]


def test_ground_rag_degrades_to_ungrounded(tmp_db, monkeypatch):
    calls = stage_fakes(monkeypatch, [(make_concept(), [])])

    orchestrator.run("ritual")           # tmp_db fixture stubs CRAG to fail

    assert calls[0]["references"] == ""


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

def test_pending_corrections_fold_into_the_spark_once(tmp_db, monkeypatch):
    autonomy.add_correction("less neon, more silence", path=tmp_db)
    calls = stage_fakes(monkeypatch, [(make_concept(), []), (make_concept(), [])])

    orchestrator.run("ritual")
    assert "less neon, more silence" in calls[0]["spark"]
    assert autonomy.pending_corrections(path=tmp_db) == []   # consumed

    orchestrator.run("ritual")                               # next night
    assert "less neon" not in (calls[1]["spark"] or "")      # steered once


# ---------- the prompt gate (the credit gate) ----------

def test_structural_floor_catches_the_cheap_failures():
    ok, why = orchestrator._structural_check("")
    assert not ok and "too thin" in why
    ok, why = orchestrator._structural_check("a door " * 70)
    assert not ok and "over-stuffed" in why
    ok, why = orchestrator._structural_check(
        "a long enough prompt with a leftover {location} token in it "
        "plus more words to clear the length floor easily today")
    assert not ok and "placeholder" in why
    ok, why = orchestrator._structural_check(GOOD_PROMPT)
    assert ok


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
    monkeypatch.setattr(orchestrator, "generate_with_retry",
                        lambda client, model, contents: "I think it's pretty good actually")
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["prompt_scores"][0]["score"] == 0
    assert "failed closed" in result["prompt_scores"][0]["reason"]
    assert "prompt gate" in result["held_reason"]


def test_one_bad_prompt_holds_the_whole_run(tmp_db, monkeypatch):
    scores = iter([{"score": 10, "reason": "", "dims": {}},
                   {"score": 3, "reason": "competing motions", "dims": {}}])
    monkeypatch.setattr(orchestrator, "_judge_prompt", lambda p: next(scores))
    two_ai = make_concept(shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
         "location": "hallway", "desc": "x", "prompt": GOOD_PROMPT},
        {"n": 2, "type": "BROLL", "source": "AI", "tool": "VEO",
         "location": "hallway", "desc": "y", "prompt": GOOD_PROMPT},
    ])
    stage_fakes(monkeypatch, [(two_ai, [])])

    result = orchestrator.run("ritual")

    assert [x["pass"] for x in result["prompt_scores"]] == [True, False]
    assert "competing motions" in result["held_reason"]   # no half-rendered credit burn


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
    autonomy.to_hold("zeropage", "already posted", status="posted", path=tmp_db)

    result = orchestrator.publish(ready_state(tmp_db))

    assert "rate cap" in result["held_reason"]
