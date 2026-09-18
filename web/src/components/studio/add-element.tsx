"use client";

/* The add-element modal: name + one labelled field + notes + photos,
   straight to the always-on /api/assets/{characters|locations|props}
   create routes, which also teach the RAG assets shelf. A location
   needs at least one photo because its vision pass describes the space
   from them. Elements opens it empty; the Assets wall opens it as "Make
   element" with a render's URL already in the strip (2026-09-18) --
   `photo_urls` rides the same form and the server fetches the bytes. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Image as ImageIcon, LayoutGrid, X } from "lucide-react";
import { API_URL } from "@/lib/api";
import { createAsset, getCapabilities } from "@/lib/studio-api";

type Kind = "characters" | "locations" | "props";
const NOUN: Record<Kind, string> = { characters: "character", locations: "location", props: "prop" };
const DETAIL_PLACEHOLDER: Record<Kind, string> = {
  characters: "Role (e.g. the rider)",
  locations: "unused — the vision pass describes the space",
  props: "Category (e.g. helmet)",
};
/* what the sheet is, per kind (2026-09-18) — drawn on save as a job */
const SHEET_NOTE: Record<Kind, string> = {
  characters: "five panels — face, front, back, left, right — plus an info block",
  locations: "plates — wide, two angles, a detail",
  props: "a turnaround — front, three-quarter, side, detail",
};

export function AddElement({
  onClose,
  onSaved,
  title = "Add element",
  initialPhotoUrls = [],
  initialNotes = "",
}: {
  onClose: () => void;
  onSaved: (name: string, photos: number, note?: string | null, sheetJob?: number | null) => void;
  title?: string;
  /** renders already on the server, attached by URL (the Assets wall's "Make element") */
  initialPhotoUrls?: string[];
  initialNotes?: string;
}) {
  const [kind, setKind] = useState<Kind>("characters");
  const [detail, setDetail] = useState("");
  const [name, setName] = useState("");
  const [notes, setNotes] = useState(initialNotes);
  const [files, setFiles] = useState<File[]>([]);
  const [urls, setUrls] = useState<string[]>(initialPhotoUrls);
  const [sheet, setSheet] = useState(true);
  const [canDraw, setCanDraw] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const previews = useMemo(() => files.slice(0, 6).map((f) => URL.createObjectURL(f)), [files]);
  const locked = kind === "locations";
  const photoCount = files.length + urls.length;
  // the sheet is drawn on Nano; no image key, no switch to show
  useEffect(() => {
    getCapabilities()
      .then((c) => setCanDraw(c["nano.generate"] !== false))
      .catch(() => setCanDraw(false));
  }, []);
  const willDraw = sheet && canDraw === true && photoCount > 0;
  const canSave = name.trim().length > 0 && !busy && (kind !== "locations" || photoCount > 0);

  async function save() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("name", name.trim());
      if (!locked && detail.trim()) form.append(kind === "characters" ? "role" : "category", detail.trim());
      if (notes.trim()) form.append("notes", notes.trim());
      files.forEach((f) => form.append("photos", f, f.name));
      urls.forEach((u) => form.append("photo_urls", u));
      form.append("sheet", willDraw ? "1" : "0");
      const res = await createAsset(kind, form);
      onSaved(name.trim(), res.photos ?? photoCount, res.note, res.sheet_job ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
      setBusy(false);
    }
  }

  return (
    <div className="zmodal" onClick={onClose}>
      <div className="zdialog" role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="zdhead">
          <h3>{title}</h3>
          <span className="spacer" />
          <button type="button" className="zdx" onClick={onClose} aria-label="Close">
            <X strokeWidth={1.8} />
          </button>
        </div>
        <div className="zdbody">
          <div className="zfield">
            <span className="m">What is it</span>
            <div className="zrow">
              <select
                className="zin"
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value as Kind);
                  setDetail("");
                }}
                aria-label="Category"
              >
                <option value="characters">Character</option>
                <option value="locations">Location · photos get described</option>
                <option value="props">Prop</option>
              </select>
              <input
                className="zin grow"
                value={detail}
                disabled={locked}
                onChange={(e) => setDetail(e.target.value)}
                placeholder={DETAIL_PLACEHOLDER[kind]}
                aria-label="Detail"
              />
            </div>
          </div>
          <div className="zfield">
            <span className="m">Name</span>
            <input className="zin" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name…" aria-label="Name" />
          </div>
          <div className="zfield">
            <span className="m">Notes</span>
            <textarea
              className="zin"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Look, wardrobe, quirks — becomes a searchable chunk on the RAG assets shelf"
              aria-label="Notes"
            />
          </div>
          <div className="zfield">
            <span className="m">Photos{locked ? " · required for a location" : ""}</span>
            <label className="zdrop">
              <input
                ref={input}
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
              />
              <ImageIcon strokeWidth={1.6} />
              {photoCount ? `${photoCount} photo${photoCount === 1 ? "" : "s"} attached` : "Pick photos, or drop them here"}
            </label>
            {previews.length || urls.length ? (
              <div className="zpreviews">
                {urls.map((u) => (
                  <span key={u} className="relative" style={{ backgroundImage: `url(${API_URL}${u})` }} title="from the Assets wall">
                    <button
                      type="button"
                      className="zdx absolute -top-1.5 -right-1.5 h-5 w-5 min-h-0 rounded-full bg-black/80"
                      aria-label="Remove this render"
                      onClick={() => setUrls((was) => was.filter((x) => x !== u))}
                    >
                      <X size={10} strokeWidth={2} />
                    </button>
                  </span>
                ))}
                {previews.map((u) => (
                  <span key={u} style={{ backgroundImage: `url(${u})` }} />
                ))}
              </div>
            ) : null}
          </div>
          {canDraw ? (
            <label className="flex cursor-pointer items-start gap-3 rounded-[10px] border border-[var(--line)] p-3">
              <input type="checkbox" className="mt-1 accent-[var(--signal)]" checked={sheet} onChange={(e) => setSheet(e.target.checked)} />
              <span className="flex min-w-0 flex-col gap-1">
                <span className="m flex items-center gap-1.5">
                  <LayoutGrid size={11} strokeWidth={1.7} /> Draw a reference sheet
                </span>
                <span className="text-[12px] leading-snug text-[var(--dim)]">
                  {SHEET_NOTE[kind]}, drawn from the photos on Nano Banana Pro after the save — a few cents. Your photos stay first; the
                  sheet rides behind them into every shot.
                </span>
              </span>
            </label>
          ) : null}
          {error ? <div className="stateline err" style={{ padding: 0 }}>{error}</div> : null}
        </div>
        <div className="zdfoot">
          <span className="m">
            saves the {NOUN[kind]} + teaches the RAG assets shelf{willDraw ? " + draws the sheet" : ""}
          </span>
          <span className="spacer" />
          <button type="button" className="zbtn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="zbtn pri" disabled={!canSave} onClick={() => void save()}>
            {busy ? "Saving…" : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}
