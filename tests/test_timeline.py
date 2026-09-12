"""A scene's timed windows, rendered as separate shots (2026-09-10).

Mike's call: a scene prompt may carry several shots -- (0-3s) one shot,
(3-7s) a different one -- and the pipeline renders them ONE BY ONE. The
brain that wrote the scene splits it, keeps the scene's memory in front of
every shot, and hands each shot only the reference photos it shows. These
tests pin the parts of that which code enforces rather than a model:

- the windows come from the scene, never from the planner's answer;
- a shot's refs are a subset of the scene's, by number, in scene order;
- a timeline planned from a prompt that has since changed is never used;
- each shot renders at its own window's length, fitted UP to what the
  model can make, through the same adapter entry point a scene uses;
- a render that stops halfway resumes instead of paying twice;
- the scene's total length reaches the writer (the gap the first
  multi-scene draft left: "fit the requested duration" with none given).
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import gemini_utils, imagery, nano_banana, preprod, providers, runway, scene_chain, shootgen, timeline

client = TestClient(app)

SCENE = (
    "Ultra-realistic grounded noir video in 9:16. STYLE: wet streets, sodium light.\n"
    "3. BEATS: (0-3s) Close on his hand turning the key; the engine coughs. "
    "(3-7s) Hard cut to the alley: he looks up at the window above. "
    "(7-10s) Reverse on the window: the curtain drops.\n"
    "4. SOUND: No background music. Rain on tin.\n"
    "5. AVOID: no plastic AI sheen."
)
FACE = "/characters/michael/photo/face.jpg"
BIKE = "/props/ducati/photo/side.jpg"
ROOM = "/locations/alley/photo/wide.jpg"


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    from app import auth
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "zeropage", "display_name": "ZERO PAGE"})


@pytest.fixture
def tmp_db(pg, monkeypatch):
    from src import entities, generative
    preprod.init(pg)
    entities.init(pg)
    generative.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    return pg


def a_scene(path, prompt=SCENE, refs=(FACE, BIKE, ROOM), parked=True):
    cid = preprod.save_concept(
        {"title": "Key", "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "desc": "d", "prompt": prompt, "refs": list(refs)}]},
        brand="antihero", prompt_template="T", dsn=path, account_id=None)
    if parked:
        preprod.set_shot_parked(cid, 1, "ready", dsn=path, account_id=None)
    return cid


def planner_answers(monkeypatch, answer, seen=None):
    """Stand in for the one billed call timeline.plan makes."""
    def fake(client_, model, contents, **kw):
        if seen is not None:
            seen.append({"model": model, "contents": contents, **kw})
        return answer if isinstance(answer, str) else json.dumps(answer)
    monkeypatch.setattr(gemini_utils, "generate_with_retry", fake)
    monkeypatch.setattr(imagery, "image_bytes_for_gemini",
                        lambda url, resolve_photo=None: b"\x89PNG....")


GOOD = {"continuity": "Michael, black leather jacket, the red Ducati, rain, sodium light.",
        "shots": [
            {"window": "0-3s", "prompt": "Macro on the key turning.", "refs": [2]},
            {"window": "3-7s", "prompt": "Wide alley, he looks up.", "refs": [3, 1, 1, 9]},
            {"window": "7-10s", "prompt": "The curtain drops.", "refs": []},
        ]}


# --- the windows ------------------------------------------------------------

def test_windows_are_read_off_the_scene_in_order_with_their_sentences():
    windows = timeline.parse_windows(SCENE)
    assert [(w["start"], w["end"], w["seconds"]) for w in windows] == [
        (0, 3, 3), (3, 7, 4), (7, 10, 3)]
    assert windows[0]["text"].startswith("Close on his hand")
    # the last window stops at the SOUND block instead of swallowing it
    assert "Rain on tin" not in windows[-1]["text"]
    assert windows[-1]["text"].endswith("the curtain drops")


def test_a_parenthetical_that_is_not_a_clock_is_not_a_window():
    assert timeline.parse_windows("(2-3 people) stand in a (4-5) queue") == []


def test_one_window_is_one_shot_and_is_not_split():
    """A scene that is one continuous moment renders whole, exactly as
    every scene did before today -- splitting it buys a planning call and
    nothing else."""
    assert timeline.parse_windows("(0-10s) one long push in on the door.") == []
    assert timeline.parse_windows("a scene with no clock at all") == []


def test_the_scene_length_is_clamped_never_refused(monkeypatch):
    monkeypatch.delenv(timeline.SCENE_SECONDS_ENV, raising=False)
    assert timeline.scene_seconds() == timeline.DEFAULT_SCENE_SECONDS
    assert timeline.scene_seconds("15") == 15
    assert timeline.scene_seconds(999) == timeline.MAX_SCENE_SECONDS
    assert timeline.scene_seconds("banana") == timeline.DEFAULT_SCENE_SECONDS
    monkeypatch.setenv(timeline.SCENE_SECONDS_ENV, "20")
    assert timeline.scene_seconds() == 20          # the night's posture
    assert timeline.scene_seconds(5) == 5          # an explicit pick still wins


def test_the_writers_are_told_how_long_the_scene_is(monkeypatch):
    """The gap the first multi-scene draft left: both templates said "fit
    the requested duration" and neither was handed one."""
    brief = shootgen.build_scene_brief_prompt("antihero", spark="x", seconds=15)
    takes = shootgen.build_scenes_prompt("x", "antihero", 2, [], seconds=15)
    for text in (brief, takes):
        assert "{seconds}" not in text
        assert "15s" in text or "15 seconds" in text
        assert "RENDERED AS ITS OWN SEPARATE CLIP" in text


# --- fitting a window to a model -------------------------------------------

def test_a_window_is_fitted_up_to_a_length_the_model_can_make():
    runway_like = {"kind": "choices", "values": [5, 10]}
    assert timeline.fit_seconds(runway_like, 3) == 5     # trimmed in the edit
    assert timeline.fit_seconds(runway_like, 7) == 10    # up, never down
    assert timeline.fit_seconds(runway_like, 14) == 10   # the longest there is
    span = {"kind": "range", "min": 2, "max": 12}
    assert timeline.fit_seconds(span, 3.5) == 4
    assert timeline.fit_seconds(span, 1) == 2
    assert timeline.fit_seconds({"kind": "fixed", "values": [8]}, 3) == 8


def test_the_timeline_price_is_the_sum_of_each_shots_own_render():
    choice = providers.check_timeline_choice("runway", runway.DEFAULT_MODEL, None, [3, 4, 3])
    assert choice["durations"] == [5, 5, 5]
    one = runway.estimate_cost(1, model=runway.DEFAULT_MODEL, duration=5)
    assert choice["estimate_usd"] == pytest.approx(3 * one)


# --- planning ----------------------------------------------------------------

def test_refs_are_picked_by_number_from_the_scenes_own_set_in_scene_order():
    windows = timeline.parse_windows(SCENE)
    out = timeline.parse_response(json.dumps(GOOD), windows, [FACE, BIKE, ROOM])
    assert [p["refs"] for p in out["parts"]] == [[BIKE], [FACE, ROOM], []]
    # the WINDOWS are the scene's, whatever the answer called them
    assert [(p["start"], p["end"]) for p in out["parts"]] == [(0, 3), (3, 7), (7, 10)]


def test_an_answer_that_does_not_fit_the_windows_is_not_a_timeline():
    windows = timeline.parse_windows(SCENE)
    short = dict(GOOD, shots=GOOD["shots"][:2])
    assert timeline.parse_response(json.dumps(short), windows, [FACE]) is None
    assert timeline.parse_response("not json", windows, [FACE]) is None


def test_the_planner_runs_on_the_brain_it_was_handed_and_sees_every_photo(monkeypatch):
    seen = []
    planner_answers(monkeypatch, GOOD, seen)
    tl = timeline.plan(SCENE, [FACE, BIKE, ROOM], brain="reasoning",
                       gemini_client=object())
    assert tl["planner"] == "reasoning"
    assert seen[0]["stage"] == "timeline"
    assert seen[0]["model"] == gemini_utils.resolve_brain("reasoning")["model"]
    captions = [c for c in seen[0]["contents"] if isinstance(c, str)]
    assert captions[0].startswith("[1]") and captions[2].startswith("[3]")
    assert tl["seconds"] == 10 and len(tl["parts"]) == 3


def test_no_planner_falls_back_to_a_plain_split_that_keeps_every_ref(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    tl = timeline.plan(SCENE, [FACE, BIKE])
    assert tl["planner"] == "split"
    assert all(p["refs"] == [FACE, BIKE] for p in tl["parts"])
    assert tl["parts"][1]["prompt"].startswith("Hard cut to the alley")
    # the continuity is the scene WITHOUT its action -- look, sound, avoid
    assert "sodium light" in tl["continuity"]
    assert "curtain drops" not in tl["continuity"]


def test_every_shots_prompt_carries_the_scenes_memory_in_front_of_it(monkeypatch):
    planner_answers(monkeypatch, GOOD)
    tl = timeline.plan(SCENE, [FACE, BIKE, ROOM], gemini_client=object())
    composed = timeline.render_prompt(tl["parts"][2], tl)
    assert composed.startswith("CONTINUITY")
    assert "black leather jacket" in composed          # code put it there
    assert "SHOT 3 OF 3 (7-10s, 3s): The curtain drops." in composed


# --- the stored timeline -----------------------------------------------------

def test_ensure_stores_the_timeline_on_the_scenes_one_shot(tmp_db, monkeypatch):
    planner_answers(monkeypatch, GOOD)
    cid = a_scene(tmp_db)
    tl = timeline.ensure(cid, gemini_client=object(), db_path=tmp_db)
    concept = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    assert concept["is_scene"]                      # still ONE shot, one row
    shot = concept["shots"][0]
    assert shot["timeline"]["parts"] == tl["parts"]
    assert shot["seconds"] == 10
    assert timeline.is_current(shot)


def test_an_edited_prompt_makes_the_timeline_stale_and_it_is_replanned(tmp_db, monkeypatch):
    calls = []
    planner_answers(monkeypatch, GOOD, calls)
    cid = a_scene(tmp_db)
    timeline.ensure(cid, gemini_client=object(), db_path=tmp_db)
    timeline.ensure(cid, gemini_client=object(), db_path=tmp_db)
    assert len(calls) == 1                          # current: no second call

    # shot 1 got its clip, then shot 3's sentence was edited in Director
    timeline.attach_part(cid, 1, 1, "media_url", "https://x/p1.mp4", db_path=tmp_db)
    concept = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    shots = concept["shots"]
    shots[0]["prompt"] = SCENE.replace("the curtain drops", "a light goes out")
    preprod.update_concept_shots(cid, {"shots": shots}, dsn=tmp_db, account_id=None)
    assert not timeline.is_current(preprod.get_concept(
        cid, dsn=tmp_db, account_id=None)["shots"][0])

    tl = timeline.ensure(cid, gemini_client=object(), db_path=tmp_db)
    assert len(calls) == 2
    # shot 1's window and sentence did not change: its clip survives
    assert tl["parts"][0]["media_url"] == "https://x/p1.mp4"
    assert tl["parts"][2]["media_url"] is None


def test_a_scene_with_one_window_renders_whole_as_before(tmp_db):
    cid = a_scene(tmp_db, prompt="(0-10s) one long push in on the door, no cut.")
    assert timeline.ensure(cid, db_path=tmp_db) is None
    shot = preprod.get_concept(cid, dsn=tmp_db, account_id=None)["shots"][0]
    assert "timeline" not in shot
    # the motion directive leads every RENDER prompt now (for_render), and
    # the scene's own sentence follows it unchanged
    prompt = timeline.render_target(shot)["prompt"]
    assert prompt.startswith(timeline.MOTION_DIRECTIVE)
    assert prompt.endswith("(0-10s) one long push in on the door, no cut.")


def test_the_scene_counts_as_rendered_only_when_every_shot_is(tmp_db, monkeypatch):
    planner_answers(monkeypatch, GOOD)
    cid = a_scene(tmp_db)
    timeline.ensure(cid, gemini_client=object(), db_path=tmp_db)
    for n in (1, 2):
        timeline.attach_part(cid, 1, n, "media_url", f"https://x/p{n}.mp4", db_path=tmp_db)
    shot = preprod.get_concept(cid, dsn=tmp_db, account_id=None)["shots"][0]
    assert not shot.get("media_url")                # still waiting in the Queue
    timeline.attach_part(cid, 1, 3, "media_url", "https://x/p3.mp4", db_path=tmp_db)
    shot = preprod.get_concept(cid, dsn=tmp_db, account_id=None)["shots"][0]
    assert shot["media_url"] == "https://x/p1.mp4"  # shot 1, not a stitched cut


def test_the_motion_directive_leads_the_render_prompt_and_not_the_keyframe(tmp_db, monkeypatch):
    """Every renderer here is image-to-video: the frame already says what the
    shot looks like, so the prompt's job is what CHANGES. The directive goes
    in at render_target -- the render boundary all four adapters read -- and
    deliberately NOT in render_prompt, which also feeds scene_chain's still."""
    planner_answers(monkeypatch, GOOD)
    cid = a_scene(tmp_db)
    timeline.ensure(cid, gemini_client=object(), db_path=tmp_db)
    shot = preprod.get_concept(cid, dsn=tmp_db, account_id=None)["shots"][0]
    tl = shot["timeline"]

    composed = timeline.render_prompt(tl["parts"][0], tl)
    assert timeline.MOTION_DIRECTIVE not in composed      # the still is spared
    rendered = timeline.render_target(shot, 1)["prompt"]
    assert rendered.startswith(timeline.MOTION_DIRECTIVE)
    assert composed in rendered                           # nothing else changed


def test_the_directive_can_be_switched_off_for_a_prompt_that_needs_the_room(
        tmp_db, monkeypatch):
    """gen4's cap is 1000 characters and refuses rather than truncating, so
    there has to be a way to spend those 121 characters on the shot instead."""
    monkeypatch.setenv("ZEROPAGE_MOTION_DIRECTIVE", "0")
    shot = {"prompt": "(0-10s) one long push in.", "seconds": 10}
    assert timeline.render_target(shot)["prompt"] == "(0-10s) one long push in."


def test_the_directive_leaves_room_under_the_gen4_cap(tmp_db, monkeypatch):
    """The budget this is sized against. A continuity block plus a shot line
    plus the directive has to still fit what runway.check_prompt_length lets
    through, or this turns working renders into refusals."""
    from src import runway
    planner_answers(monkeypatch, GOOD)
    cid = a_scene(tmp_db)
    timeline.ensure(cid, gemini_client=object(), db_path=tmp_db)
    shot = preprod.get_concept(cid, dsn=tmp_db, account_id=None)["shots"][0]
    rendered = timeline.render_target(shot, 1)["prompt"]
    runway.check_prompt_length(rendered, "gen4_turbo")          # no raise
    assert len(timeline.MOTION_DIRECTIVE) < 150


def test_render_target_reads_the_part_its_own_still_and_refs(tmp_db, monkeypatch):
    planner_answers(monkeypatch, GOOD)
    cid = a_scene(tmp_db)
    timeline.ensure(cid, gemini_client=object(), db_path=tmp_db)
    timeline.attach_part(cid, 1, 2, "reference_image", "https://x/still2.png", db_path=tmp_db)
    shot = preprod.get_concept(cid, dsn=tmp_db, account_id=None)["shots"][0]
    target = timeline.render_target(shot, 2)
    assert target["reference_image"] == "https://x/still2.png"
    assert target["refs"] == [FACE, ROOM]
    assert target["seconds"] == 4
    assert timeline.render_target(shot, 9) is None


# --- one still per shot -----------------------------------------------------

def test_a_timed_scene_draws_one_still_per_shot_with_the_last_as_continuity(
        tmp_db, monkeypatch):
    planner_answers(monkeypatch, GOOD)
    drawn = []

    def fake_nano(prompt, *, reference_image=None, db_path=None, concept_id=None,
                  beat="", **kw):
        drawn.append({"prompt": prompt, "labels": [r[0] for r in reference_image or []],
                      "beat": beat})
        return {"ok": True, "media_url": f"https://x/still{len(drawn)}.png",
                "generation_id": 1, "path": None, "error": None}
    monkeypatch.setattr(nano_banana, "generate_from_prompt", fake_nano)
    monkeypatch.setattr(shootgen, "beat_moments", lambda *a, **k: pytest.fail(
        "a timed scene is split by its windows, not by the beat splitter"))

    cid = a_scene(tmp_db)
    result = scene_chain.keyframe_scene(cid, db_path=tmp_db, gemini_client=object())
    assert result["ok"] and len(result["frames"]) == 3
    assert "black leather jacket" in drawn[0]["prompt"]
    assert "FIRST frame of shot 1 of 3" in drawn[0]["beat"]
    # shot 1 shows the bike only; shot 2 gets the face and the room AND
    # shot 1's still, labelled as continuity rather than something to copy
    assert len(drawn[0]["labels"]) == 1
    assert drawn[1]["labels"][-1] == scene_chain.CONTINUITY_REF_LABEL
    shot = preprod.get_concept(cid, dsn=tmp_db, account_id=None)["shots"][0]
    assert shot["reference_image"] == "https://x/still1.png"
    assert [p["reference_image"] for p in shot["timeline"]["parts"]] == [
        "https://x/still1.png", "https://x/still2.png", "https://x/still3.png"]


def test_a_strip_cut_short_by_the_cap_is_finished_by_picking_again(tmp_db, monkeypatch):
    planner_answers(monkeypatch, GOOD)
    budget = {"left": 1}

    def capped(prompt, **kw):
        if budget["left"] <= 0:
            return {"ok": False, "error": "NANO_DAILY_CAP reached"}
        budget["left"] -= 1
        return {"ok": True, "media_url": f"https://x/s{budget['left']}-{len(prompt)}.png",
                "generation_id": 1, "path": None, "error": None}
    monkeypatch.setattr(nano_banana, "generate_from_prompt", capped)
    cid = a_scene(tmp_db)
    first = scene_chain.keyframe_scene(cid, db_path=tmp_db, gemini_client=object())
    assert len(first["frames"]) == 1 and "CAP" in first["error"]
    concept = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    assert scene_chain.pick_skip_reason(concept) is None      # not done yet

    budget["left"] = 5
    second = scene_chain.keyframe_scene(cid, db_path=tmp_db, gemini_client=object())
    assert len(second["frames"]) == 3 and budget["left"] == 3  # only 2 more drawn
    concept = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    assert scene_chain.pick_skip_reason(concept) == "already has a still"


# --- the Queue renders the shots one by one ---------------------------------

def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def fake_runway(monkeypatch, fail_on=None):
    calls = []

    def fake(concept_id, shot_n, *, part=None, duration=None, db_path=None,
             account_id=None, **kw):
        calls.append({"part": part, "duration": duration, "approved": kw.get("approved")})
        if fail_on is not None and part == fail_on:
            return {"ok": False, "error": "RUNWAY_DAILY_CAP reached"}
        if part:
            timeline.attach_part(concept_id, shot_n, part, "media_url",
                                 f"https://x/clip{part}.mp4", db_path=db_path,
                                 account_id=account_id)
        else:
            preprod.set_shot_media_url(concept_id, shot_n, "https://x/clip.mp4",
                                       dsn=db_path, account_id=account_id)
        return {"ok": True, "media_url": f"https://x/clip{part}.mp4"}
    monkeypatch.setattr(runway, "generate_for_shot", fake)
    monkeypatch.setattr(runway, "has_key", lambda account_id=None: True)
    return calls


def test_approving_a_timed_scene_renders_each_shot_at_its_own_length(tmp_db, monkeypatch):
    planner_answers(monkeypatch, GOOD)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("google.genai.Client", lambda **kw: object())
    calls = fake_runway(monkeypatch)
    cid = a_scene(tmp_db)

    card = next(c for c in client.get("/api/queue/pending?brand=antihero").json()["items"]
                if c["id"] == cid)
    assert [p["seconds"] for p in card["timeline"]["parts"]] == [3, 4, 3]

    res = client.post(f"/api/queue/{cid}/approve", json={"provider": "runway"})
    assert res.status_code == 200, res.text
    assert res.json()["render"]["durations"] == [5, 5, 5]
    job = wait_for_job(res.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert [c["part"] for c in calls] == [1, 2, 3]          # one by one, in order
    assert all(c["duration"] == 5 and c["approved"] is True for c in calls)
    shot = preprod.get_concept(cid, dsn=tmp_db, account_id=None)["shots"][0]
    assert shot["media_url"] == "https://x/clip1.mp4"
    assert all(c["id"] != cid for c in
               client.get("/api/queue/pending?brand=antihero").json()["items"])


def test_a_render_stopped_by_the_cap_resumes_instead_of_paying_twice(tmp_db, monkeypatch):
    planner_answers(monkeypatch, GOOD)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("google.genai.Client", lambda **kw: object())
    calls = fake_runway(monkeypatch, fail_on=2)
    cid = a_scene(tmp_db)
    job = wait_for_job(client.post(f"/api/queue/{cid}/approve",
                                   json={"provider": "runway"}).json()["job_id"])
    assert job["status"] == "failed"
    assert "1 of 3 rendered" in job["error"]
    # still waiting: two shots have no clip
    assert any(c["id"] == cid for c in
               client.get("/api/queue/pending?brand=antihero").json()["items"])

    calls = fake_runway(monkeypatch)
    job = wait_for_job(client.post(f"/api/queue/{cid}/approve",
                                   json={"provider": "runway"}).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert [c["part"] for c in calls] == [2, 3]              # shot 1 not re-bought


def test_a_single_window_scene_still_approves_as_one_clip(tmp_db, monkeypatch):
    calls = fake_runway(monkeypatch)
    cid = a_scene(tmp_db, prompt="(0-10s) one long push in on the door, no cut.")
    res = client.post(f"/api/queue/{cid}/approve", json={"provider": "runway",
                                                         "duration": 10})
    job = wait_for_job(res.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert calls == [{"part": None, "duration": 10, "approved": True}]


# --- Create plans the shots ---------------------------------------------------

def test_create_plans_the_shots_on_the_brain_that_wrote_the_scene(tmp_db, monkeypatch):
    seen = []

    def fake_writer(client_, model, contents, **kw):
        return json.dumps({"scenes": [{"title": "Key", "location": "", "prompt": SCENE}]})
    monkeypatch.setattr(shootgen, "generate_with_retry", fake_writer)
    monkeypatch.setattr(shootgen, "reference_block", lambda **kw: "")
    planner_answers(monkeypatch, GOOD, seen)
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    result = scene_chain.run("the key", "antihero", count=1, refs=[FACE, BIKE, ROOM],
                             db_path=tmp_db, gemini_client=object(),
                             brain="reasoning", seconds=10)
    cid = result["scenes"][0]["concept_id"]
    shot = preprod.get_concept(cid, dsn=tmp_db, account_id=None)["shots"][0]
    assert shot["timeline"]["planner"] == "reasoning"
    assert seen and seen[0]["model"] == gemini_utils.resolve_brain("reasoning")["model"]
    assert "3 shots across 1 scene(s)" in result["notes"]
