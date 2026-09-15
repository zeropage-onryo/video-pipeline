/* Elements are the things a person CREATES to hold a shot to -- characters,
   props, products and places -- and @-mentions in a prompt (Mike's call,
   2026-09-15). They are a blank slate until one is made, and they are not
   the Assets wall: the studio's own generated stills live there and never
   on an element shelf.

   The API stores three kinds (characters, locations, props). The four the
   product shows map onto them here, in one place: a place IS a location
   row, and a product IS a prop row whose `category` (meta.kind) is
   "product" -- so Products needs no new table, and a prop saved before
   the kind existed stays a prop. */
import { deleteAsset, type Asset } from "@/lib/studio-api";

export type ElementKind = "character" | "prop" | "product" | "place";

export const PRODUCT_KIND = "product";

export const ELEMENT_KINDS: { id: ElementKind; label: string; one: string }[] = [
  { id: "character", label: "Characters", one: "character" },
  { id: "prop", label: "Props", one: "prop" },
  { id: "product", label: "Products", one: "product" },
  { id: "place", label: "Places", one: "place" },
];

/** the API route a kind is created through */
export const CREATE_ROUTE: Record<ElementKind, "characters" | "locations" | "props"> = {
  character: "characters",
  prop: "props",
  product: "props",
  place: "locations",
};

export function elementKind(a: Asset): ElementKind | null {
  switch (a.category) {
    case "character":
      return "character";
    case "location":
      return "place";
    case "prop":
      return String(a.meta?.kind ?? "").trim().toLowerCase() === PRODUCT_KIND ? "product" : "prop";
    default:
      return null;
  }
}

export const isElement = (a: Asset) => elementKind(a) !== null;

export const kindLabel = (k: ElementKind) => ELEMENT_KINDS.find((x) => x.id === k)?.one ?? k;

/* Half the asset bank comes off an iPhone as HEIC, which the API serves
   happily and no browser can draw. The renderers decode it server-side
   (pillow-heif), so a HEIC ref is a valid reference -- it just cannot be
   a thumbnail. */
const UNDRAWABLE = /\.(heic|heif)(\?|$)/i;
export const drawable = (url: string) => !UNDRAWABLE.test(url);

/** the frame to show for an element: the first photo a browser can draw,
 *  else nothing (the plate falls back to its blank state) */
export function displayPhoto(a: Asset): string | null {
  return a.photos.find(drawable) ?? (a.poster && drawable(a.poster) ? a.poster : null);
}

export const handleOf = (name: string) =>
  "@" + name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** DELETE the element's row through its kind's route. The asset id the API
 *  lists is "<table>-<rowid>" (character-2, location-5, prop-12). */
export function deleteElement(a: Asset) {
  const kind = elementKind(a);
  const rowId = Number(String(a.id).split("-").pop());
  if (!kind || !Number.isFinite(rowId)) return Promise.reject(new Error("not an element"));
  return deleteAsset(CREATE_ROUTE[kind], rowId);
}
