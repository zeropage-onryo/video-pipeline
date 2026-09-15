"use client";

/* The new-element modal, shared by Studio and Elements: name + one
   labelled field + notes + photos, straight to the always-on
   /api/assets/{characters|locations|props} create routes, which also
   teach the RAG assets shelf. The four kinds a person picks (character,
   prop, product, place) map onto those three routes in lib/elements.ts:
   a product is a prop saved with category "product". A place needs at
   least one photo because its vision pass describes the space from them. */
import { useMemo, useRef, useState } from "react";
import { Image as ImageIcon, X } from "lucide-react";
import { createAsset } from "@/lib/studio-api";
import { CREATE_ROUTE, ELEMENT_KINDS, PRODUCT_KIND, type ElementKind } from "@/lib/elements";

type Kind = ElementKind;
const DETAIL_PLACEHOLDER: Record<Kind, string> = {
  character: "Role (e.g. the rider)",
  prop: "Category (e.g. helmet)",
  product: "unused — saved as a product",
  place: "unused — the vision pass describes the space",
};
const KIND_NOTE: Record<Kind, string> = {
  character: "",
  prop: "",
  product: "the thing the film is selling: a bottle, a jacket, a bike",
  place: "photos get described",
};

export function AddElement({
  onClose,
  onSaved,
  title = "Add element",
}: {
  onClose: () => void;
  onSaved: (name: string, photos: number, note?: string | null) => void;
  title?: string;
}) {
  const [kind, setKind] = useState<Kind>("character");
  const [detail, setDetail] = useState("");
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const previews = useMemo(() => files.slice(0, 6).map((f) => URL.createObjectURL(f)), [files]);
  const locked = kind === "place" || kind === "product";
  const canSave = name.trim().length > 0 && !busy && (kind !== "place" || files.length > 0);

  async function save() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("name", name.trim());
      if (kind === "product") form.append("category", PRODUCT_KIND);
      else if (!locked && detail.trim()) form.append(kind === "character" ? "role" : "category", detail.trim());
      if (notes.trim()) form.append("notes", notes.trim());
      files.forEach((f) => form.append("photos", f, f.name));
      const res = await createAsset(CREATE_ROUTE[kind], form);
      onSaved(name.trim(), res.photos ?? files.length, res.note);
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
                {ELEMENT_KINDS.map(({ id, one }) => (
                  <option key={id} value={id}>
                    {one[0].toUpperCase() + one.slice(1)}
                    {KIND_NOTE[id] ? ` · ${KIND_NOTE[id]}` : ""}
                  </option>
                ))}
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
            <span className="m">Photos{kind === "place" ? " · required for a place" : ""}</span>
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
              {files.length ? `${files.length} photo${files.length === 1 ? "" : "s"} attached` : "Pick photos, or drop them here"}
            </label>
            {previews.length ? (
              <div className="zpreviews">
                {previews.map((u) => (
                  <span key={u} style={{ backgroundImage: `url(${u})` }} />
                ))}
              </div>
            ) : null}
          </div>
          {error ? <div className="stateline err" style={{ padding: 0 }}>{error}</div> : null}
        </div>
        <div className="zdfoot">
          <span className="m">saves the {kind} + teaches the RAG assets shelf</span>
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
