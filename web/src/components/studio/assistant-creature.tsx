"use client";

/* The floating creature and its thoughts (2026-10-09, the "Creature
   Companions" design canvas, Mike's calls). It replaced the pill: the
   creature floats at 320px in a corner of every studio page, says what it
   is thinking in thought bubbles above its head, and a click opens the dock
   (assistant-pill.tsx draws the dock and owns everything the assistant
   does; this file is only the body and the bubbles).

   - Click: open the dock, or lower it. A click waits DOUBLE_MS to see
     whether a second one follows (lib/creature.ts clickIntent).
   - Double-click: make it small (80px, no thoughts, still shows the amber
     light and the unread count). A click brings it back.
   - Drag: park it on either side, at any height; the dock then seats it at
     that end. Kept per browser.
   - Hover: it turns to listen and leans in. Press: it squishes.

   The thoughts are "amber leads" (the canvas's pick): the one thing waiting
   on the person sits nearest the head in amber; while it works, what it is
   doing; after a failed turn, a retry; else a line it wants to say. Above
   that, small idea thoughts from the latest answer, and "Ask me anything". */
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { AssistantAvatar, type AvatarState } from "@/components/studio/assistant-avatar";
import { DOUBLE_MS, clickIntent, snapPark, type Park } from "@/lib/creature";
import { coloursOf, decodeMascot, lookOf } from "@/lib/mascot";
import "@/components/studio/assistant-creature.css";

/** the creature's own colour, for the glow under it */
export function tintOf(avatar: string): string {
  const m = decodeMascot(avatar);
  return coloursOf(m.look).find((c) => c.id === m.colour)?.hex ?? lookOf(m.look).own.hex;
}

export function Creature({
  avatar,
  face,
  progress,
  unread,
  small,
  docked,
  label,
  title,
  park,
  onAct,
  onSmall,
  onDrop,
}: {
  avatar: string;
  face: AvatarState;
  /* 0..1 fills the floor ring while a job runs */
  progress?: number;
  unread: number;
  small: boolean;
  docked: boolean;
  label: string;
  title: string;
  park: Park;
  /* a click: open or lower the dock, or come back from small */
  onAct: () => void;
  /* a double-click: make it small (or bring it back) */
  onSmall: () => void;
  /* a drag let go */
  onDrop: (p: Park) => void;
}) {
  const [hover, setHover] = useState(false);
  const [dragging, setDragging] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastClick = useRef(0);
  const drag = useRef<{ x: number; y: number; id: number; moved: boolean } | null>(null);
  // when a drag let go: the click the browser sends right after it is the
  // drag's, not the person's (and only right after, never a later one)
  const dropped = useRef(0);
  const settle = useRef<DOMRect | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  // what a drag moves: the resting group, thoughts and all (never the dock)
  const group = () => (docked ? null : (btn.current?.closest<HTMLElement>(".zpa-rest") ?? null));
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  // after a drop: the group is drawn at its new park, then slid there from
  // where the pointer let go (a FLIP), rather than jumping
  const parkKey = `${park.side}:${park.y}:${park.small}`;
  useLayoutEffect(() => {
    const el = group();
    const from = settle.current;
    settle.current = null;
    if (!el) return;
    el.style.translate = "";
    if (!from) return;
    const to = el.getBoundingClientRect();
    el.style.transition = "none";
    el.style.translate = `${from.left - to.left}px ${from.top - to.top}px`;
    void el.offsetWidth;
    el.style.transition = "translate 340ms cubic-bezier(0.22, 0.61, 0.36, 1)";
    el.style.translate = "0px 0px";
    const done = () => {
      el.style.transition = "";
      el.style.translate = "";
    };
    el.addEventListener("transitionend", done, { once: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs when the park changes; group() reads the DOM
  }, [parkKey]);

  // quiet faces turn to listen while the pointer is on it
  const quiet = face === "idle" || face === "sleeping";
  const shown: AvatarState = hover && quiet && !small && !dragging ? "listening" : face;

  function click(e: React.MouseEvent) {
    if (performance.now() - dropped.current < 350) {
      dropped.current = 0;
      return;
    }
    // a second tap some browsers do not count as one (iOS): timed here
    const now = performance.now();
    const n = e.detail === 1 && now - lastClick.current < DOUBLE_MS + 60 ? 2 : e.detail;
    lastClick.current = now;
    const intent = clickIntent(n, small);
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (intent === "now") onAct();
    else if (intent === "later")
      timer.current = setTimeout(() => {
        timer.current = null;
        onAct();
      }, DOUBLE_MS);
    else if (intent === "double") onSmall();
  }

  function down(e: React.PointerEvent<HTMLButtonElement>) {
    if (docked || e.button !== 0 || !group()) return;
    drag.current = { x: e.clientX, y: e.clientY, id: e.pointerId, moved: false };
  }
  function move(e: React.PointerEvent<HTMLButtonElement>) {
    const d = drag.current;
    const el = group();
    if (!d || !el || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved) {
      if (Math.hypot(dx, dy) < 6) return;
      d.moved = true;
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        /* a pointer the browser no longer tracks: the drag still follows it */
      }
      setDragging(true);
    }
    el.style.transition = "none";
    el.style.translate = `${dx}px ${dy}px`;
  }
  function up(e: React.PointerEvent<HTMLButtonElement>) {
    const d = drag.current;
    drag.current = null;
    if (!d || !d.moved) return;
    dropped.current = performance.now();
    setDragging(false);
    const el = group();
    const body = e.currentTarget.getBoundingClientRect();
    if (el) settle.current = el.getBoundingClientRect();
    const next = snapPark(body, { width: window.innerWidth, height: window.innerHeight }, small);
    if (next.side === park.side && next.y === park.y) {
      // dropped where it was: slide straight back
      if (el) {
        el.style.transition = "translate 240ms cubic-bezier(0.22, 0.61, 0.36, 1)";
        el.style.translate = "0px 0px";
        el.addEventListener(
          "transitionend",
          () => {
            el.style.transition = "";
            el.style.translate = "";
          },
          { once: true },
        );
      }
      settle.current = null;
      return;
    }
    onDrop(next);
  }

  const ring = face === "working" || face === "thinking";
  const p = progress == null ? null : Math.max(0, Math.min(1, progress));
  return (
    <button
      ref={btn}
      type="button"
      className="zpa-creature"
      data-face={face}
      data-small={small ? "1" : undefined}
      data-docked={docked ? "1" : undefined}
      data-dragging={dragging ? "1" : undefined}
      aria-label={label}
      title={title}
      onClick={click}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={() => {
        drag.current = null;
        setDragging(false);
        const el = group();
        if (el) el.style.translate = "";
      }}
      onPointerEnter={() => setHover(true)}
      onPointerLeave={() => setHover(false)}
      style={{ "--zpa-tint": tintOf(avatar) } as CSSProperties}
    >
      <span className="zpa-floor" aria-hidden />
      {ring && !small ? (
        <svg className="zpa-floor-ring" viewBox="0 0 136 34" aria-hidden data-progress={p == null ? "sweep" : "known"}>
          <ellipse className="zpa-floor-track" cx="68" cy="17" rx="62" ry="13" />
          <ellipse
            className="zpa-floor-arc"
            cx="68"
            cy="17"
            rx="62"
            ry="13"
            pathLength={100}
            style={{ strokeDasharray: `${Math.round((p ?? 0.3) * 100)} 100` }}
          />
        </svg>
      ) : null}
      <span className="zpa-squish">
        <span className="zpa-sway">
          <AssistantAvatar avatar={avatar} state={shown} size="fill" />
        </span>
      </span>
      {face === "needs" ? <span className="zpa-light" aria-hidden /> : null}
      {face === "sleeping" && !small ? (
        <span className="zpa-zs" aria-hidden>
          <i>z</i>
          <i>z</i>
          <i>z</i>
        </span>
      ) : null}
      {unread > 0 ? (
        <span className="zpa-count" key={unread} aria-hidden>
          {unread > 9 ? "9+" : unread}
        </span>
      ) : null}
    </button>
  );
}

/* ── thoughts ── */

export type Lead =
  | {
      kind: "needs";
      title: string;
      body?: string;
      note?: string;
      primary: { label: string; run: () => void };
      secondary?: { label: string; run: () => void };
    }
  | { kind: "working"; label: string; text: string; progress: number | null }
  | { kind: "error"; line: string; retry: () => void; open: () => void }
  | { kind: "say"; line: string; open: () => void };

export type Idea = { text: string; run: () => void; open?: boolean };

export function Thoughts({ lead, ideas, busy, name }: { lead: Lead | null; ideas: Idea[]; busy: boolean; name: string }) {
  if (!lead && !ideas.length) return null;
  return (
    <div className="zpa-thoughts" role="group" aria-label={`What ${name} is thinking`}>
      {ideas.map((d, k) => (
        <button
          type="button"
          key={`${k}:${d.text}`}
          className={`zpa-idea${d.open ? " open" : ""}`}
          // every other one sits further from the head, so they read as
          // thoughts drifting up rather than a list
          data-alt={(ideas.length - 1 - k) % 2 ? "1" : undefined}
          style={{ "--k": ideas.length - 1 - k } as CSSProperties}
          disabled={busy && !d.open}
          onClick={d.run}
        >
          {d.open ? <span aria-hidden>+</span> : null}
          {d.text}
        </button>
      ))}
      {lead ? <LeadThought lead={lead} /> : null}
      {lead ? (
        <span className="zpa-puffs" data-kind={lead.kind} aria-hidden>
          <i />
          <i />
        </span>
      ) : null}
    </div>
  );
}

function LeadThought({ lead }: { lead: Lead }) {
  if (lead.kind === "needs")
    return (
      <div className="zpa-lead needs" role="status">
        <span className="zpa-lead-k">Needs you</span>
        <p>{lead.title}</p>
        {lead.body ? <p className="zpa-lead-body">{lead.body}</p> : null}
        <div className="zpa-lead-go">
          <button type="button" className="zpa-lead-yes" onClick={lead.primary.run}>
            {lead.primary.label}
          </button>
          {lead.secondary ? (
            <button type="button" className="zpa-lead-no" onClick={lead.secondary.run}>
              {lead.secondary.label}
            </button>
          ) : null}
          {lead.note ? <small>{lead.note}</small> : null}
        </div>
      </div>
    );
  if (lead.kind === "working")
    return (
      <div className="zpa-lead working" role="status">
        <span className="zpa-lead-k">{lead.label}</span>
        <p className="zpa-lead-live">{lead.text}</p>
        <span className="zpa-lead-bar" data-progress={lead.progress == null ? "sweep" : "known"}>
          <i style={{ width: `${Math.round((lead.progress ?? 0.35) * 100)}%` }} />
        </span>
      </div>
    );
  if (lead.kind === "error")
    return (
      <div className="zpa-lead error" role="status">
        <span className="zpa-lead-k">Didn&apos;t go through</span>
        <p>{lead.line}</p>
        <div className="zpa-lead-go">
          <button type="button" className="zpa-lead-yes" onClick={lead.retry}>
            Retry
          </button>
          <button type="button" className="zpa-lead-no" onClick={lead.open}>
            Open
          </button>
        </div>
      </div>
    );
  return (
    <button type="button" className="zpa-lead say" onClick={lead.open}>
      {lead.line}
    </button>
  );
}
