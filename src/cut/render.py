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

A still image (an uploaded photo, a Nano render) is an input like any
clip, read with `-loop 1 -framerate fps -t <what the cut asks of it>`, so
the same trim chain holds it on screen (`stills_in`).

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
from . import lanes, sources
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
    # font scale is a fraction of frame height; margin (vertical) keeps
    # text clear of the platform UI at the bottom of a 9:16 frame. `align`
    # is the ASS numpad alignment (2 bottom-centre, 1 bottom-left, 8
    # top-centre); `box` draws an opaque box behind the text (BorderStyle
    # 3) instead of an outline.
    "preset:bold_center": {"font": "Arial", "scale": 0.045, "margin": 0.2, "bold": -1,
                           "align": 2, "box": False, "side": 0.08},
    # a lower third: smaller, left-aligned, on a dark box -- a name or a
    # place, not the dialogue
    "preset:lower_third": {"font": "Arial", "scale": 0.032, "margin": 0.12, "bold": -1,
                           "align": 1, "box": True, "side": 0.06},
    # quiet text at the top, thin outline, no bold -- keeps the bottom of
    # the frame (and the platform's own UI there) clear
    "preset:minimal_top": {"font": "Arial", "scale": 0.03, "margin": 0.08, "bold": 0,
                           "align": 8, "box": False, "side": 0.08},
}


class RenderError(RuntimeError):
    pass


# Threads cost memory (every decoder and encoder thread holds frames of
# its own) and buy nothing on the 1-shared-CPU Fly machine the render runs
# on. With the inputs split by stream, these caps took #375's v9 from
# 1.1 GB to 0.35 GB peak (measured 2026-09-30).
DECODE_THREADS = 2
ENCODE_THREADS = 2


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
        # BorderStyle 3 paints OutlineColour as a box; 1 is outline+shadow
        border, outline_colour = ((3, "&H99000000") if p["box"] else (1, "&H00000000"))
        outline = max(4, size // 5) if p["box"] else max(2, size // 14)
        styles.append(
            f"Style: {name},{p['font']},{size},&H00FFFFFF,&H00FFFFFF,{outline_colour},&H80000000,"
            f"{p['bold']},0,0,0,100,100,0,0,{border},{outline},{0 if p['box'] else 1},"
            f"{p['align']},{round(w * p['side'])},{round(w * p['side'])},"
            f"{round(h * p['margin'])},1")
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

def _segment(c: dict, src: str, seg: str, fps: int, w: int, h: int, norm: str,
             prereversed: bool = False) -> list[str]:
    """One picture clip's chain, ending in [seg] at the canvas size.

    A clip with no look takes the plain path: trim, fit, pad (`norm`). A
    clip with keyframes (lanes.py) or opacity is fitted WITHOUT the pad,
    given an alpha channel, zoomed and rotated per frame, and laid over a
    black canvas of its own length at its per-frame offset -- the letterbox
    is the canvas, so a zoom-out shows black around the picture, as the
    preview does. `t` in every expression is clip-relative (setpts zeroed
    it), which is what the keys' frames are. Crop applies to the source
    picture before any of it, so it is in the picture's own proportions."""
    length = d.clip_length(c)
    if prereversed:
        # pre-reversed by reverse_source: the file IS the span, backwards
        head = f"{src}setpts=PTS-STARTPTS"
    else:
        head = f"{src}trim=start={_s(c['src_in'], fps)}:end={_s(c['src_out'], fps)},setpts=PTS-STARTPTS"
        if c.get("reverse"):
            # in-graph fallback (compile_args without a pre-pass): holds
            # the whole span in memory, which render() never asks of it
            head += ",reverse"
    if length != d.span(c):
        # speed: stretch the span to the clip's length; `fps` (in norm /
        # fit) then drops or repeats frames at the project rate
        head += f",setpts=PTS*{length / d.span(c):.6f}"
    crop = c.get("crop")
    if crop:
        left, right = crop.get("left", 0), crop.get("right", 0)
        top, bottom = crop.get("top", 0), crop.get("bottom", 0)
        head += (f",crop=iw*{1 - left - right:.4f}:ih*{1 - top - bottom:.4f}"
                 f":iw*{left:.4f}:ih*{top:.4f}")
    exact = ""
    if d.is_retimed(c):
        # a retimed span lands within a frame of its length; hold the last
        # frame and cut, so the concat/xfade offsets stay exact
        exact = f",tpad=stop_mode=clone:stop=2,trim=end={_s(length, fps)}"
    if not lanes.has_look(c):
        return [f"{head},{norm}{exact}[{seg}]"]
    keys = {p: (lanes.lane(c, p) or {}).get("keys") or [] for p in lanes.PATHS}
    fit = (f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1,"
           "format=yuva420p")
    opacity = c.get("opacity")
    if opacity is not None and opacity < 1:
        fit += f",colorchannelmixer=aa={opacity:.4f}"
    if lanes.animated(c, "zoom"):
        z = lanes.expr(keys["zoom"], fps, 1.0)
        fit += (f",scale=w='max(2,trunc(iw*({z})/2)*2)':h='max(2,trunc(ih*({z})/2)*2)'"
                ":eval=frame")
    if lanes.animated(c, "rotation"):
        r = lanes.expr(keys["rotation"], fps, 0.0)
        fit += f",rotate=a='({r})*PI/180':c=none:ow='hypot(iw,ih)':oh='hypot(iw,ih)'"
    x = lanes.expr(keys["x"], fps, 0.0)
    y = lanes.expr(keys["y"], fps, 0.0)
    return [
        f"color=c=black:s={w}x{h}:r={fps}:d={_s(length, fps)},format=yuv420p[{seg}bg]",
        f"{head},{fit}[{seg}fg]",
        f"[{seg}bg][{seg}fg]overlay=x='(W-w)/2+({x})*W':y='(H-h)/2+({y})*H':eval=frame:"
        f"eof_action=pass,setsar=1,format=yuv420p,settb=AVTB[{seg}]",
    ]


def _video_graph(doc: dict, index: dict[str, int], parts: list[str],
                 burn: Optional[str], rev_index: Optional[dict[str, int]] = None,
                 stills=()) -> str:
    rev_index = rev_index or {}
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
        if c.get("reverse") and c.get("media") in stills:
            c = {k: val for k, val in c.items() if k != "reverse"}   # a still is its own reverse
        rev = rev_index.get(c.get("id")) if c.get("reverse") else None
        src = f"[{rev}:v]" if rev is not None else f"[{index[c['media']]}:v]"
        parts.extend(_segment(c, src, seg, fps, w, h, norm, prereversed=rev is not None))
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


def _atempo(factor: float) -> list[str]:
    out = []
    while factor > 2.0:
        out.append("atempo=2.0")
        factor /= 2.0
    while factor < 0.5:
        out.append("atempo=0.5")
        factor /= 0.5
    out.append(f"atempo={factor:.6f}")
    return out


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
            if c.get("reverse"):
                chain.append("areverse")
            if d.clip_length(c) != d.span(c):
                # pitch-kept tempo; atempo takes 0.5-2 per instance
                chain += _atempo(d.span(c) / d.clip_length(c))
                cl = _s(d.clip_length(c), fps)
                chain += [f"apad=whole_dur={cl}", f"atrim=end={cl}"]
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


def stills_in(media: Optional[dict], paths: dict[str, Path]) -> set[str]:
    """The handles that are still images: flagged by the probe, or named
    by an image extension when no probe was passed."""
    out = {h for h, info in (media or {}).items() if info and info.get("still")}
    return out | {h for h, p in paths.items() if Path(p).suffix.lower() in sources.IMAGE_EXTS}


def compile_args(doc: dict, paths: dict[str, Path], out: Path, *,
                 burn: Optional[str] = None, ffmpeg: str = "ffmpeg",
                 stills=()) -> list[str]:
    """The whole ffmpeg argv for one doc. Pure. `burn` is the .ass file
    name to burn in (relative to the cwd ffmpeg runs in), or None.

    A handle in `stills` is an image: it is read with `-loop 1` at the
    project fps, bounded by `-t` to the furthest frame any clip asks of
    it, so the same trim/setpts chain that cuts a video cuts a held
    still -- and an image never becomes an endless input."""
    handles = d.handles(doc)
    missing = [h for h in handles if h not in paths]
    if missing:
        raise RenderError(f"no file for {', '.join(missing)}")
    # A file is opened ONCE FOR ITS PICTURE AND ONCE FOR ITS SOUND, never
    # once for both. The sound of every clip is mixed from the first frame
    # of the cut (amix, with adelay placing each clip), so ffmpeg reads
    # every file's audio at once -- and reading a file's audio demuxes its
    # video too, whose decoded frames then queue until the picture reaches
    # that clip. On #375's v9 (T25, 2026-09-30) that queue was the whole
    # render's memory: 1.1 GB, and the kernel killed ffmpeg on Fly's 1 GB
    # machine. `-an` / `-vn` on the inputs keep each read to its own stream.
    fps = doc["fps"]
    on_video = {c.get("media") for t in d.tracks_of(doc, "video") for c in t.get("clips") or []}
    on_audio = {c.get("media") for t in d.tracks_of(doc, "audio") for c in t.get("clips") or []}
    argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    vindex: dict[str, int] = {}
    aindex: dict[str, int] = {}
    n = 0
    for h in handles:
        if h in on_video:
            if h in stills:
                need = max([c["src_out"] for _, c in d.all_clips(doc) if c.get("media") == h] or [1])
                argv += ["-loop", "1", "-framerate", str(fps), "-t", _s(need, fps)]
            argv += ["-threads", str(DECODE_THREADS), "-an", "-i", str(paths[h])]
            vindex[h] = n
            n += 1
        if h in on_audio:
            argv += ["-threads", str(DECODE_THREADS), "-vn", "-i", str(paths[h])]
            aindex[h] = n
            n += 1
    # a reversed picture clip reads a PRE-REVERSED file when render() made
    # one (paths["rev:<clip id>"], reverse_source): the `reverse` filter
    # holds the whole span in memory, which a 1 GB machine cannot spare
    rev_index: dict[str, int] = {}
    for t in d.tracks_of(doc, "video"):
        for c in t.get("clips") or []:
            key = f"rev:{c.get('id')}"
            if c.get("reverse") and key in paths:
                argv += ["-threads", str(DECODE_THREADS), "-an", "-i", str(paths[key])]
                rev_index[c["id"]] = n
                n += 1
    parts: list[str] = []
    vout = _video_graph(doc, vindex, parts, burn, rev_index, stills)
    aout = _audio_graph(doc, aindex, parts)
    argv += ["-filter_complex_threads", "1", "-filter_complex", ";".join(parts),
             "-map", f"[{vout}]", "-map", f"[{aout}]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-threads", str(ENCODE_THREADS),
             "-r", str(doc["fps"]),
             "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE),
             "-movflags", "+faststart", "-t", _s(doc["duration"], doc["fps"]), str(out)]
    return argv


# --------------------------------------------------------------------------
# running it
# --------------------------------------------------------------------------

REVERSE_CHUNK_SECONDS = 1.0


def reverse_source(exe: str, src: Path, start: int, end: int, fps: int, work: Path,
                   name: str) -> Path:
    """Source frames [start, end) of `src`, backwards, as one file -- made
    one second at a time (each chunk reversed alone, the chunks joined
    last-first) so no more than a second of decoded picture is ever held.
    The `reverse` filter on a whole 10 s 1080p span is ~1.8 GB of frames."""
    chunk = max(1, round(REVERSE_CHUNK_SECONDS * fps))
    pieces: list[Path] = []
    a = start
    while a < end:
        b = min(end, a + chunk)
        out = work / f"{name}_{len(pieces):04d}.mp4"
        argv = [exe, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", _s(a, fps), "-threads", str(DECODE_THREADS), "-an", "-i", str(src),
                "-vf", f"fps={fps},trim=end_frame={b - a},setpts=PTS-STARTPTS,reverse",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p",
                "-threads", str(ENCODE_THREADS), str(out)]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
        if proc.returncode != 0 or not out.is_file():
            tail = (proc.stderr or "").strip().splitlines()[-2:]
            raise RenderError("reversing a clip failed: " + (" | ".join(tail) or f"exit {proc.returncode}"))
        pieces.append(out)
        a = b
    listing = work / f"{name}.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in reversed(pieces)), encoding="utf-8")
    final = work / f"{name}.mp4"
    proc = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                           "-safe", "0", "-i", str(listing), "-c", "copy", str(final)],
                          cwd=work, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    if proc.returncode != 0 or not final.is_file():
        raise RenderError("joining a reversed clip failed")
    return final


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
        paths = dict(paths)
        for t in d.tracks_of(doc, "video"):
            for c in t.get("clips") or []:
                if c.get("reverse") and c["media"] in paths and c["media"] not in stills_in(media, paths):
                    paths[f"rev:{c['id']}"] = reverse_source(
                        exe, Path(paths[c["media"]]), c["src_in"], c["src_out"], doc["fps"],
                        work, f"rev_{c['id']}")
        tmp_out = work / "out.mp4"
        argv = compile_args(doc, paths, tmp_out, burn=burn, ffmpeg=exe,
                            stills=stills_in(media, paths))
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
