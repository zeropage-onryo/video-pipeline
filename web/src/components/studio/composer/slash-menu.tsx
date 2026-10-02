"use client";

/* The `/` menu above the composer (the mock's "VIDEO PRESETS" list).
   Keyboard is owned by the textarea (page.tsx: arrows move, Enter/Tab
   pick, Escape closes); this only draws the list and takes clicks. */
import { motion } from "motion/react";
import type { SlashCommand } from "@/lib/composer";

const GROUP_LABEL: Record<SlashCommand["group"], string> = {
  make: "Commands",
  camera: "Camera presets",
  use: "Use",
};

export function SlashMenu({
  items,
  active,
  onPick,
  onHover,
}: {
  items: SlashCommand[];
  active: number;
  onPick: (c: SlashCommand) => void;
  onHover: (i: number) => void;
}) {
  return (
    <motion.div
      className="zc-slash"
      role="listbox"
      aria-label="Commands"
      initial={{ opacity: 0, y: 6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 6, scale: 0.98 }}
      transition={{ duration: 0.16, ease: [0.22, 0.61, 0.36, 1] }}
    >
      {!items.length ? <div className="zc-slash-empty">No command matches</div> : null}
      {items.map((c, i) => {
        const head = i === 0 || items[i - 1].group !== c.group ? GROUP_LABEL[c.group] : null;
        return (
          <div key={c.id}>
            {head ? <div className="zc-slash-head">{head}</div> : null}
            <button
              type="button"
              role="option"
              aria-selected={i === active}
              className="zc-slash-item"
              // mousedown, not click: the textarea's blur would close the
              // menu before a click landed
              onMouseDown={(e) => {
                e.preventDefault();
                onPick(c);
              }}
              onMouseEnter={() => onHover(i)}
            >
              <span className="zc-slash-cmd">/{c.cmd}</span>
              <span className="zc-slash-desc">{c.desc}</span>
            </button>
          </div>
        );
      })}
    </motion.div>
  );
}
