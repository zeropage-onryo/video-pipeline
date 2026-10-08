"""
src/cut/index.py -- the index: "watches the footage before it cuts"
(docs/CUT_EDITOR.md section 5.3, phase 2).

One clip, indexed once per file (by sha256), in this order:

1. PROBE + PROXY. ffprobe at INDEX_FPS; a 720p H.264 proxy with a
   keyframe every second, made only when the source is bigger than that
   (every renderer here already makes 720p, so usually the proxy IS the
   file). Everything below reads the proxy.
2. SHOTS. ffmpeg's own scene-change score (`select=gt(scene,T)`) -- no
   OpenCV, no new dependency. A generated clip is nearly always one shot.
3. SHOT LOG. ONE Gemini call on the proxy, for every shot at once: who,
   action, objects, setting, emotion, shot size, angle, camera, quality
   flags, and whether anyone SPEAKS. The prompt is prompts/cut/shot_log.txt;
   the answer is JSON checked by `check_log` -- prompts request, code
   checks: a shot size off the list is dropped rather than stored as if it
   were one, a quality flag off the list likewise, a shot count that does
   not match is a note.
4. TRANSCRIPT. fal's Whisper (the fal key already on Fly; no new vendor)
   at word level with speakers -- only when the file has sound AND the
   shot log heard speech. Whisper on ambience (rain, a city, a score)
   invents words ("Thank you."), and most generated clips are exactly
   that, so the check that runs first is also what keeps a hallucinated
   line out of the index, and out of the bill. An uploaded voiceover
   (asset:) has no picture and is speech by definition, so it goes
   straight to the transcript.
5. EMBED + WRITE. Segments and shots embedded (RETRIEVAL_DOCUMENT) and
   everything written in one transaction (moments.write).

Every model call is metered: the shot log through generate_with_retry
(stage `shot_log`), the transcript with its own llm_calls row (stage
`transcribe`) that is UNPRICED -- fal's Whisper page states no price, and a
guessed $0 would read as free on /costs.

Nothing here raises past `index_media`: a failed step is recorded on the
media_index row with status `failed` and the reason, so a backfill over a
hundred clips reports the one that broke instead of stopping on it.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from .. import db
from . import doc as d
from . import moments, sources

INDEX_FPS = d.DEFAULT_FPS
PROXY_HEIGHT = 720
PROXY_MAX_BYTES = 40 * 1024 * 1024
SCENE_THRESHOLD = 0.35
MIN_SHOT_FRAMES = 12
INLINE_VIDEO_LIMIT = 19_000_000
TRANSCRIBE_MODEL = "fal-ai/whisper"
# fal bills Whisper by GPU compute time and its model page states no rate
# (it renders "$0 per compute second"; checked 2026-10-08), so the meter
# prices it by the AUDIO minute at a third-party reading of fal's cost
# (~$0.00544 per 10-minute clip, costbench.com, 2026-10-08). An estimate
# like every figure on /costs, and unverified against fal's own page:
# FAL_WHISPER_USD_PER_MIN overrides it.
WHISPER_USD_PER_MIN = 0.000544
SEGMENT_GAP_S = 0.8
PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "cut" / "shot_log.txt"

SHOT_SIZES = ("extreme close-up", "close-up", "medium close-up", "medium", "medium wide",
              "wide", "extreme wide")
ANGLES = ("eye level", "low angle", "high angle", "overhead", "dutch", "over the shoulder",
          "point of view")
QUALITY_FLAGS = ("blur", "bad focus", "flub", "black frames", "flicker", "artifact",
                 "watermark", "text on screen", "audio clipping")


class IndexFailed(RuntimeError):
    pass


def log_model() -> str:
    from .. import gemini_utils
    return gemini_utils.FAST_MODEL


# --------------------------------------------------------------------------
# 1-2: the file, the proxy, the shots
# --------------------------------------------------------------------------

def fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ffmpeg(*args, timeout=300) -> subprocess.CompletedProcess:
    exe = sources.ffmpeg_bin()
    if not exe:
        raise IndexFailed("ffmpeg is not installed on this machine")
    return subprocess.run([exe, "-hide_banner", "-nostdin", *args], capture_output=True,
                          text=True, timeout=timeout)


def make_proxy(path: Path, info: dict, workdir: Path) -> Path:
    if (info.get("height") or 0) <= PROXY_HEIGHT and path.stat().st_size <= PROXY_MAX_BYTES:
        return path
    out = workdir / "proxy.mp4"
    proc = _ffmpeg("-y", "-i", str(path), "-vf", f"scale=-2:{PROXY_HEIGHT},fps={INDEX_FPS}",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                   "-g", str(INDEX_FPS), "-c:a", "aac", "-b:a", "96k", str(out))
    if proc.returncode != 0 or not out.is_file():
        raise IndexFailed("could not make a proxy: " + (proc.stderr.strip().splitlines() or ["?"])[-1])
    return out


_PTS = re.compile(r"pts_time:([0-9.]+)")


def shot_cuts(path: Path, fps: int = INDEX_FPS) -> list[int]:
    """Frames where a new shot starts (never 0), from ffmpeg's scene score."""
    proc = _ffmpeg("-i", str(path), "-an", "-vf",
                   f"select='gt(scene,{SCENE_THRESHOLD})',showinfo", "-f", "null", "-")
    return sorted({d.to_frames(float(t), fps) for t in _PTS.findall(proc.stderr or "")} - {0})


def shots_from_cuts(cuts: list[int], frames: int) -> list[tuple[int, int]]:
    """Cut points -> [(start, end)], dropping any cut that would leave a
    shot shorter than MIN_SHOT_FRAMES (a flash frame is not a shot)."""
    bounds = [0]
    for c in sorted(cuts):
        if c - bounds[-1] >= MIN_SHOT_FRAMES and frames - c >= MIN_SHOT_FRAMES:
            bounds.append(c)
    bounds.append(frames)
    return [(a, b) for a, b in zip(bounds, bounds[1:]) if b > a]


# --------------------------------------------------------------------------
# 3: the shot log
# --------------------------------------------------------------------------

def build_prompt(shots: list[tuple[int, int]], fps: int) -> str:
    listed = "\n".join(f"{i}. {a / fps:.2f}s - {b / fps:.2f}s" for i, (a, b) in enumerate(shots, 1))
    return PROMPT_PATH.read_text().format(count=len(shots), shots=listed)


def _pick(value, allowed) -> Optional[str]:
    v = str(value or "").strip().lower()
    return v if v in allowed else None


def check_log(raw: str, shots: list[tuple[int, int]]) -> tuple[dict, list[str]]:
    """The model's JSON -> ({"speech", "shots": [...]}, notes). Never
    raises on a bad answer: an unreadable log is logged as unreadable."""
    from .. import gemini_utils
    notes: list[str] = []
    try:
        data = json.loads(gemini_utils.strip_fences(raw or ""))
    except (TypeError, ValueError):
        return {"speech": None, "shots": []}, ["the shot log was not readable JSON"]
    if not isinstance(data, dict):
        return {"speech": None, "shots": []}, ["the shot log was not an object"]
    got = [s for s in data.get("shots") or [] if isinstance(s, dict)]
    if len(got) != len(shots):
        notes.append(f"the shot log described {len(got)} shot(s) of {len(shots)}")
    out = []
    for i, s in enumerate(got[:len(shots)]):
        size, angle = _pick(s.get("shot_size"), SHOT_SIZES), _pick(s.get("angle"), ANGLES)
        if s.get("shot_size") and not size:
            notes.append(f"shot {i + 1}: shot size {s.get('shot_size')!r} is not on the list")
        quality = [q for q in (str(x).strip().lower() for x in s.get("quality") or [])
                   if q in QUALITY_FLAGS]
        out.append({
            "n": i + 1,
            "summary": str(s.get("summary") or "").strip()[:400],
            "people": [str(x).strip()[:120] for x in s.get("people") or [] if str(x).strip()][:8],
            "action": str(s.get("action") or "").strip()[:200],
            "objects": [str(x).strip()[:80] for x in s.get("objects") or [] if str(x).strip()][:12],
            "setting": str(s.get("setting") or "").strip()[:160],
            "emotion": str(s.get("emotion") or "").strip()[:60],
            "shot_size": size, "angle": angle,
            "camera": str(s.get("camera") or "").strip()[:60],
            "quality": quality,
        })
    speech = data.get("speech")
    return {"speech": speech if isinstance(speech, bool) else None, "shots": out}, notes


def _video_part(client, path: Path):
    from google.genai import types
    data = path.read_bytes()
    if len(data) <= INLINE_VIDEO_LIMIT:
        return types.Part.from_bytes(data=data, mime_type="video/mp4")
    import time
    handle = client.files.upload(file=str(path), config={"mime_type": "video/mp4"})
    deadline = time.time() + 120
    while getattr(handle.state, "name", str(handle.state)) == "PROCESSING" and time.time() < deadline:
        time.sleep(2)
        handle = client.files.get(name=handle.name)
    if getattr(handle.state, "name", str(handle.state)) != "ACTIVE":
        raise IndexFailed("Gemini did not finish processing the clip")
    return handle


def shot_log(proxy: Path, shots: list[tuple[int, int]], *, client, account_id: Optional[int],
             fps: int = INDEX_FPS) -> tuple[dict, list[str]]:
    from .. import gemini_utils
    raw = gemini_utils.generate_with_retry(
        client, log_model(), [_video_part(client, proxy), build_prompt(shots, fps)],
        stage="shot_log", account_id=account_id)
    return check_log(raw, shots)


# --------------------------------------------------------------------------
# 4: the transcript
# --------------------------------------------------------------------------

def extract_audio(path: Path, workdir: Path) -> Path:
    """Mono 16 kHz MP3: what Whisper hears anyway, at a few KB a second."""
    out = workdir / "speech.mp3"
    proc = _ffmpeg("-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                   "-c:a", "libmp3lame", "-b:a", "48k", str(out))
    if proc.returncode != 0 or not out.is_file():
        raise IndexFailed("could not extract the audio")
    return out


def audio_url(path: Path, sha: str, account_id: Optional[int]) -> str:
    """Somewhere fal's servers can fetch the audio from: the bucket when
    it is configured (the clip itself is already there), else a data URI."""
    from .. import media
    url = media.mirror(path, f"renders/cut/audio/{sha[:24]}.mp3", account_id,
                       content_type="audio/mpeg", derive=False)
    if url:
        return media.url_for(f"/renders/cut/audio/{sha[:24]}.mp3", account_id)
    return "data:audio/mpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def _span(chunk: dict) -> tuple[Optional[float], Optional[float]]:
    ts = chunk.get("timestamp") or [None, None]
    try:
        return (float(ts[0]) if ts[0] is not None else None,
                float(ts[1]) if len(ts) > 1 and ts[1] is not None else None)
    except (TypeError, ValueError, IndexError):
        return None, None


def parse_transcript(result: dict, fps: int, frames: int) -> dict[str, list[dict]]:
    """fal Whisper's {"chunks": [{"timestamp": [s, e], "text", "speaker"?}],
    "diarization_segments": [{"timestamp", "speaker"}]} -> word and segment
    moments, in frames, clamped to the clip."""
    diar = []
    for seg in result.get("diarization_segments") or []:
        s, e = _span(seg)
        if s is not None and e is not None:
            diar.append((s, e, seg.get("speaker")))

    def speaker_at(s: float, e: float) -> Optional[str]:
        best, overlap = None, 0.0
        for a, b, who in diar:
            o = min(b, e) - max(a, s)
            if o > overlap:
                best, overlap = who, o
        return best

    words = []
    for ch in result.get("chunks") or []:
        text = str(ch.get("text") or "").strip()
        s, e = _span(ch)
        if not text or s is None:
            continue
        e = e if e is not None and e > s else s + 0.2
        start, end = min(d.to_frames(s, fps), frames), min(max(d.to_frames(e, fps),
                                                              d.to_frames(s, fps) + 1), frames)
        if end <= start:
            continue
        words.append({"kind": "word", "start_f": start, "end_f": end, "text": text,
                      "speaker": ch.get("speaker") or speaker_at(s, e), "_s": s, "_e": e})

    segments, current = [], []

    def close():
        if current:
            segments.append({"kind": "segment", "start_f": current[0]["start_f"],
                             "end_f": current[-1]["end_f"],
                             "text": " ".join(w["text"] for w in current).strip(),
                             "speaker": current[0]["speaker"]})
            current.clear()

    for w in words:
        if current and (w["_s"] - current[-1]["_e"] > SEGMENT_GAP_S
                        or w["speaker"] != current[-1]["speaker"]):
            close()
        current.append(w)
        if re.search(r"[.!?]$", w["text"]):
            close()
    close()
    for w in words:
        w.pop("_s")
        w.pop("_e")
    return {"words": words, "segments": segments}


def whisper_usd(seconds: float) -> float:
    """The estimated price of transcribing `seconds` of audio."""
    try:
        rate = float(os.environ.get("FAL_WHISPER_USD_PER_MIN") or WHISPER_USD_PER_MIN)
    except ValueError:
        rate = WHISPER_USD_PER_MIN
    return round(max(0.0, float(seconds or 0)) / 60.0 * rate, 6)


def transcribe(path: Path, sha: str, *, account_id: Optional[int], workdir: Path,
               fps: int = INDEX_FPS, frames: int, http: Optional[Callable] = None) -> dict:
    from .. import fal, spend
    if http is None and not fal.has_key(account_id):
        raise IndexFailed("no FAL_KEY -- the transcript needs fal's Whisper")
    body = {"audio_url": audio_url(extract_audio(path, workdir), sha, account_id),
            "task": "transcribe", "chunk_level": "word", "diarize": True}
    ok = False
    try:
        result, _ = fal._submit_and_wait(TRANSCRIBE_MODEL, body, http=http, account_id=account_id)
        ok = True
    finally:
        # one row per call, priced by the audio's length (whisper_usd),
        # never by tokens -- Whisper reports none
        spend.record_call(stage="transcribe", model_asked=TRANSCRIBE_MODEL, usage={},
                          ok=ok, account_id=account_id,
                          cost_usd=whisper_usd(frames / fps if fps else 0))
    out = parse_transcript(result, fps, frames)
    out["language"] = (result.get("inferred_languages") or [None])[0]
    return out


# --------------------------------------------------------------------------
# 5: one clip, start to finish
# --------------------------------------------------------------------------

def _shot_text(entry: dict) -> str:
    bits = [entry["summary"], entry["action"], entry["setting"], entry["emotion"],
            ", ".join(entry["people"]), ", ".join(entry["objects"]),
            entry["shot_size"] or "", entry["angle"] or "", entry["camera"]]
    return ". ".join(b for b in bits if b)


def _embed(texts: list[str], embed: Optional[Callable]) -> Optional[list]:
    if not texts:
        return []
    if embed is None:
        from .. import rag
        client = rag.make_client()

        def embed(batch):
            return rag.embed_texts(batch, client, "RETRIEVAL_DOCUMENT")
    return embed(texts)


def index_media(handle: str, *, account_id: Optional[int], dsn: Optional[str] = None,
                force: bool = False, gemini=None, http: Optional[Callable] = None,
                embed: Optional[Callable] = None) -> dict[str, Any]:
    """Index one clip. Returns the media_index row plus `skipped`/`notes`.
    `gemini`, `http` and `embed` are the three seams a test replaces (the
    Gemini client, fal's HTTP, the embedder) -- one each, and nothing else
    in this module talks to a network."""
    notes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="zpf-index-") as tmp:
        work = Path(tmp)
        try:
            path = sources.resolve(handle, account_id=account_id, workdir=work, dsn=dsn)
            info = sources.probe(path, INDEX_FPS)
        except sources.SourceError as e:
            return {"media": handle, "status": "failed", "notes": str(e)}
        sha = fingerprint(path)
        if not force and moments.is_current(handle, sha, account_id=account_id, dsn=dsn):
            row = moments.indexed(handle, account_id=account_id, dsn=dsn)
            return {**row, "skipped": "already indexed"}
        frames, found, speech = info["frames"], [], None
        try:
            if info["video"]:
                proxy = make_proxy(path, info, work)
                shots = shots_from_cuts(shot_cuts(proxy), frames)
                if gemini is None:
                    from .. import gemini_utils
                    gemini = gemini_utils.client_for(account_id)
                log, log_notes = shot_log(proxy, shots, client=gemini, account_id=account_id)
                notes += log_notes
                speech = log["speech"]
                for (a, b), entry in zip(shots, log["shots"]):
                    found.append({"kind": "shot", "start_f": a, "end_f": b,
                                  "text": _shot_text(entry) or f"shot {entry['n']}",
                                  "tags": entry})
                for (a, b) in shots[len(log["shots"]):]:
                    found.append({"kind": "shot", "start_f": a, "end_f": b,
                                  "text": "unlogged shot", "tags": None})
            else:
                speech = True          # an uploaded voiceover is speech by definition
            if info["audio"] and speech:
                t = transcribe(path, sha, account_id=account_id, workdir=work, frames=frames,
                               http=http)
                found += t["segments"] + t["words"]
                if info["video"] and not t["words"]:
                    notes.append("speech was heard but Whisper returned no words")
            elif info["audio"] and speech is None:
                notes.append("not transcribed: the shot log could not say whether anyone speaks")
            to_embed = [m for m in found if m["kind"] in moments.EMBEDDED_KINDS]
            try:
                for m, vec in zip(to_embed, _embed([m["text"] for m in to_embed], embed)):
                    m["embedding"] = vec
            except Exception as e:                       # noqa: BLE001
                notes.append(f"stored without embeddings (search by words only): "
                             f"{type(e).__name__}: {e}"[:300])
            row = moments.write(handle, sha, account_id=account_id, fps=INDEX_FPS,
                                frames=frames, has_audio=info["audio"], speech=speech,
                                moments=found, notes="; ".join(notes) or None, dsn=dsn)
        except Exception as e:                           # noqa: BLE001
            reason = f"{type(e).__name__}: {e}"[:500]
            row = moments.write(handle, sha, account_id=account_id, fps=INDEX_FPS,
                                frames=frames, has_audio=info["audio"], speech=speech,
                                moments=[], status="failed", notes=reason, dsn=dsn)
    return {**row, "notes": row.get("notes")}


# --------------------------------------------------------------------------
# what to index
# --------------------------------------------------------------------------

def handles_for_concept(concept_id: int, *, account_id: Optional[int],
                        dsn: Optional[str] = None) -> list[str]:
    """The banked clips on a concept's slots, in order (a slot with no
    clip, or with no Asset Bank row, has nothing to index)."""
    from .. import media, preprod
    from . import assemble
    concept = preprod.get_concept(concept_id, dsn, account_id=account_id)
    if concept is None:
        raise LookupError(f"no concept {concept_id}")
    index = assemble._asset_index(account_id, dsn)
    out = []
    for s in assemble.clip_slots(concept):
        row = s["media_url"] and (index.get(s["media_url"])
                                  or index.get(media.tail_for(s["media_url"]) or ""))
        if row and d.handle("gen", row["id"]) not in out:
            out.append(d.handle("gen", row["id"]))
    return out


def all_handles(*, account_id: Optional[int], dsn: Optional[str] = None) -> list[str]:
    """Every clip and every uploaded audio file this account has."""
    with db.connect(dsn) as conn:
        gen = conn.execute(
            "SELECT id FROM generated_assets WHERE media_kind = 'video' "
            "AND account_id IS NOT DISTINCT FROM %s ORDER BY id", (account_id,)).fetchall()
        audio = (conn.execute(
            "SELECT id FROM cut_media WHERE account_id IS NOT DISTINCT FROM %s ORDER BY id",
            (account_id,)).fetchall() if db.table_exists(conn, "cut_media") else [])
    return [d.handle("gen", r["id"]) for r in gen] + [d.handle("asset", r["id"]) for r in audio]


def find(q: str, *, account_id: Optional[int], k: int = 8, dsn: Optional[str] = None,
         embed_query: Optional[Callable] = None) -> dict[str, Any]:
    """Search the index and say what each hit is: the clip's handle, the
    concept it belongs to, where in it (frames and seconds), and what
    matched. THE search -- the /api/cut/search route and the pill's
    `search_footage` tool both call this, so they cannot disagree.

    The query is embedded here (RETRIEVAL_QUERY); a failed embed searches
    the words alone and says so rather than failing the search."""
    vector, notes = None, []
    try:
        if embed_query is None:
            from .. import rag
            client = rag.make_client()

            def embed_query(text):
                return rag.embed_texts([text], client, "RETRIEVAL_QUERY")[0]
        vector = embed_query(q) if (q or "").strip() else None
    except Exception as e:                               # noqa: BLE001
        notes.append(f"meaning search unavailable ({type(e).__name__}); searched the words only")
    out = moments.search(q, account_id=account_id, k=k, query_vector=vector, dsn=dsn)
    out["notes"] = notes + [n for n in out["notes"] if not (notes and "no embedding key" in n)]
    from .. import preprod, render_assets
    assets = {f"gen:{r['id']}": r for r in render_assets.list_all(dsn, account_id=account_id,
                                                                  include_deleted=True)}
    concept_ids = {a["concept_id"] for a in assets.values() if a.get("concept_id")}
    titles = {c["id"]: c.get("title") for c in
              preprod.get_concepts(sorted(concept_ids), dsn, account_id=account_id)} \
        if concept_ids else {}
    for h in out["results"]:
        asset = assets.get(h["media"]) or {}
        h["concept_id"] = asset.get("concept_id")
        h["concept_title"] = titles.get(asset.get("concept_id"))
        h["shot_n"] = asset.get("shot_n")
        h["media_url"] = asset.get("media_url")
        h.pop("id", None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Index clips so the editor can search them.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="index every clip not indexed yet")
    b.add_argument("--account", help="account slug (default: the oldest account)")
    b.add_argument("--dry-run", action="store_true", help="list what would be indexed")
    one = sub.add_parser("one", help="index one handle, e.g. gen:85")
    one.add_argument("handle")
    one.add_argument("--account")
    one.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    from .. import accounts
    account_id = accounts.resolve_account(args.account)
    moments.init()
    handles = [args.handle] if args.cmd == "one" else all_handles(account_id=account_id)
    for h in handles:
        if args.cmd == "backfill" and args.dry_run:
            row = moments.indexed(h, account_id=account_id)
            print(f"{h}: {'indexed ' + row['created_at'] if row else 'NOT indexed'}")
            continue
        r = index_media(h, account_id=account_id, force=getattr(args, "force", False))
        print(f"{h}: {r.get('skipped') or r.get('status')} -- shots {r.get('shots', 0)}, "
              f"words {r.get('words', 0)}, speech {r.get('speech')}"
              + (f" -- {r['notes']}" if r.get("notes") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
