"use client";

/* What the Pipeline card and the Queue card share (2026-09-17; the React
   port of app/static/zpf/cards.js): the image-first top, the tags laid
   over it, the reference thumbnails and the readiness dot. One row in the
   database is one card in the product, so the two pages must not grow two
   ideas of what its picture is.

   Everything here is DISPLAY over the payload app/api.py's _concept_card
   already sends. Nothing below decides anything: the reference gate, the
   spend gate and the pick are the server's.

   A NOTE ON `!`: studio.css carries `.zps button { font: inherit; color:
   inherit }` UNLAYERED, and unlayered CSS beats every Tailwind utility
   (they live in @layer utilities) whatever the specificity. So a button's
   face, SIZE and colour are written `font-plex! text-xs! text-bone!` here
   (`font` is a shorthand: it resets font-size and line-height too). Moving that
   reset into a layer would fix it at the root and restyle every other
   button in the studio; that is a separate change. */
/* eslint-disable @next/next/no-img-element */
import { useMemo, useState, type ReactNode } from "react";
import { API_URL } from "@/lib/api";
import { fileName, sourced, sourcesFor } from "@/lib/refs";
import type { Concept, TimelinePart } from "@/lib/studio-api";

export const brandName = (b?: string | null) => String(b || "").replace(/zeropage/i, "ZERO PAGE").toUpperCase();
export const partsOf = (c: Concept): TimelinePart[] => c.timeline?.parts || [];
export const windowLabel = (p: TimelinePart) => `${p.start}–${p.end}s`;

/** "3 SHOTS · 12S". A scene with no windows is one shot, and its length is
 *  not on the card payload, so none is claimed. */
export function shotsLabel(c: Concept): string {
  const parts = partsOf(c);
  if (!parts.length) return "1 SHOT";
  const total = c.timeline?.seconds ?? parts[parts.length - 1].end;
  return `${parts.length} SHOT${parts.length === 1 ? "" : "S"} · ${total}S`;
}

export type Gate = { level: "pass" | "warn" | "fail"; short: "READY" | "CHECK" | "BLOCKED"; long: string; score?: number };

/** READY / CHECK / BLOCKED.

    BLOCKED is the reference gate's own fact (no refs,
    preprod.reference_gate) and outranks everything: nothing renders without
    photographs, whatever a judge thought of the writing.

    Then THE PROMPT GATE'S VERDICT, when the concept has one. `c.gate` is
    autonomy.gates_for_concepts on the card payload since 2026-09-17, the
    same reading the MCP `idea` tool makes. A pass with no warnings is READY;
    a fail is CHECK, never BLOCKED -- the gates are advisory (2026-09-07),
    the run parked anyway, and a judge that agreed with the grade 38% of the
    time gets to raise a flag, not close a door.

    `c.gate` null means NO GRAPH RUN EVER SCORED THIS (a Studio Create stops
    on the board unscored). That is said as such, and the dot falls back to
    validate_concept's warnings. It must not read as a pass.
    (app/static/zpf/cards.js is the twin.) */
export function gateOf(c: Concept): Gate {
  if (!(c.refs || []).length) return { level: "fail", short: "BLOCKED", long: "Blocked · no reference images" };
  const warnings = c.warnings || [];
  const flagged = warnings.length ? ` · ${warnings.length} warning${warnings.length === 1 ? "" : "s"} on file` : "";
  const g = c.gate;
  if (g && g.score !== null && g.score !== undefined) {
    const reworked = g.reworks ? ` · after ${g.reworks} rework${g.reworks === 1 ? "" : "s"}` : "";
    if (g.passed && !warnings.length) {
      return { level: "pass", short: "READY", score: g.score, long: `Prompt gate ${g.score}/10 · passed${reworked}` };
    }
    return {
      level: "warn",
      short: "CHECK",
      score: g.score,
      long: g.passed
        ? `Prompt gate ${g.score}/10 · passed${reworked}${flagged}`
        : `Prompt gate ${g.score}/10 · ${g.reason || "did not pass"}${reworked}${flagged}`,
    };
  }
  // a run that ended before the gate scored anything says why it ended
  const unscored = g
    ? `Not scored · ${g.outcome || "the run ended before the prompt gate"}`
    : "Never scored · written by Create, which stops on the board";
  if (warnings.length) return { level: "warn", short: "CHECK", long: `${unscored}${flagged}` };
  return { level: "pass", short: "READY", long: `${unscored} · references attached` };
}

export const GATE_DOT: Record<Gate["level"], string> = { pass: "bg-gate-pass", warn: "bg-gate-warn", fail: "bg-noir-red" };

/** The card's picture: the keyframe if one was drawn, else the first
 *  reference, else the red slate. */
export function heroOf(c: Concept): { kind: "keyframe" | "ref" | "none"; url: string } {
  if (c.reference_image) return { kind: "keyframe", url: c.reference_image };
  if ((c.refs || []).length) return { kind: "ref", url: c.refs[0] };
  return { kind: "none", url: "" };
}

/** the stills: the scene's keyframe, then each timed shot's own. Shot 1's
 *  still IS the scene's keyframe, so it is not listed twice. */
export function stillsOf(c: Concept): string[] {
  const urls: string[] = [];
  if (c.reference_image) urls.push(c.reference_image);
  for (const p of partsOf(c)) if (p.reference_image && !urls.includes(p.reference_image)) urls.push(p.reference_image);
  return urls;
}

/** The preview's items for a concept's references. `ref_sources` is
 *  parallel to `refs`; an older payload without it still previews,
 *  captioned by what the URL proves. */
export function refItems(c: Concept) {
  const refs = c.refs || [];
  return c.ref_sources && c.ref_sources.length === refs.length ? c.ref_sources.map(sourced) : refs.map((url) => ({ url }));
}

/** The server's thumbnail for reference i (`ref_thumbs`, parallel to
 *  `refs` -- BACKLOG #0), or "" on an older payload without one, in which
 *  case the image falls back to its own chain. `refs` itself is never read
 *  for a size: refs[0] is the frame the render anchors on. */
export function thumbOf(c: Concept, i: number): string {
  const thumbs = c.ref_thumbs || [];
  return thumbs.length === (c.refs || []).length ? thumbs[i] || "" : "";
}

/* ── pictures ── */

/** An <img> that walks refs.sourcesFor (the server's thumbnail when the
 *  card carries one, the local route, then the stored URL) and becomes a
 *  labelled slate when every source failed. */
export function RefImg({
  url,
  thumb = false,
  small = "",
  eager = false,
  alt = "",
  className = "",
  deadLabel = "IMAGE UNAVAILABLE",
  deadClassName = "",
}: {
  url: string;
  thumb?: boolean;
  small?: string;
  eager?: boolean;
  alt?: string;
  className?: string;
  deadLabel?: string;
  deadClassName?: string;
}) {
  const sources = useMemo(() => sourcesFor(url, { thumb, base: API_URL, small }), [url, thumb, small]);
  const [failed, setFailed] = useState<{ url: string; n: number }>({ url, n: 0 });
  const n = failed.url === url ? failed.n : 0;
  /* Arrived yet? A board tile can wait seconds on a multi-megabyte original
     (2026-09-18: a 3024px photo decoding into a 52px tile), and an empty
     dark box for that long reads as a broken card. Until the bytes land the
     <img> box itself pulses -- an <img> paints its background with nothing
     loaded. Keyed by source, like `failed`, so a retry pulses again. */
  const [arrived, setArrived] = useState<string | null>(null);
  const here = sources[n] ?? "";
  if (n >= sources.length) {
    return (
      <span
        role="img"
        aria-label={deadLabel || `unavailable: ${fileName(url)}`}
        className={`flex items-center justify-center overflow-hidden bg-[#1c1716] text-center font-plex text-[9px] leading-tight tracking-[0.08em] text-noir-red2 [overflow-wrap:anywhere] ${deadClassName || "size-full"}`}
      >
        {deadLabel}
      </span>
    );
  }
  return (
    <img
      src={here}
      alt={alt}
      loading={eager ? "eager" : "lazy"}
      decoding="async"
      className={`${className} ${arrived === here ? "" : "bg-noir-raise motion-safe:animate-pulse"}`}
      /* a cached image can finish before React attaches onLoad */
      ref={(el) => {
        if (el?.complete && el.naturalWidth > 0 && arrived !== here) setArrived(here);
      }}
      onLoad={() => setArrived(here)}
      onError={() => setFailed({ url, n: n + 1 })}
    />
  );
}

export const TAG =
  "absolute flex max-w-[calc(100%-24px)] items-center gap-1.5 truncate rounded-[4px] px-2 py-1 font-plex text-[11px] leading-[1.3] tracking-[0.08em]";
export const TAG_DARK = "bg-[rgb(11_11_11/0.78)] text-bone";

export function NoReferenceSlate() {
  return (
    <span className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-[#1c1716] font-plex text-[11px] tracking-[0.16em] text-noir-red2">
      <span>NO REFERENCE</span>
      <small className="text-[11px] tracking-normal text-bone/55">cannot render yet</small>
    </span>
  );
}

/* The references as the card's picture, when nothing has been drawn yet.
   The asset sort puts the character first (it is what Runway anchors on),
   so with ref 1 alone as the hero a board of Michael scenes is a wall of
   one headshot and no card can be told from its neighbour (2026-09-18:
   17 of 21). Ref 1 keeps the large cell -- it IS the anchor -- and up to
   three more stack beside it, which is what tells the scenes apart. */
function RefMosaic({ concept }: { concept: Concept }) {
  const refs = concept.refs || [];
  const rest = refs.slice(1, 4);
  const cell = "block size-full min-h-0 min-w-0 object-cover";
  return (
    <span className="absolute inset-0 grid grid-cols-[3fr_2fr] gap-px bg-noir-bg group-enabled:group-hover:brightness-110">
      <RefImg url={refs[0]} thumb small={thumbOf(concept, 0)} className={cell} deadLabel="REF 1 UNAVAILABLE" deadClassName="size-full text-[11px] tracking-[0.16em]" />
      <span className="grid min-h-0 min-w-0 gap-px" style={{ gridTemplateRows: `repeat(${rest.length}, minmax(0, 1fr))` }}>
        {rest.map((u, i) => (
          <RefImg key={`${u}-${i}`} url={u} thumb small={thumbOf(concept, i + 1)} className={cell} deadLabel="N/A" />
        ))}
      </span>
    </span>
  );
}

/** The 16:9 top of a card: a real button, the picture, and whatever tags
 *  the page lays over it. A rendered scene plays its clip while the pointer
 *  is on it (muted, never preloaded: the still stays the poster). */
export function Hero({
  concept,
  label,
  onOpen,
  disabled = false,
  children,
}: {
  concept: Concept;
  label: string;
  onOpen: (trigger: HTMLElement) => void;
  disabled?: boolean;
  children?: ReactNode;
}) {
  const hero = heroOf(concept);
  const refs = concept.refs || [];
  const mosaic = hero.kind === "ref" && refs.length > 1;
  const clip = concept.media_url ? (concept.media_url.startsWith("/") ? API_URL + concept.media_url : concept.media_url) : "";
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={(e) => onOpen(e.currentTarget)}
      onPointerEnter={(e) => {
        if (e.pointerType === "touch") return;
        e.currentTarget.querySelector("video")?.play().catch(() => {});
      }}
      onPointerLeave={(e) => {
        const v = e.currentTarget.querySelector("video");
        if (v) {
          v.pause();
          v.currentTime = 0;
        }
      }}
      className="group relative block aspect-video w-full overflow-hidden rounded-t-[9px] bg-noir-slate p-0 focus-visible:rounded-t-[9px]! disabled:cursor-default"
    >
      {hero.kind === "none" ? (
        <NoReferenceSlate />
      ) : mosaic ? (
        <RefMosaic concept={concept} />
      ) : (
        <RefImg
          url={hero.url}
          thumb={hero.kind === "ref"}
          small={hero.kind === "ref" ? thumbOf(concept, 0) : ""}
          className="block size-full object-cover group-enabled:group-hover:brightness-110"
          deadLabel={hero.kind === "keyframe" ? "KEYFRAME UNAVAILABLE" : "REFERENCE UNAVAILABLE"}
          deadClassName="absolute inset-0 text-[11px] tracking-[0.16em]"
        />
      )}
      {clip ? (
        <video
          src={clip}
          muted
          loop
          playsInline
          preload="none"
          aria-hidden
          /* shown only WHILE PLAYING, never merely on hover: a clip this
             machine cannot fetch (it lives on another host's volume) would
             otherwise black out the still it was meant to animate */
          onPlaying={(e) => {
            e.currentTarget.dataset.on = "1";
          }}
          onPause={(e) => {
            delete e.currentTarget.dataset.on;
          }}
          className="pointer-events-none absolute inset-0 size-full object-cover opacity-0 transition-opacity duration-300 data-[on]:opacity-100"
        />
      ) : null}
      {hero.kind === "ref" ? (
        <span className={`${TAG} ${TAG_DARK} bottom-10 left-3 text-bone2!`}>
          {mosaic ? `REFS 1–${Math.min(4, refs.length)}` : "REF 1"} · NO KEYFRAME YET
        </span>
      ) : null}
      {children}
    </button>
  );
}

/** Up to `max` thumbnails, then one "+N" tile that opens the preview at the
 *  first hidden one. Each is a real button carrying its index. */
export function RefThumbs({
  concept,
  max = 4,
  size = "md",
  onOpen,
}: {
  concept: Concept;
  max?: number;
  size?: "sm" | "md" | "lg";
  onOpen: (index: number, trigger: HTMLElement) => void;
}) {
  const refs = concept.refs || [];
  const box = size === "lg" ? "size-[82px] rounded-[6px]" : size === "sm" ? "h-11 w-9 rounded-[4px]" : "size-[52px] rounded-[6px]";
  const base = `relative flex-none overflow-hidden border border-noir-line bg-noir-slate p-0 hover:border-bone focus-visible:rounded-[6px]! ${box}`;
  return (
    <>
      {refs.slice(0, max).map((url, i) => (
        <button
          type="button"
          key={`${url}-${i}`}
          className={base}
          aria-label={`Preview reference ${i + 1} of ${refs.length}: ${fileName(url)}`}
          onClick={(e) => onOpen(i, e.currentTarget)}
        >
          <RefImg url={url} thumb small={thumbOf(concept, i)} className="block size-full object-cover" deadLabel="N/A" />
          {size === "sm" ? null : (
            <span className="pointer-events-none absolute bottom-[3px] left-1 font-plex text-[9px] leading-none text-bone [text-shadow:0_0_3px_#000,0_0_3px_#000]">
              {i + 1}
            </span>
          )}
        </button>
      ))}
      {refs.length > max ? (
        <button
          type="button"
          className={`${base} border-dashed border-noir-line3! bg-transparent! font-plex! text-xs! text-bone!`}
          aria-label={`Preview ${refs.length - max} more references`}
          onClick={(e) => onOpen(max, e.currentTarget)}
        >
          +{refs.length - max}
        </button>
      ) : null}
    </>
  );
}

/* the card shell and its text block, so the two pages agree on them */
export const CARD = "relative flex min-w-0 flex-col rounded-[10px] border bg-noir-panel font-tight text-sm leading-[1.4] text-bone";
export const ICON_BTN =
  "flex size-11 flex-none items-center justify-center rounded-[8px] border border-noir-line bg-transparent p-0 text-bone3! hover:enabled:border-bone hover:enabled:text-bone! disabled:opacity-40 focus-visible:rounded-[8px]!";

export function TitleBlock({ concept }: { concept: Concept }) {
  return (
    <div className="flex min-w-0 flex-[1_1_150px] flex-col gap-0.5">
      <h4 className="m-0 truncate font-bebas text-[26px] font-normal leading-none tracking-[0.03em] text-bone" title={concept.title}>
        {concept.title || "Untitled"}
      </h4>
      {/* the card line: ONE line, clamped; the full text is its title */}
      {concept.summary ? (
        <p className="m-0 truncate text-[14.5px] text-bone2" title={concept.summary}>
          {concept.summary}
        </p>
      ) : null}
    </div>
  );
}
