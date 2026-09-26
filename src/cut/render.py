"""
src/cut/render.py -- the render of record (docs/CUT_EDITOR.md section 5.5).

A doc compiles to ONE ffmpeg invocation with ONE `filter_complex`:

    video  trim/setpts -> fps/scale/pad -> concat (cuts) | xfade (transitions)
           -> black for any gap -> ass (burned captions)
    audio  per clip: atrim -> volume -> afade (a transition's overlap) -> adelay
           per track: amix -> pad/trim to the cut's exact length
           ducking:   sidechaincompress, keyed off the role it ducks under
           master:    amix -> loudnorm to -14 LUFS (social-video loudness)

`compile_args` is PURE -- a doc and a map of handle -> file in, an argv
out -- so the graph is tested without ffmpeg. `render` runs it, checks
what came out, files the MP4 under data/renders/cut/ and mirrors it to R2
through media.mirror (the one writer-side key builder, so it gets the
tenant prefix like every other render).

No ledger hold: nothing generative runs here. Manual editing stays free,
the bet invideo made.

What v0 does not render, and refuses rather than fakes: more than one
video track with clips on it (V2 overlays need `overlay`, which is the
Grade/B-roll phase), and any doc the validator rejects. What it degrades
on, loudly: an ffmpeg built without libass (Homebrew's default) cannot
burn captions, so the cut is exported without them, the `.ass` file is
written beside it, and the result says so in `notes`.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from . import doc as d
from . import sources
from . import validate as v

LOUDNESS_LUFS = -14
TRUE_PEAK = -1.5
SAMPLE_RATE = 48000
RENDER_TIMEOUT = 900
CUT_DIR = sources.RENDERS_DIR / "cut"

# Ducking: threshold is the key level where the music starts to drop
# (linear, ~ -34 dBFS), ratio how hard. Speech-over-bed values; the bed's
# own level is its clip gain.
DUCK = "threshold=0.02:ratio=8:attack=20:release=400"

CAPTION_PRESETS = {
    # font scale is a fraction of frame height; margin keeps text clear
    # of the platform UI at the bottom of a 9:16 frame
    "preset:bold_center": {"font": "Arial", "scale": 0.045, "margin": 0.2, "bold": -1},
}


class RenderError(RuntimeError):
    pass


def _s(frames: int, fps: int) -> str:
    """Frames -> seconds as ffmpeg takes them: exact to the microsecond,
    never scientific notation."""
    return f"{frames / fps:.6f}".rstrip("0").rstrip(".") or "0"


@lru_cache(maxsize=4)
def _filters(exe: str) -> frozenset:
    try:
        out = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True,
                             text=True, timeout=20).stdout
    except (subprocess.SubprocessError, OSError):
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and "->" in parts[2]:
            names.add(parts[1])
    return frozenset(names)


def can_burn_captions(exe: Optional[str] = None) -> bool:
    exe = exe or sources.ffmpeg_bin()
    return bool(exe) and "ass" in _filters(exe)


# --------------------------------------------------------------------------
# captions -> .ass
# --------------------------------------------------------------------------

def _ass_time(frames: int, fps: int) -> str:
    cs = round(frames * 100 / fps)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    # braces open override blocks in ASS; a newline is \N
    return (text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
            .replace("\r", "").replace("\n", "\\N"))


def ass_document(doc: dict) -> Optional[str]:
    """Every caption track as one ASS script, or None when there are no
    cues. Pure."""
    tracks = [t for t in d.tracks_of(doc, "caption") if t.get("cues")]
    if not tracks:
        return None
    w, h = doc["size"]
    fps = doc["fps"]
    styles, events = [], []
    for i, t in enumerate(tracks):
        p = CAPTION_PRESETS.get(t.get("style"), CAPTION_PRESETS["preset:bold_center"])
        name = f"S{i + 1}"
        size = max(12, round(h * p["scale"]))
        styles.append(
            f"Style: {name},{p['font']},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
            f"{p['bold']},0,0,0,100,100,0,0,1,{max(2, size // 14)},1,2,"
            f"{round(w * 0.08)},{round(w * 0.08)},{round(h * p['margin'])},1")
        for q in t["cues"]:
            events.append(f"Dialogue: 0,{_ass_time(q['start'], fps)},{_ass_time(q['end'], fps)},"
                          f"{name},,0,0,0,,{_ass_text(q['text'])}")
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events, ""])


# --------------------------------------------------------------------------
# the graph
# --------------------------------------------------------------------------

def _video_graph(doc: dict, index: dict[str, int], parts: list[str],
                 burn: Optional[str]) -> str:
    fps, (w, h), total = doc["fps"], doc["size"], doc["duration"]
    norm = (f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p,settb=AVTB")
    with_clips = [t for t in d.tracks_of(doc, "video") if t.get("clips")]
    if len(with_clips) > 1:
        raise RenderError("v0 renders one video track; "
                          f"{', '.join(t['id'] for t in with_clips)} all have clips")
    clips = sorted(with_clips[0]["clips"], key=lambda c: c["at"]) if with_clips else []

    def black(frames: int, label: str) -> str:
        parts.append(f"color=c=black:s={w}x{h}:r={fps}:d={_s(frames, fps)},"
                     f"format=yuv420p,setsar=1,settb=AVTB[{label}]")
        return label

    acc, cursor, n = None, 0, 0

    def join(seg: str, transition: int) -> None:
        nonlocal acc, n
        if acc is None:
            acc = seg
            return
        n += 1
        out = f"vj{n}"
        if transition:
            parts.append(f"[{acc}][{seg}]xfade=transition=fade:duration={_s(transition, fps)}:"
                         f"offset={_s(cursor - transition, fps)}[{out}]")
        else:
            parts.append(f"[{acc}][{seg}]concat=n=2:v=1:a=0[{out}]")
        acc = out

    for k, c in enumerate(clips):
        frames = int((c.get("transition_in") or {}).get("frames") or 0)
        if c["at"] > cursor:
            join(black(c["at"] - cursor, f"vg{k}"), 0)
            cursor = c["at"]
        seg = f"v{k}"
        parts.append(f"[{index[c['media']]}:v]trim=start={_s(c['src_in'], fps)}:"
                     f"end={_s(c['src_out'], fps)},setpts=PTS-STARTPTS,{norm}[{seg}]")
        join(seg, frames)
        cursor = c["at"] + d.clip_length(c) if not frames else cursor - frames + d.clip_length(c)
    if acc is None:
        acc = black(max(total, 1), "vblack")
        cursor = max(total, 1)
    tail = []
    if cursor < total:
        tail.append(f"tpad=stop_mode=add:stop_duration={_s(total - cursor, fps)}:color=black")
    if burn:
        tail.append(f"ass={burn}")
    tail.append(f"trim=end={_s(total, fps)}")
    parts.append(f"[{acc}]{','.join(tail)}[vout]")
    return "vout"


def _audio_graph(doc: dict, index: dict[str, int], parts: list[str]) -> str:
    fps, total = doc["fps"], doc["duration"]
    whole = _s(total, fps)
    fit = f"apad=whole_dur={whole},atrim=end={whole}"
    streams: dict[str, str] = {}          # track id -> its mixed stream label
    roles: dict[str, list[str]] = {}      # role -> track ids
    for t in d.tracks_of(doc, "audio"):
        clips = sorted(t.get("clips") or [], key=lambda c: c["at"])
        if not clips:
            continue
        labels = []
        for k, c in enumerate(clips):
            nxt = clips[k + 1] if k + 1 < len(clips) else None
            chain = [f"atrim=start={_s(c['src_in'], fps)}:end={_s(c['src_out'], fps)}",
                     "asetpts=PTS-STARTPTS",
                     f"aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo"]
            gain = float(c.get("gain_db") or 0)
            if gain:
                chain.append(f"volume={gain:g}dB")
            fin = int((c.get("transition_in") or {}).get("frames") or 0)
            if fin:
                chain.append(f"afade=t=in:st=0:d={_s(fin, fps)}")
            fout = int(((nxt or {}).get("transition_in") or {}).get("frames") or 0)
            if fout:
                chain.append(f"afade=t=out:st={_s(d.clip_length(c) - fout, fps)}:d={_s(fout, fps)}")
            if c["at"]:
                chain.append(f"adelay=delays={round(c['at'] * 1000 / fps)}:all=1")
            label = f"a{t['id']}_{k}"
            parts.append(f"[{index[c['media']]}:a]{','.join(chain)}[{label}]")
            labels.append(label)
        out = f"t{t['id']}"
        if len(labels) == 1:
            parts.append(f"[{labels[0]}]{fit}[{out}]")
        else:
            parts.append("".join(f"[{x}]" for x in labels)
                         + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0,{fit}[{out}]")
        streams[t["id"]] = out
        roles.setdefault(t.get("role"), []).append(t["id"])

    if not streams:
        parts.append(f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=end={whole}[aout]")
        return "aout"

    # ducking: each ducked track takes a copy of the key role's mix
    keys: dict[str, list[str]] = {}
    for t in d.tracks_of(doc, "audio"):
        under = t.get("duck_under")
        if t["id"] in streams and under and roles.get(under):
            keys.setdefault(under, []).append(t["id"])
    for role, ducked in keys.items():
        # the key is the role's mix; it is split so it can be HEARD (main)
        # and also drive every compressor that ducks under it (copies)
        key_tracks = roles[role]
        if len(key_tracks) == 1:
            key = streams[key_tracks[0]]
        else:
            key = f"key_{role}"
            parts.append("".join(f"[{streams[x]}]" for x in key_tracks)
                         + f"amix=inputs={len(key_tracks)}:normalize=0[{key}]")
        main = f"{key}_main"
        copies = [f"{key}_sc{i}" for i in range(len(ducked))]
        parts.append(f"[{key}]asplit={len(copies) + 1}[{main}]"
                     + "".join(f"[{c}]" for c in copies))
        for x in key_tracks:
            streams[x] = None
        streams[f"_key_{role}"] = main
        for tid, sc in zip(ducked, copies):
            out = f"{streams[tid]}_duck"
            parts.append(f"[{streams[tid]}][{sc}]sidechaincompress={DUCK}[{out}]")
            streams[tid] = out

    live = [s for s in streams.values() if s]
    master = f"loudnorm=I={LOUDNESS_LUFS}:TP={TRUE_PEAK}:LRA=11,aresample={SAMPLE_RATE},atrim=end={whole}"
    if len(live) == 1:
        parts.append(f"[{live[0]}]{master}[aout]")
    else:
        parts.append("".join(f"[{x}]" for x in live)
                     + f"amix=inputs={len(live)}:normalize=0:dropout_transition=0,{master}[aout]")
    return "aout"


def compile_args(doc: dict, paths: dict[str, Path], out: Path, *,
                 burn: Optional[str] = None, ffmpeg: str = "ffmpeg") -> list[str]:
    """The whole ffmpeg argv for one doc. Pure. `burn` is the .ass file
    name to burn in (relative to the cwd ffmpeg runs in), or None."""
    handles = d.handles(doc)
    missing = [h for h in handles if h not in paths]
    if missing:
        raise RenderError(f"no file for {', '.join(missing)}")
    index = {h: i for i, h in enumerate(handles)}
    parts: list[str] = []
    vout = _video_graph(doc, index, parts, burn)
    aout = _audio_graph(doc, index, parts)
    argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for h in handles:
        argv += ["-i", str(paths[h])]
    argv += ["-filter_complex", ";".join(parts),
             "-map", f"[{vout}]", "-map", f"[{aout}]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-r", str(doc["fps"]),
             "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE),
             "-movflags", "+faststart", "-t", _s(doc["duration"], doc["fps"]), str(out)]
    return argv


# --------------------------------------------------------------------------
# running it
# --------------------------------------------------------------------------

def render(doc: dict, *, account_id: Optional[int], name: str,
           paths: Optional[dict[str, Path]] = None, media: Optional[dict] = None,
           dsn: Optional[str] = None, out_dir: Optional[Path] = None) -> dict[str, Any]:
    """Render a doc to data/renders/cut/<name>.mp4 (and R2). Returns
    {"stored", "url", "path", "seconds", "bytes", "notes"}. Raises
    RenderError / sources.SourceError / validate.InvalidDoc with a reason
    a person can act on."""
    exe = sources.ffmpeg_bin()
    if not exe:
        raise RenderError("ffmpeg is not installed on this machine")
    if doc.get("duration", 0) <= 0:
        raise RenderError("the timeline is empty")
    out_dir = Path(out_dir or CUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="zpf-cut-") as tmp:
        work = Path(tmp)
        if paths is None or media is None:
            paths, media = sources.gather(d.handles(doc), account_id=account_id,
                                          fps=doc["fps"], workdir=work, dsn=dsn)
        v.validate(doc, media)
        ass = ass_document(doc)
        burn = None
        if ass:
            (work / "captions.ass").write_text(ass, encoding="utf-8")
            if can_burn_captions(exe):
                burn = "captions.ass"
            else:
                shutil.copyfile(work / "captions.ass", out_dir / f"{name}.ass")
                notes.append("captions NOT burned in: this ffmpeg has no libass -- "
                             f"written beside the MP4 as {name}.ass")
        tmp_out = work / "out.mp4"
        argv = compile_args(doc, paths, tmp_out, burn=burn, ffmpeg=exe)
        started = time.monotonic()
        try:
            proc = subprocess.run(argv, cwd=work, capture_output=True, text=True,
                                  timeout=RENDER_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise RenderError(f"ffmpeg ran past {RENDER_TIMEOUT}s") from None
        if proc.returncode != 0 or not tmp_out.is_file():
            tail = (proc.stderr or "").strip().splitlines()[-3:]
            raise RenderError("ffmpeg failed: " + (" | ".join(tail) or f"exit {proc.returncode}"))
        final = out_dir / f"{name}.mp4"
        shutil.move(str(tmp_out), final)
    got = sources.probe(final, doc["fps"])
    if abs(got["frames"] - doc["duration"]) > 2:
        notes.append(f"rendered {got['frames']} frames against a {doc['duration']}-frame cut")

    from .. import media as media_mod
    stored = url = None
    if final.parent.resolve() == CUT_DIR.resolve():
        # served by the app's /renders mount; the mirror is best-effort, and
        # url_for mints the R2 string when it landed there
        stored = f"/renders/cut/{final.name}"
        media_mod.mirror(final, f"renders/cut/{final.name}", account_id,
                         content_type="video/mp4", derive=False)
        url = media_mod.url_for(stored, account_id)
    return {"stored": stored, "url": url,
            "path": str(final), "seconds": got["seconds"],
            "bytes": final.stat().st_size, "notes": notes,
            "elapsed": round(time.monotonic() - started, 1)}
