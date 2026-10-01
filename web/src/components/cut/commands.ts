"use client";

/* Every manual tool, named once (2026-09-28): Editor mode's palette lists
   these, and the keyboard map below binds the same ids -- a shortcut and
   a palette entry cannot drift into two different edits.

   The keys follow the task list and Resolve where they agree: Space and
   J/K/L for the transport, ←/→ a frame, Shift+←/→ a second, B / Cmd+B split
   at the playhead, Delete lifts and Shift+Delete ripples, N flips snapping,
   Cmd+Z / Cmd+Shift+Z undo and redo, +/− zoom and Shift+Z fits. A is the
   select tool and C the blade (B is taken by split, per the task list). */
import { useEffect } from "react";
import {
  ArrowDownToLine,
  ArrowLeftRight,
  ArrowRightToLine,
  Replace,
  Captions,
  Diamond,
  Download,
  Magnet,
  MousePointer2,
  Pause,
  Redo2,
  Scissors,
  Slice,
  Trash2,
  Undo2,
  ZoomIn,
  ZoomOut,
  type LucideIcon,
} from "lucide-react";
import { useCut } from "@/lib/cut/store";
import {
  addMarkerAtPlayhead,
  deleteSelection,
  jumpCut,
  nudge,
  splitAtPlayhead,
  toEnd,
  toStart,
  editFromSource,
  sourceToMark,
} from "@/lib/cut/actions";
import { clampPps, endOf, fitPps } from "@/lib/cut/timeline";

export type Command = {
  id: string;
  label: string;
  icon: LucideIcon;
  keys?: string;
  words?: string[];
  run: () => void;
};

const s = () => useCut.getState();

/* where the timeline's width lives, for "zoom to fit" */
export const timelineWidth = () =>
  (document.querySelector(".cx-scroll") as HTMLElement | null)?.clientWidth ?? 900;

export function zoomBy(factor: number) {
  s().setPps(clampPps(s().pps * factor));
}
export function zoomToFit() {
  const d = s().doc;
  if (!d) return;
  s().setPps(fitPps(Math.max(endOf(d), d.fps * 5), d.fps, timelineWidth()));
  const el = document.querySelector(".cx-scroll") as HTMLElement | null;
  if (el) el.scrollLeft = 0;
}
export function togglePlay() {
  const st = s();
  const d = st.doc;
  if (st.playing) return st.setPlaying(false);
  if (d && st.playhead >= endOf(d)) st.seek(0);
  st.setRate(1);
  st.setPlaying(true);
}
export function openExport() {
  window.dispatchEvent(new Event("zpf:cut-export"));
}

export const COMMANDS: Command[] = [
  { id: "split", label: "Split at playhead", icon: Scissors, keys: "B", words: ["cut", "razor", "blade"], run: splitAtPlayhead },
  { id: "lift", label: "Delete (leave the gap)", icon: Trash2, keys: "Del", words: ["remove", "lift"], run: () => void deleteSelection(false) },
  { id: "ripple", label: "Ripple delete", icon: Trash2, keys: "⇧Del", words: ["close gap", "remove"], run: () => void deleteSelection(true) },
  { id: "marker", label: "Add marker", icon: Diamond, keys: "M", words: ["chapter"], run: () => addMarkerAtPlayhead() },
  {
    id: "caption",
    label: "Add caption at playhead",
    icon: Captions,
    keys: "T",
    words: ["text", "title", "subtitle"],
    run: () => s().setLeftTab("text"),
  },
  { id: "undo", label: "Undo", icon: Undo2, keys: "⌘Z", run: () => void s().undo() },
  { id: "redo", label: "Redo", icon: Redo2, keys: "⌘⇧Z", run: () => void s().redo() },
  { id: "fit", label: "Zoom to fit", icon: ArrowLeftRight, keys: "⇧Z", words: ["whole", "overview"], run: zoomToFit },
  { id: "zin", label: "Zoom in", icon: ZoomIn, keys: "+", run: () => zoomBy(1.5) },
  { id: "zout", label: "Zoom out", icon: ZoomOut, keys: "−", run: () => zoomBy(1 / 1.5) },
  { id: "snap", label: "Toggle snapping", icon: Magnet, keys: "N", words: ["magnet"], run: () => s().toggleSnap() },
  { id: "select", label: "Select tool", icon: MousePointer2, keys: "A", run: () => s().setTool("select") },
  { id: "blade", label: "Blade tool", icon: Slice, keys: "C", words: ["razor"], run: () => s().setTool("blade") },
  { id: "play", label: "Play / pause", icon: Pause, keys: "Space", run: togglePlay },
  { id: "src-insert", label: "Insert from Source", icon: ArrowDownToLine, keys: "F9", words: ["source", "insert"], run: () => void editFromSource("insert") },
  { id: "src-overwrite", label: "Overwrite from Source", icon: Replace, keys: "F10", words: ["source", "overwrite"], run: () => void editFromSource("overwrite") },
  { id: "src-append", label: "Append from Source", icon: ArrowRightToLine, keys: "⇧F12", words: ["source", "append"], run: () => void editFromSource("append") },
  { id: "export", label: "Export…", icon: Download, keys: "⌘E", words: ["render", "mp4", "download"], run: openExport },
];

export function runCommand(c: Command) {
  c.run();
}

const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
};

/* The editor's keyboard. Mounted once by the editor page; it ignores keys
   typed into a field, so writing a caption never splits a clip. */
export function useEditorKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.defaultPrevented) return;
      const st = s();
      const mod = e.metaKey || e.ctrlKey;
      const key = e.key;
      const fps = st.doc?.fps ?? 30;
      const handled = () => e.preventDefault();

      if (mod && key.toLowerCase() === "z") {
        handled();
        return void (e.shiftKey ? st.redo() : st.undo());
      }
      if (mod && key.toLowerCase() === "y") {
        handled();
        return void st.redo();
      }
      if (mod && key.toLowerCase() === "b") {
        handled();
        return splitAtPlayhead();
      }
      if (mod && key.toLowerCase() === "e") {
        handled();
        return openExport();
      }
      if (mod) return;

      /* The Source viewer's keys. Marking and the three edits work from
         either viewer once a clip is loaded (I/O always mean the Source,
         since the timeline has no In/Out of its own yet); the transport
         keys follow whichever viewer is active. */
      if (st.source.handle) {
        const lower = key.toLowerCase();
        if (lower === "i" || lower === "o") {
          handled();
          if (e.shiftKey) return sourceToMark(lower === "i" ? "in" : "out");
          return lower === "i" ? st.markIn() : st.markOut();
        }
        if (e.altKey && lower === "x") {
          handled();
          return st.clearMarks();
        }
        if (key === "F9" || key === ",") {
          handled();
          return void editFromSource("insert");
        }
        if (key === "F10" || key === ".") {
          handled();
          return void editFromSource("overwrite");
        }
        if (key === "F12" && e.shiftKey) {
          handled();
          return void editFromSource("append");
        }
        if (st.activeViewer === "source") {
          const src = st.source;
          const go = (f: number) => {
            st.setSourcePlaying(false);
            st.sourceSeek(f);
          };
          switch (key) {
            case " ":
              handled();
              if (src.playing) return st.setSourcePlaying(false);
              st.setSourceRate(1);
              return st.setSourcePlaying(true);
            case "k":
            case "K":
              handled();
              return st.setSourcePlaying(false);
            case "l":
            case "L":
              handled();
              st.setSourceRate(src.playing && src.rate > 0 ? Math.min(4, src.rate * 2) : 1);
              return st.setSourcePlaying(true);
            case "j":
            case "J":
              handled();
              st.setSourceRate(src.playing && src.rate < 0 ? Math.max(-4, src.rate * 2) : -1);
              return st.setSourcePlaying(true);
            case "ArrowLeft":
              handled();
              return go(src.playhead - (e.shiftKey ? fps : 1));
            case "ArrowRight":
              handled();
              return go(src.playhead + (e.shiftKey ? fps : 1));
            case "Home":
              handled();
              return go(0);
            case "End":
              handled();
              return go((src.frames ?? 1) - 1);
          }
        }
      }

      // Resolve's page keys: Shift+4 Edit, Shift+6 Color, Shift+7 Fairlight
      // (Audio). `code`, because Shift turns the key into $ ^ &
      if (e.shiftKey && !mod) {
        const page = { Digit4: "edit", Digit6: "color", Digit7: "audio" }[e.code] as
          | "edit"
          | "color"
          | "audio"
          | undefined;
        if (page) {
          handled();
          return st.setPage(page);
        }
      }

      // Shift+Z, whichever case the platform reports the key in
      if (e.shiftKey && key.toLowerCase() === "z") {
        handled();
        return zoomToFit();
      }

      switch (key) {
        case " ":
          handled();
          return togglePlay();
        case "k":
        case "K":
          handled();
          return st.setPlaying(false);
        case "l":
        case "L": {
          handled();
          const r = st.playing && st.rate > 0 ? Math.min(4, st.rate * 2) : 1;
          st.setRate(r);
          if (!st.playing) st.setPlaying(true);
          return;
        }
        case "j":
        case "J": {
          handled();
          const r = st.playing && st.rate < 0 ? Math.max(-4, st.rate * 2) : -1;
          st.setRate(r);
          if (!st.playing) st.setPlaying(true);
          return;
        }
        case "ArrowLeft":
          handled();
          return nudge(e.shiftKey ? -fps : -1);
        case "ArrowRight":
          handled();
          return nudge(e.shiftKey ? fps : 1);
        case "ArrowUp":
          handled();
          return jumpCut(-1);
        case "ArrowDown":
          handled();
          return jumpCut(1);
        case "Home":
          handled();
          return toStart();
        case "End":
          handled();
          return toEnd();
        case "b":
        case "B":
          handled();
          return splitAtPlayhead();
        case "Delete":
        case "Backspace":
          handled();
          return void deleteSelection(e.shiftKey);
        case "n":
        case "N":
          handled();
          return st.toggleSnap();
        case "a":
        case "A":
          return st.setTool("select");
        case "c":
        case "C":
          return st.setTool("blade");
        case "m":
        case "M":
          handled();
          return addMarkerAtPlayhead();
        case "t":
        case "T":
          return st.setLeftTab("text");
        case "+":
        case "=":
          handled();
          return zoomBy(1.5);
        case "-":
        case "_":
          handled();
          return zoomBy(1 / 1.5);
        case "Escape":
          return st.clearSelection();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
