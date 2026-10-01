"use client";

/* The Source viewer (2026-10-01): Resolve's left-hand viewer, the first gap
   the invideo captures named (docs/reference-look/invideo-editor). A clip
   from the bin is looked at, marked and cut BEFORE it touches the
   timeline -- the timeline was the only place to trim until now.

   - Double-click a bin tile to load it here. It has its own clock, its
     own transport, and its own In/Out marks (I / O), kept per clip for
     the session.
   - Insert (F9 or ,), Overwrite (F10 or .) and Append (Shift+F12) put the
     marked range on the timeline at the timeline's playhead -- one op each,
     through the same placeMedia the bin's drop uses.
   - Transcript: the index's words. Click a word to go to it; drag across
     words to mark In/Out on them. Metadata: what the file is.

   Picture comes from T6's proxy like the program viewer's; it is a
   preview, not the export. Times are frames at the PROJECT fps, so a
   marked range is already the src_in / src_out an op takes. */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRightToLine,
  Brackets,
  ChevronFirst,
  ChevronLast,
  Pause,
  Play,
  Replace,
  StepBack,
  StepForward,
} from "lucide-react";
import { useCut } from "@/lib/cut/store";
import { editFromSource, sourceToMark } from "@/lib/cut/actions";
import { getTranscript, type Transcript } from "@/lib/cut/api";
import { timecode } from "@/lib/cut/timeline";

type Tab = "source" | "transcript" | "metadata";

export function SourceViewer() {
  const handle = useCut((s) => s.source.handle);
  const active = useCut((s) => s.activeViewer === "source");
  const item = useCut((s) => s.bin.find((b) => b.handle === s.source.handle));
  const [tab, setTab] = useState<Tab>("source");

  return (
    <div
      className="cx-viewer cx-source"
      data-active={active ? "1" : undefined}
      onPointerDown={() => useCut.getState().setActiveViewer("source")}
    >
      <div className="cx-viewer-head">
        <span className="cx-seg" role="tablist">
          {(["source", "transcript", "metadata"] as Tab[]).map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t === "source" ? "Source" : t === "transcript" ? "Transcript" : "Metadata"}
            </button>
          ))}
        </span>
        <span
          className="cx-label"
          style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "right" }}
          title={item?.name}
        >
          {item?.name ?? ""}
        </span>
      </div>
      {!handle ? (
        <div className="cx-stage">
          <p className="cx-note" style={{ textAlign: "center", maxWidth: 240 }}>
            Double-click a clip in the bin to look at it here, mark In and Out, then Insert or Overwrite it onto the
            timeline.
          </p>
        </div>
      ) : tab === "source" ? (
        <SourcePlayer />
      ) : tab === "transcript" ? (
        <TranscriptTab handle={handle} />
      ) : (
        <MetadataTab />
      )}
      {handle ? <SourceTransport /> : null}
    </div>
  );
}

/* ── the picture and its clock ── */
function SourcePlayer() {
  const handle = useCut((s) => s.source.handle)!;
  const playhead = useCut((s) => s.source.playhead);
  const playing = useCut((s) => s.source.playing);
  const rate = useCut((s) => s.source.rate);
  const fps = useCut((s) => s.doc?.fps ?? 30);
  const item = useCut((s) => s.bin.find((b) => b.handle === handle));
  const preview = useCut((s) => s.previews[handle]);
  const ensurePreview = useCut((s) => s.ensurePreview);
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => ensurePreview(handle), [handle, ensurePreview]);

  // Forward play is the element's own (smooth, with sound); the store's
  // playhead follows it. Reverse (J) has no native mode, so it steps by
  // seeking, as the program viewer's clock does.
  useEffect(() => {
    const el = ref.current;
    if (!playing) {
      el?.pause();
      return;
    }
    let raf = 0;
    if (rate > 0 && el) {
      el.playbackRate = rate;
      el.play().catch(() => undefined);
      const tick = () => {
        const s = useCut.getState();
        s.sourceSeek(el.currentTime * fps);
        if (el.ended) s.setSourcePlaying(false);
        else raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    } else {
      el?.pause();
      let last = performance.now();
      const tick = (now: number) => {
        const s = useCut.getState();
        const next = s.source.playhead + ((now - last) / 1000) * fps * s.source.rate;
        last = now;
        s.sourceSeek(next);
        if (next <= 0) s.setSourcePlaying(false);
        else raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }
    return () => cancelAnimationFrame(raf);
  }, [playing, rate, fps]);

  // paused (or reversing): the element follows the playhead
  useEffect(() => {
    const el = ref.current;
    if (!el || (playing && rate > 0)) return;
    const want = playhead / fps;
    if (Math.abs(el.currentTime - want) > 0.5 / fps) {
      try {
        el.currentTime = want;
      } catch {
        /* not seekable yet */
      }
    }
  }, [playhead, playing, rate, fps]);

  if (item?.kind === "image") {
    const src = item.url ?? item.poster;
    return (
      <div className="cx-stage">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {src ? <img className="cx-source-media" src={src} alt="" /> : null}
      </div>
    );
  }
  const src = item?.kind === "audio" ? item.url : (preview?.proxy ?? item?.url ?? null);
  return (
    <div className="cx-stage">
      {item?.kind === "audio" ? (
        <div className="cx-source-audio">
          <span className="cx-label">sound</span>
        </div>
      ) : null}
      {src ? (
        <video
          ref={ref}
          className="cx-source-media"
          src={src}
          playsInline
          preload="auto"
          style={item?.kind === "audio" ? { display: "none" } : undefined}
          onLoadedMetadata={(e) => {
            const s = useCut.getState();
            const d = e.currentTarget.duration;
            if (Number.isFinite(d) && d > 0) s.setSourceFrames(Math.floor(d * fps + 1e-6));
            e.currentTarget.currentTime = Math.max(0.001, s.source.playhead / fps);
          }}
        />
      ) : (
        <p className="cx-note">No playable file for this clip yet.</p>
      )}
    </div>
  );
}

/* ── the scrubber with its marks, then the buttons ── */
function SourceTransport() {
  const playhead = useCut((s) => s.source.playhead);
  const playing = useCut((s) => s.source.playing);
  const frames = useCut((s) => s.source.frames);
  const fps = useCut((s) => s.doc?.fps ?? 30);
  const marks = useCut((s) => (s.source.handle ? s.marks[s.source.handle] : undefined));
  const bar = useRef<HTMLDivElement>(null);
  const total = Math.max(1, frames ?? 1);
  const pct = (f: number) => `${Math.min(100, Math.max(0, (f / total) * 100))}%`;
  const inF = marks?.in;
  const outF = marks?.out;
  const span = (outF ?? total) - (inF ?? 0);

  const seekAt = (clientX: number) => {
    const r = bar.current?.getBoundingClientRect();
    if (!r) return;
    const s = useCut.getState();
    s.setSourcePlaying(false);
    s.sourceSeek(((clientX - r.left) / r.width) * total);
  };

  const toggle = () => {
    const s = useCut.getState();
    if (s.source.playing) return s.setSourcePlaying(false);
    if (frames !== null && s.source.playhead >= frames - 1) s.sourceSeek(inF ?? 0);
    s.setSourceRate(1);
    s.setSourcePlaying(true);
  };
  const step = (n: number) => {
    const s = useCut.getState();
    s.setSourcePlaying(false);
    s.sourceSeek(s.source.playhead + n);
  };

  return (
    <div className="cx-source-foot">
      <div
        className="cx-scrub"
        ref={bar}
        onPointerDown={(e) => {
          seekAt(e.clientX);
          const move = (ev: PointerEvent) => seekAt(ev.clientX);
          const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
          };
          window.addEventListener("pointermove", move);
          window.addEventListener("pointerup", up);
        }}
      >
        {inF !== undefined || outF !== undefined ? (
          <i className="cx-scrub-range" style={{ left: pct(inF ?? 0), right: `calc(100% - ${pct(outF ?? total)})` }} />
        ) : null}
        {inF !== undefined ? <i className="cx-scrub-mark in" style={{ left: pct(inF) }} /> : null}
        {outF !== undefined ? <i className="cx-scrub-mark out" style={{ left: pct(outF) }} /> : null}
        <i className="cx-scrub-head" style={{ left: pct(playhead) }} />
      </div>
      <div className="cx-source-clock">
        <span className="cx-tc">{timecode(playhead, fps)}</span>
        <span className="cx-label" title="In · Out · marked length">
          {inF !== undefined ? timecode(inF, fps) : "--:--:--"} → {outF !== undefined ? timecode(outF, fps) : "--:--:--"} ·{" "}
          {timecode(Math.max(0, span), fps)}
        </span>
      </div>
      <div className="cx-transport cx-source-transport">
        <button type="button" className="cx-btn" title="Mark In (I)" onClick={() => useCut.getState().markIn()}>
          <span className="cx-mark-glyph">[</span>
        </button>
        <button type="button" className="cx-btn" title="Mark Out (O)" onClick={() => useCut.getState().markOut()}>
          <span className="cx-mark-glyph">]</span>
        </button>
        <button type="button" className="cx-btn" title="Clear marks (Alt+X)" onClick={() => useCut.getState().clearMarks()}>
          <Brackets />
        </button>
        <span className="cx-sep" style={{ margin: "0 4px" }} />
        <button type="button" className="cx-btn" title="Go to In (Shift+I)" onClick={() => sourceToMark("in")}>
          <ChevronFirst />
        </button>
        <button type="button" className="cx-btn" title="Back one frame (←)" onClick={() => step(-1)}>
          <StepBack />
        </button>
        <button type="button" className="cx-btn cx-play" title="Play / pause (Space)" onClick={toggle}>
          {playing ? <Pause /> : <Play />}
        </button>
        <button type="button" className="cx-btn" title="Forward one frame (→)" onClick={() => step(1)}>
          <StepForward />
        </button>
        <button type="button" className="cx-btn" title="Go to Out (Shift+O)" onClick={() => sourceToMark("out")}>
          <ChevronLast />
        </button>
        <span className="cx-sep" style={{ margin: "0 4px" }} />
        <button type="button" className="cx-btn cx-edit" title="Insert at the playhead (F9 or ,)" onClick={() => void editFromSource("insert")}>
          <ArrowDownToLine /> <span className="cx-edit-l">Insert</span>
        </button>
        <button type="button" className="cx-btn cx-edit" title="Overwrite at the playhead (F10 or .)" onClick={() => void editFromSource("overwrite")}>
          <Replace /> <span className="cx-edit-l">Overwrite</span>
        </button>
        <button type="button" className="cx-btn cx-edit" title="Append to the end (Shift+F12)" onClick={() => void editFromSource("append")}>
          <ArrowRightToLine /> <span className="cx-edit-l">Append</span>
        </button>
      </div>
    </div>
  );
}

/* ── Transcript: click a word to go there; drag across words to mark ── */
function TranscriptTab({ handle }: { handle: string }) {
  const fps = useCut((s) => s.doc?.fps ?? 30);
  const playhead = useCut((s) => s.source.playhead);
  const marks = useCut((s) => s.marks[handle]);
  const [data, setData] = useState<{ handle: string; t: Transcript | null; err: string | null } | null>(null);
  // a ref, not state: the release must see the press that started the
  // drag even when both land before React has rendered between them
  const drag = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    getTranscript(handle)
      .then((t) => alive && setData({ handle, t, err: null }))
      .catch((e) => alive && setData({ handle, t: null, err: e instanceof Error ? e.message : "could not read it" }));
    return () => {
      alive = false;
    };
  }, [handle]);

  const words = useMemo(
    () =>
      (data?.handle === handle ? (data.t?.words ?? []) : []).map((w) => ({
        ...w,
        a: Math.floor(w.start * fps),
        b: Math.max(Math.floor(w.start * fps) + 1, Math.ceil(w.end * fps)),
      })),
    [data, handle, fps],
  );

  if (!data || data.handle !== handle) return <div className="cx-pane-body"><p className="cx-note">Reading the transcript…</p></div>;
  if (data.err) return <div className="cx-pane-body"><p className="cx-note">{data.err}</p></div>;
  if (data.t?.status !== "indexed") {
    return (
      <div className="cx-pane-body">
        <p className="cx-note">
          This clip has not been indexed yet, so there are no words to show. Once it is on the timeline, the Agent tab
          can index it (about a cent a clip) — then its words appear here.
        </p>
      </div>
    );
  }
  if (!words.length) {
    return (
      <div className="cx-pane-body">
        <p className="cx-note">{data.t.speech === false ? "Nobody speaks in this clip." : "No words were heard in this clip."}</p>
      </div>
    );
  }
  const inRange = (a: number, b: number) =>
    marks?.in !== undefined && marks?.out !== undefined && a >= marks.in && b <= marks.out;
  const finish = (i: number) => {
    if (drag.current === null) return;
    const lo = Math.min(drag.current, i);
    const hi = Math.max(drag.current, i);
    const s = useCut.getState();
    if (lo !== hi) {
      s.markIn(words[lo].a);
      s.markOut(words[hi].b - 1);
    }
    drag.current = null;
  };
  return (
    <div className="cx-pane-body cx-transcript" onPointerLeave={() => (drag.current = null)}>
      <p>
        {words.map((w, i) => (
          <span
            key={`${w.a}-${i}`}
            className="cx-word"
            data-now={playhead >= w.a && playhead < w.b ? "1" : undefined}
            data-marked={inRange(w.a, w.b) ? "1" : undefined}
            title={timecode(w.a, fps)}
            onPointerDown={(e) => {
              e.preventDefault();
              drag.current = i;
              const s = useCut.getState();
              s.setSourcePlaying(false);
              s.sourceSeek(w.a);
            }}
            onPointerUp={() => finish(i)}
          >
            {w.text}{" "}
          </span>
        ))}
      </p>
      <p className="cx-note" style={{ marginTop: 10 }}>
        Click a word to go to it. Drag across words to mark them In and Out.
      </p>
    </div>
  );
}

function MetadataTab() {
  const item = useCut((s) => s.bin.find((b) => b.handle === s.source.handle));
  const frames = useCut((s) => s.source.frames);
  const fps = useCut((s) => s.doc?.fps ?? 30);
  if (!item) return null;
  const mb = item.size_bytes ? `${(item.size_bytes / 1048576).toFixed(1)} MB` : "—";
  return (
    <div className="cx-pane-body">
      <dl className="cx-kv">
        <dt>Name</dt>
        <dd>{item.name}</dd>
        <dt>Handle</dt>
        <dd>{item.handle}</dd>
        <dt>Kind</dt>
        <dd>{item.kind}</dd>
        <dt>From</dt>
        <dd>{item.source === "render" ? "a render" : "an upload"}</dd>
        <dt>Length</dt>
        <dd>{frames !== null ? timecode(frames, fps) : item.seconds ? `${item.seconds.toFixed(2)} s` : "not measured yet"}</dd>
        {item.width && item.height ? (
          <>
            <dt>Size</dt>
            <dd>
              {item.width}×{item.height}
            </dd>
          </>
        ) : null}
        <dt>Picture</dt>
        <dd>{item.has_video ? "yes" : "no"}</dd>
        <dt>Sound</dt>
        <dd>{item.has_audio === null ? "not measured yet" : item.has_audio ? "yes" : "no"}</dd>
        <dt>File</dt>
        <dd>{mb}</dd>
      </dl>
    </div>
  );
}
