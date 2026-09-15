"use client";

/* The element sheet (2026-09-15, Mike: "no click on to expand with
   options"): one element opened up -- its frames, kind, @handle, notes,
   how many shots it grounds -- with the things you can do to it. Shared by
   Elements (card click), the Studio shelf (the ⋯ on a plate) and the
   Assets rail.

   Delete is two-step and inline, never a browser confirm(): the first
   click turns into the question, the second answers it. It removes the
   element from every shelf and its RAG chunk; the photo bytes stay where
   they are (the bucket, the folder), which the question says. */
/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { useState } from "react";
import { AtSign, ImageOff, Trash2, X } from "lucide-react";
import { API_URL } from "@/lib/api";
import type { Asset } from "@/lib/studio-api";
import { deleteElement, displayPhoto, drawable, elementKind, handleOf, kindLabel } from "@/lib/elements";

export function ElementSheet({
  asset,
  usedIn,
  onClose,
  onDeleted,
  onAttach,
}: {
  asset: Asset;
  /** how many concepts name it; omitted when the caller does not know */
  usedIn?: number;
  onClose: () => void;
  onDeleted: (asset: Asset) => void;
  /** the Studio shelf attaches in place; elsewhere the action is a link there */
  onAttach?: (asset: Asset) => void;
}) {
  const [frame, setFrame] = useState<string | null>(displayPhoto(asset));
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const kind = kindLabel(elementKind(asset) ?? "prop");
  const frames = asset.photos.length;

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteElement(asset);
      onDeleted(asset);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete");
      setBusy(false);
      setAsking(false);
    }
  }

  return (
    <div className="zmodal" onClick={onClose}>
      <div className="zdialog elsheet" role="dialog" aria-label={asset.name} onClick={(e) => e.stopPropagation()}>
        <div className="zdhead">
          <h3>{asset.name}</h3>
          <span className="m eskind">{kind}</span>
          <span className="spacer" />
          <button type="button" className="zdx" onClick={onClose} aria-label="Close">
            <X strokeWidth={1.8} />
          </button>
        </div>
        <div className="zdbody esbody">
          <div className="esframe">
            {frame ? (
              <img src={`${API_URL}${frame}`} alt={asset.name} />
            ) : (
              <span className="m">
                <ImageOff strokeWidth={1.6} size={14} /> {frames ? "this frame cannot be previewed" : "no photos yet"}
              </span>
            )}
          </div>
          {frames > 1 ? (
            <div className="esstrip">
              {asset.photos.map((u) => (
                <button
                  type="button"
                  key={u}
                  className={u === frame ? "on" : ""}
                  data-ext={drawable(u) ? undefined : u.split(".").pop()?.split("?")[0]?.toUpperCase()}
                  style={drawable(u) ? { backgroundImage: `url("${API_URL}${u}")` } : undefined}
                  aria-label={u.split("/").pop()}
                  onClick={() => setFrame(u)}
                />
              ))}
            </div>
          ) : null}
          <dl className="esmeta">
            <dt>handle</dt>
            <dd className="mono">
              <AtSign size={11} strokeWidth={1.8} />
              {handleOf(asset.name).slice(1)}
            </dd>
            <dt>frames</dt>
            <dd>{frames ? `${frames} frame${frames === 1 ? "" : "s"}` : "none yet"}</dd>
            {usedIn !== undefined ? (
              <>
                <dt>used in</dt>
                <dd>{usedIn ? `${usedIn} shot${usedIn === 1 ? "" : "s"}` : "not used yet"}</dd>
              </>
            ) : null}
            {asset.text ? (
              <>
                <dt>notes</dt>
                <dd className="estext">{asset.text}</dd>
              </>
            ) : null}
          </dl>
          {error ? <div className="stateline err" style={{ padding: 0 }}>{error}</div> : null}
        </div>
        <div className="zdfoot esfoot">
          {asking ? (
            <>
              <span className="m esask">
                Delete {asset.name}? It leaves every shelf and the writer forgets it. Its photos stay in the bucket.
              </span>
              <span className="spacer" />
              <button type="button" className="zbtn" onClick={() => setAsking(false)} disabled={busy}>
                Keep it
              </button>
              <button type="button" className="zbtn danger" onClick={() => void remove()} disabled={busy}>
                <Trash2 strokeWidth={1.7} /> {busy ? "Deleting…" : "Delete"}
              </button>
            </>
          ) : (
            <>
              <button type="button" className="zbtn quiet" onClick={() => setAsking(true)} title="Delete this element">
                <Trash2 strokeWidth={1.7} /> Delete
              </button>
              <span className="spacer" />
              {onAttach ? (
                <button
                  type="button"
                  className="zbtn pri"
                  disabled={!frames}
                  title={frames ? undefined : "No frames to attach yet"}
                  onClick={() => onAttach(asset)}
                >
                  Attach as reference
                </button>
              ) : (
                <Link href={`/studio?attach=${encodeURIComponent(asset.id)}`} className="zbtn pri">
                  Use in Studio
                </Link>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
