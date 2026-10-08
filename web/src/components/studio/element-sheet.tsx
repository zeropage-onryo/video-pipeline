"use client";

/* The element sheet (2026-09-15, Mike: "no click on to expand with
   options"): one element opened up -- its frames, kind, @handle, notes,
   how many shots it grounds -- with the things you can do to it. Shared by
   Elements (card click), the Studio shelf (the ⋯ on a plate) and the
   Assets rail.

   Delete is two-step and inline, never a browser confirm(): the first
   click turns into the question, the second answers it. It removes the
   element from every shelf and its RAG chunk; the photo bytes stay where
   they are (the bucket, the folder), which the question says. The answer
   is still undoable for a few seconds (useElementDelete below). */
/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { useCallback, useState } from "react";
import { AtSign, ImageOff, Trash2, X } from "lucide-react";
import { API_URL } from "@/lib/api";
import { holdElementDelete, type Asset } from "@/lib/studio-api";
import { deleteElement, displayPhoto, drawable, elementKind, handleOf, kindLabel } from "@/lib/elements";
import { useShell } from "@/components/studio/shell";

/** Delete an element WITH an Undo (2026-10-08). The server's delete is a
 *  hard DELETE -- the row and its notes are gone -- so it is HELD: `hide`
 *  takes the element off the page now (and getAssets leaves it out of any
 *  listing read meanwhile), the DELETE goes when the toast closes or the
 *  page is left, and Undo calls `restore` with nothing ever sent. A DELETE
 *  that fails puts the element back and says so. */
export function useElementDelete() {
  const { toast } = useShell();
  return useCallback(
    (asset: Asset, { hide, restore }: { hide: () => void; restore: () => void }) => {
      holdElementDelete(asset.id, true);
      hide();
      toast(`${asset.name} deleted · photos stay in the bucket`, "ok", {
        action: {
          label: "Undo",
          run: () => {
            holdElementDelete(asset.id, false);
            restore();
            toast(`${asset.name} is back`);
          },
        },
        onClose: () => {
          deleteElement(asset, { keepalive: true })
            .then(() => holdElementDelete(asset.id, false))
            .catch((e) => {
              holdElementDelete(asset.id, false);
              toast(`${asset.name} was not deleted${e instanceof Error ? `: ${e.message}` : ""}`, "err");
              restore();
            });
        },
      });
    },
    [toast],
  );
}

export function ElementSheet({
  asset,
  usedIn,
  onClose,
  onDeleted,
  onRestored,
  onAttach,
}: {
  asset: Asset;
  /** how many concepts name it; omitted when the caller does not know */
  usedIn?: number;
  onClose: () => void;
  /** take it off the page: the delete itself is held behind an Undo */
  onDeleted: (asset: Asset) => void;
  /** the Undo: it was never deleted, so the page reads it back */
  onRestored: (asset: Asset) => void;
  /** the Studio shelf attaches in place; elsewhere the action is a link there */
  onAttach?: (asset: Asset) => void;
}) {
  const [frame, setFrame] = useState<string | null>(displayPhoto(asset));
  const [asking, setAsking] = useState(false);
  const kind = kindLabel(elementKind(asset) ?? "prop");
  const frames = asset.photos.length;
  const removeElement = useElementDelete();

  function remove() {
    removeElement(asset, { hide: () => onDeleted(asset), restore: () => onRestored(asset) });
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
        </div>
        <div className="zdfoot esfoot">
          {asking ? (
            <>
              <span className="m esask">
                Delete {asset.name}? It leaves every shelf and the writer forgets it. Its photos stay in the bucket.
              </span>
              <span className="spacer" />
              <button type="button" className="zbtn" onClick={() => setAsking(false)}>
                Keep it
              </button>
              <button type="button" className="zbtn danger" onClick={remove}>
                <Trash2 strokeWidth={1.7} /> Delete
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
