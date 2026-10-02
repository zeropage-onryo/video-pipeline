"use client";

/* The `/` menu above the composer. Keyboard is owned by the textarea
   (page.tsx: arrows move, Enter/Tab pick, Escape closes); this only
   draws the list and takes clicks. */
import type { SlashCommand } from "@/lib/composer";

const GROUP_LABEL: Record<SlashCommand["group"], string> = {
  make: "Make",
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
  if (!items.length) {
    return (
      <div className="zc-slash" role="listbox" aria-label="Commands">
        <div className="zc-slash-empty">No command matches</div>
      </div>
    );
  }
  return (
    <div className="zc-slash" role="listbox" aria-label="Commands">
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
    </div>
  );
}
