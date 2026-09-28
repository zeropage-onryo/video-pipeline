"""
A fal render whose worker dies mid-poll is finished by the sweep, not
orphaned (2026-09-26: PR #70's deploy restarted the API while two Queue
renders -- #121 Kling, #135 Seedance -- were polling, and both holds sat
`submitted` with no generations row and no way back to fal's job).

What each test guards:
- fal's receipt is persisted BEFORE the first poll, keyed by the hold's ref
- a job fal COMPLETED is fetched, downloaded, recorded, settled and attached
  to the concept exactly as the live path would have -- one generations row,
  linked to the hold
- a job fal FAILED, forgot (404), or kept queued past the give-up is
  released with the reason, and leaves a failed attempt row
- anything that is not an answer from fal leaves the hold alone
- a live worker's request (fresh heartbeat) is never claimed, and a render
  that finished normally is resolved so the sweep never sees it
- a worker that died AFTER writing its row is finished without a second row
- a hold somebody already released by hand still gets its clip attached,
  and the ledger is not touched again

Hermetic: the `http` seam is a fake (conftest blocks the network), the
download is patched, and a "dead worker" is a BaseException raised from the
poll -- it sails past every `except Exception`, so nothing releases,
records or resolves, which is exactly what a killed process does.
"""

import json
import urllib.error

import pytest

from src import accounts, db, fal, fal_requests, generative, ledger, preprod

PROMPT = "a man walks into a rain-lit bar and does not look back " * 2
STATUS_URL = "https://queue.fal.run/fal-ai/x/requests/r1/status"
RESPONSE_URL = "https://queue.fal.run/fal-ai/x/requests/r1"
OUTPUT = "https://v3.fal.media/files/out/clip.mp4"


def _wrapped(code, reason, body=""):
    """fal._request's own shape (#69): RuntimeError from the HTTPError."""
    try:
        raise urllib.error.HTTPError(STATUS_URL, code, reason, {}, None)
    except urllib.error.HTTPError as e:
        try:
            raise RuntimeError(f"HTTP Error {code}: {reason}"
                               + (f" -- {body}" if body else "")) from e
        except RuntimeError as wrapped:
            return wrapped


class WorkerDied(BaseException):
    """The process going away: not an Exception, so no handler runs."""


class Fal:
    """fal's queue, scripted. `die_on_poll` kills the worker at the first
    status poll; afterwards the same object answers the sweep."""

    def __init__(self, *, status="COMPLETED", status_payload=None, result=None,
                 die_on_poll=False, status_raises=None, result_raises=None):
        self.status = status
        self.status_payload = status_payload or {}
        self.result = result if result is not None else {"video": {"url": OUTPUT}}
        self.die_on_poll = die_on_poll
        self.status_raises = status_raises
        self.result_raises = result_raises
        self.calls = []
        self.on_first_poll = None

    def __call__(self, url, payload=None):
        self.calls.append(url)
        if payload is not None:
            return {"status": "IN_QUEUE", "request_id": "r1",
                    "status_url": STATUS_URL, "response_url": RESPONSE_URL,
                    "cancel_url": RESPONSE_URL + "/cancel"}
        if url == STATUS_URL:
            if self.on_first_poll:
                hook, self.on_first_poll = self.on_first_poll, None
                hook()
            if self.die_on_poll:
                self.die_on_poll = False
                raise WorkerDied()
            if self.status_raises:
                raise self.status_raises
            return {"status": self.status, **self.status_payload}
        if self.result_raises:
            raise self.result_raises
        return self.result


@pytest.fixture
def studio(pg, monkeypatch, tmp_path):
    """A funded, not-exempt account on the installation's fal key, so a
    real hold is taken, with the clip's destinations stubbed locally."""
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("FAL_KEY", "OPERATOR-SECRET")
    monkeypatch.setenv(fal.SPEND_ENV, "1")
    monkeypatch.setattr(fal, "POLL_SECONDS", 0)
    monkeypatch.setattr(fal, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(fal, "_request", lambda *a, **k: pytest.fail("real HTTP"))

    downloaded = []

    def download(url, out_path):
        downloaded.append(url)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 2048)

    monkeypatch.setattr(fal, "_download", download)
    import src.render_assets as render_assets
    import src.storage as storage
    monkeypatch.setattr(storage, "configured", lambda: False)
    monkeypatch.setattr(render_assets, "record_best_effort",
                        lambda **kw: {"id": None, "rag": {"ok": False}})

    generative.init(pg)
    preprod.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"])
    ledger.grant(account_id, 100000, "purchase", dsn=pg)
    concept_id = preprod.save_concept(
        {"title": "The Crimson Descent", "hook": "h", "logline": "l",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
                    "prompt": PROMPT, "refs": ["/refs/seed.jpg"]}]},
        "antihero", dsn=pg, account_id=account_id)
    return {"dsn": pg, "account_id": account_id, "concept_id": concept_id,
            "downloaded": downloaded, "funded": 100000}


@pytest.fixture
def stale_now(monkeypatch):
    """Every unresolved request reads as dead -- the sweep ten minutes on."""
    monkeypatch.setattr(fal_requests, "STALE_SECONDS", -1)


def _die_mid_render(studio, http):
    with pytest.raises(WorkerDied):
        fal.generate_for_shot(studio["concept_id"], 1, db_path=studio["dsn"],
                              model="kling3-turbo-pro", http=http, approved=True,
                              account_id=studio["account_id"])


def _requests(studio):
    with db.connect(studio["dsn"]) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM fal_requests WHERE account_id = %s ORDER BY id",
            (studio["account_id"],)).fetchall()]


def _generations(studio):
    with db.connect(studio["dsn"]) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM generations WHERE account_id = %s ORDER BY id",
            (studio["account_id"],)).fetchall()]


def _kinds(studio):
    return [e["kind"] for e in ledger.entries(studio["account_id"], studio["dsn"])]


def _shot(studio):
    concept = preprod.get_concept(studio["concept_id"], dsn=studio["dsn"],
                                  account_id=studio["account_id"])
    return concept["shots"][0]


# --- the receipt ------------------------------------------------------------

def test_the_receipt_is_persisted_before_the_first_poll(studio):
    http = Fal(die_on_poll=True)
    seen = []
    http.on_first_poll = lambda: seen.extend(_requests(studio))
    _die_mid_render(studio, http)

    assert len(seen) == 1                       # written between submit and poll
    row = seen[0]
    assert row["request_id"] == "r1"
    assert row["status_url"] == STATUS_URL and row["response_url"] == RESPONSE_URL
    assert row["resolved_at"] is None
    holds = [e for e in ledger.entries(studio["account_id"], studio["dsn"])
             if e["kind"] == "hold"]
    assert row["ref"] == holds[0]["ref"]        # the same ref links hold and job
    assert row["hold_id"] == holds[0]["id"]
    assert holds[0]["submitted_at"]             # and this is exactly the orphan shape
    assert _generations(studio) == []
    track = json.loads(row["context_json"])
    assert track["kind"] == "shot" and track["concept_id"] == studio["concept_id"]


def test_a_live_workers_request_is_not_claimed(studio):
    """Default staleness: the worker beat a moment ago, so it is alive as
    far as the sweep can tell -- a rolling deploy's old machine included."""
    http = Fal(die_on_poll=True)
    _die_mid_render(studio, http)
    assert fal_requests.recover(dsn=studio["dsn"], http=http) == {
        "rendered": [], "released": [], "pending": [], "retry": []}
    assert _requests(studio)[0]["resolved_at"] is None
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) > 0


def test_a_finished_render_resolves_its_request(studio, stale_now):
    result = fal.generate_for_shot(studio["concept_id"], 1, db_path=studio["dsn"],
                                   model="kling3-turbo-pro", http=Fal(), approved=True,
                                   account_id=studio["account_id"])
    assert result["ok"] is True, result["error"]
    [row] = _requests(studio)
    assert row["resolved_at"] and row["outcome"] == "rendered"
    assert row["generation_id"] == result["generation_id"]
    # nothing for the sweep to do, even with every row reading as stale
    assert fal_requests.recover(dsn=studio["dsn"], http=Fal())["rendered"] == []
    params = json.loads(_generations(studio)[0]["params_json"])
    assert params[fal_requests.GENERATION_REF_KEY] == row["ref"]


# --- the sweep: fal answered ------------------------------------------------

def test_a_completed_job_is_recorded_settled_and_attached(studio, stale_now):
    http = Fal(die_on_poll=True)
    _die_mid_render(studio, http)
    assert not _shot(studio).get("media_url")

    out = fal_requests.recover(dsn=studio["dsn"], http=http)

    [row] = _requests(studio)
    assert out["rendered"] == [row["ref"]]
    assert http.calls[-1] == RESPONSE_URL                     # the result fetch
    assert studio["downloaded"] == [OUTPUT]
    [gen] = _generations(studio)
    assert gen["output_path"] and gen["tool"] == "kling"
    params = json.loads(gen["params_json"])
    assert params[ledger.GENERATION_REF_KEY] == row["ref"]    # reap's link
    assert params[fal_requests.GENERATION_REF_KEY] == row["ref"]
    assert params["concept_id"] == studio["concept_id"]
    # settled at what was held, linked to the clip
    settles = [e for e in ledger.entries(studio["account_id"], studio["dsn"])
               if e["kind"] == "settle"]
    assert settles and settles[0]["generation_id"] == gen["id"]
    assert "release" not in _kinds(studio)
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    assert ledger.available(studio["account_id"], studio["dsn"]) == \
        studio["funded"] - row["held"]
    # attached exactly as generate_for_shot does
    assert _shot(studio)["media_url"].endswith(".mp4")
    assert row["resolved_at"] and "recovered" in row["outcome"]
    assert row["generation_id"] == gen["id"]
    # and the reaper has nothing left to call an orphan
    assert ledger.reap(older_than="9999", dsn=studio["dsn"])["orphaned"] == []


def test_a_second_sweep_does_nothing(studio, stale_now):
    http = Fal(die_on_poll=True)
    _die_mid_render(studio, http)
    fal_requests.recover(dsn=studio["dsn"], http=http)
    again = fal_requests.recover(dsn=studio["dsn"], http=http)
    assert again["rendered"] == [] and again["released"] == []
    assert len(_generations(studio)) == 1


@pytest.mark.parametrize("fal_says, why", [
    ({"status": "COMPLETED", "status_payload": {"error": "content policy",
                                                "error_type": "moderation"}},
     "content policy"),
    ({"result": {"error": "out of memory", "error_type": "runtime"}}, "out of memory"),
    ({"result": {"detail": []}}, "no output"),
    ({"status_raises": urllib.error.HTTPError(STATUS_URL, 404, "Not Found", {}, None)},
     "HTTP 404"),
    # what fal._request actually raises since #69: the HTTPError wrapped in
    # a RuntimeError carrying fal's body -- must classify the same way
    ({"status_raises": _wrapped(404, "Not Found")}, "HTTP 404"),
    ({"result_raises": _wrapped(422, "Unprocessable Entity",
                                '{"detail": "duration must be an integer"}')},
     "HTTP 422"),
])
def test_a_job_fal_says_failed_is_released_with_the_reason(studio, stale_now,
                                                            fal_says, why):
    _die_mid_render(studio, Fal(die_on_poll=True))
    out = fal_requests.recover(dsn=studio["dsn"], http=Fal(**fal_says))

    [row] = _requests(studio)
    assert out["released"] == [row["ref"]]
    assert "release" in _kinds(studio) and "settle" not in _kinds(studio)
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    assert ledger.available(studio["account_id"], studio["dsn"]) == studio["funded"]
    assert row["outcome"].startswith("failed") and why in row["outcome"]
    # every attempt is a row -- the failed shape reap reads
    [gen] = _generations(studio)
    assert gen["output_path"] is None and why in gen["notes"]
    assert json.loads(gen["params_json"])[ledger.GENERATION_REF_KEY] == row["ref"]
    assert not _shot(studio).get("media_url")


def test_a_job_still_queued_waits_then_is_given_up(studio, stale_now, monkeypatch):
    _die_mid_render(studio, Fal(die_on_poll=True))
    queued = Fal(status="IN_QUEUE")
    assert fal_requests.recover(dsn=studio["dsn"], http=queued)["pending"]
    assert "release" not in _kinds(studio)
    assert _requests(studio)[0]["resolved_at"] is None

    monkeypatch.setattr(fal_requests, "GIVE_UP_SECONDS", -1)
    assert fal_requests.recover(dsn=studio["dsn"], http=queued)["released"]
    assert "release" in _kinds(studio)
    assert "IN_QUEUE" in _requests(studio)[0]["outcome"]


@pytest.mark.parametrize("trouble", [
    urllib.error.HTTPError(STATUS_URL, 503, "Unavailable", {}, None),
    _wrapped(503, "Service Unavailable"),
    _wrapped(429, "Too Many Requests"),
    urllib.error.URLError("connection reset"),
    RuntimeError("FAL_KEY not set"),
])
def test_no_answer_from_fal_leaves_the_hold_alone(studio, stale_now, trouble):
    """fal may have rendered and billed this job; releasing on OUR failure
    to ask would be the discrepancy ledger.reap refuses to paper over."""
    _die_mid_render(studio, Fal(die_on_poll=True))
    out = fal_requests.recover(dsn=studio["dsn"], http=Fal(status_raises=trouble))
    assert out["retry"] and not out["released"]
    assert "release" not in _kinds(studio) and "settle" not in _kinds(studio)
    assert _requests(studio)[0]["resolved_at"] is None
    assert _generations(studio) == []


# --- the sweep: partial deaths ----------------------------------------------

def test_a_worker_that_died_after_its_row_is_finished_without_a_second(
        studio, stale_now, monkeypatch):
    def die(*a, **k):
        raise WorkerDied()

    real_publish = fal._publish
    monkeypatch.setattr(fal, "_publish", die)
    with pytest.raises(WorkerDied):
        fal.generate_for_shot(studio["concept_id"], 1, db_path=studio["dsn"],
                              model="kling3-turbo-pro", http=Fal(), approved=True,
                              account_id=studio["account_id"])
    assert len(_generations(studio)) == 1
    monkeypatch.setattr(fal, "_publish", real_publish)

    http = Fal()
    out = fal_requests.recover(dsn=studio["dsn"], http=http)
    assert len(out["rendered"]) == 1
    assert http.calls == []                       # the clip was already on disk
    assert len(_generations(studio)) == 1         # reused, never duplicated
    assert _kinds(studio).count("settle") == 1
    assert _shot(studio)["media_url"].endswith(".mp4")


def test_a_hold_released_by_hand_still_gets_its_clip(studio, stale_now):
    """The 2026-09-26 pair were released by hand. Had they been tracked, a
    later sweep must still attach what fal made -- and not move money again."""
    _die_mid_render(studio, Fal(die_on_poll=True))
    [row] = _requests(studio)
    ledger.release(row["hold_id"], "orphan: released by hand", dsn=studio["dsn"])
    before = ledger.entries(studio["account_id"], studio["dsn"])

    out = fal_requests.recover(dsn=studio["dsn"], http=Fal())
    assert out["rendered"] == [row["ref"]]
    assert ledger.entries(studio["account_id"], studio["dsn"]) == before
    assert _shot(studio)["media_url"].endswith(".mp4")
    assert len(_generations(studio)) == 1


def test_a_nightly_candidate_is_recovered_onto_its_own_shot_row(studio, stale_now,
                                                                tmp_path):
    with pytest.raises(WorkerDied):
        fal.generate_candidates(PROMPT, tmp_path / "shot1", n=1, db_path=studio["dsn"],
                                model="ltx2.3", http=Fal(die_on_poll=True),
                                approved=True, account_id=studio["account_id"])
    [row] = _requests(studio)
    shot_id = json.loads(row["context_json"])["shot_id"]

    fal_requests.recover(dsn=studio["dsn"], http=Fal())
    [gen] = _generations(studio)
    assert gen["shot_id"] == shot_id and gen["tool"] == "ltx"
    assert gen["output_path"].endswith("cand1.mp4")
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    assert "settle" in _kinds(studio)


def test_an_exempt_accounts_render_is_recovered_with_no_money_moved(
        studio, stale_now):
    """No hold, but the render is still real: the clip is attached and the
    ledger is untouched."""
    accounts.set_credit_exempt("zeropage", True, dsn=studio["dsn"])
    _die_mid_render(studio, Fal(die_on_poll=True))
    [row] = _requests(studio)
    assert row["hold_id"] is None
    fal_requests.recover(dsn=studio["dsn"], http=Fal())
    assert _kinds(studio) == ["grant"]
    assert _shot(studio)["media_url"].endswith(".mp4")
    params = json.loads(_generations(studio)[0]["params_json"])
    assert ledger.GENERATION_REF_KEY not in params


def test_a_bare_generate_video_is_not_tracked_without_a_hold(tmp_path, monkeypatch):
    """No caller context and nothing held: there is nothing to recover and
    no database to write to -- the untracked path is unchanged."""
    monkeypatch.setenv(fal.SPEND_ENV, "1")
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setattr(fal, "POLL_SECONDS", 0)
    monkeypatch.setattr(fal, "_download",
                        lambda url, p: p.write_bytes(b"\x00"))
    monkeypatch.setattr(fal_requests.Tracker, "submitted",
                        lambda *a: pytest.fail("tracked an unbilled bare call"))
    fal.generate_video("x", tmp_path / "a.mp4", http=Fal())


def test_the_startup_sweep_finishes_the_orphan_then_stops(studio, stale_now,
                                                          monkeypatch):
    """What the app lifespan starts: it sweeps until nothing is open, then
    exits rather than polling forever."""
    _die_mid_render(studio, Fal(die_on_poll=True))
    real = fal_requests.recover
    monkeypatch.setattr(fal_requests, "recover",
                        lambda **kw: real(http=Fal(), **kw))
    thread = fal_requests.start_background(dsn=studio["dsn"], every=0)
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert fal_requests.open_count(dsn=studio["dsn"]) == 0
    assert _shot(studio)["media_url"].endswith(".mp4")
