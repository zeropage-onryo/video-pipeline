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
import { fileName, sourcesFor } from "@/lib/refs";
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

export type Gate = { level: "pass" | "warn" | "fail"; short: "READY" | "CHECK" | "BLOCKED"; long: string };

/** READY / CHECK / BLOCKED.

    NOT the prompt gate's verdict: prompt_scores (score, passed, reason) is
    not on this payload -- only the MCP `idea` tool joins it -- so the dot is
    derived from what the card does carry. BLOCKED is the reference gate's
    own fact (no refs, preprod.reference_gate). CHECK is anything a person
    should read first: validate_concept's warnings, or the advisory verdict
    the night wrote into park_reason ("advisory: prompt gate 4/10 — ...").
    READY is the absence of both, and says only that. */
export function gateOf(c: Concept): Gate {
  if (!(c.refs || []).length) return { level: "fail", short: "BLOCKED", long: "Blocked · no reference images" };
  const warnings = c.warnings || [];
  const advisory = /^advisory/i.test(c.park_reason || "");
  if (warnings.length || advisory) {
    const why = advisory ? c.park_reason : `${warnings.length} warning${warnings.length === 1 ? "" : "s"} on file`;
    return { level: "warn", short: "CHECK", long: `Check · ${why}` };
  }
  return { level: "pass", short: "READY", long: "Ready · references attached, no warnings on file" };
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

/* ── pictures ── */

/** An <img> that walks refs.sourcesFor (local route, then the stored URL)
 *  and becomes a labelled slate when every source failed. */
export function RefImg({
  url,
  thumb = false,
  eager = false,
  alt = "",
  className = "",
  deadLabel = "IMAGE UNAVAILABLE",
  deadClassName = "",
}: {
  url: string;
  thumb?: boolean;
  eager?: boolean;
  alt?: string;
  className?: string;
  deadLabel?: string;
  deadClassName?: string;
}) {
  const sources = useMemo(() => sourcesFor(url, { thumb, base: API_URL }), [url, thumb]);
  const [failed, setFailed] = useState<{ url: string; n: number }>({ url, n: 0 });
  const n = failed.url === url ? failed.n : 0;
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
      src={sources[n]}
      alt={alt}
      loading={eager ? "eager" : "lazy"}
      decoding="async"
      className={className}
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

/** The 16:9 top of a card: a real button, the picture, and whatever tags
 *  the page lays over it. */
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
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={(e) => onOpen(e.currentTarget)}
      className="group relative block aspect-video w-full overflow-hidden rounded-t-[9px] bg-noir-slate p-0 focus-visible:rounded-t-[9px]! disabled:cursor-default"
    >
      {hero.kind === "none" ? (
        <NoReferenceSlate />
      ) : (
        <RefImg
          url={hero.url}
          thumb={hero.kind === "ref"}
          className="block size-full object-cover group-enabled:group-hover:brightness-110"
          deadLabel={hero.kind === "keyframe" ? "KEYFRAME UNAVAILABLE" : "REFERENCE UNAVAILABLE"}
          deadClassName="absolute inset-0 text-[11px] tracking-[0.16em]"
        />
      )}
      {hero.kind === "ref" ? <span className={`${TAG} ${TAG_DARK} bottom-10 left-3 text-bone2!`}>REF 1 · NO KEYFRAME YET</span> : null}
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
          <RefImg url={url} thumb className="block size-full object-cover" deadLabel="N/A" />
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
