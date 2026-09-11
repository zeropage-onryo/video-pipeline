"use client";

/* `@` mentions: typing @word in a textarea autocompletes against
   /api/assets/search (characters + props + locations in one list).
   Picking one replaces the @word with the asset's name and hands the
   hit to onPick, so the caller can attach its frames — the composer
   adds the photos as references, the Director drops an element card
   on the canvas already wired in. */
import { useEffect, useRef, useState, type RefObject } from "react";
import { API_URL } from "@/lib/api";
import { searchAssets, type AssetHit } from "@/lib/studio-api";

export function useMentions(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
  setValue: (next: string) => void,
  onPick?: (hit: AssetHit) => void,
) {
  const [items, setItems] = useState<AssetHit[]>([]);
  const [cursor, setCursor] = useState(0);
  const token = useRef<{ start: number; end: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const close = () => {
    setItems([]);
    token.current = null;
  };

  const pick = (hit: AssetHit) => {
    const ta = ref.current;
    const tok = token.current;
    if (!ta || !tok) {
      close();
      return;
    }
    const next = value.slice(0, tok.start) + hit.name + value.slice(tok.end);
    setValue(next);
    const at = tok.start + hit.name.length;
    requestAnimationFrame(() => {
      ta.setSelectionRange(at, at);
      ta.focus();
    });
    close();
    onPick?.(hit);
  };

  // re-scan on every value change: the @word ends at the caret
  useEffect(() => {
    const ta = ref.current;
    if (!ta || document.activeElement !== ta) return;
    const pos = ta.selectionStart ?? value.length;
    const before = value.slice(0, pos);
    const match = before.match(/@([\w -]{0,40})$/);
    if (!match) {
      close();
      return;
    }
    token.current = { start: pos - match[0].length, end: pos };
    const q = match[1].trim();
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      searchAssets(q)
        .then((res) => {
          setItems(res.items);
          setCursor(0);
        })
        .catch(close);
    }, 120);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!items.length) return false;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(items.length - 1, c + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      pick(items[cursor]);
    } else if (e.key === "Escape") {
      e.stopPropagation();
      close();
    } else return false;
    return true;
  };

  const dropdown = items.length ? (
    <div className="mentiondrop" role="listbox">
      {items.map((it, i) => (
        <button
          type="button"
          key={`${it.category}-${it.name}`}
          className={`mention${i === cursor ? " cur" : ""}`}
          role="option"
          aria-selected={i === cursor}
          onMouseDown={(e) => {
            e.preventDefault();
            pick(it);
          }}
        >
          <span
            className="mth"
            style={it.thumb ? { backgroundImage: `url("${API_URL}${it.thumb}")` } : undefined}
          />
          <span>{it.name}</span>
          <span className="mcat">{it.category}</span>
        </button>
      ))}
    </div>
  ) : null;

  return { dropdown, onKeyDown, onBlur: () => setTimeout(close, 150) };
}
