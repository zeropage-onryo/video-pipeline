/* Reading a reference URL (2026-09-17, the image-first cards).

   `parseRef` is the TypeScript twin of src/asset_shelf.parse_ref, the ONE
   parser of a reference URL -- same rules, same order: strip the query,
   take the path of an absolute URL, refuse a path that climbs, drop the
   local route's "photo" segment. A ref is stored as the public R2 URL when
   R2 is configured and as the local route when it is not; both must read
   the same, or a caption quietly goes missing (the 2026-09-08 lesson).

   `sourcesFor` prefers the LOCAL route: the API's photo routes and its
   /refs mount serve the file when that machine has it and 302 into R2 when
   it does not, so asking there first reads the Mac's photos off disk and
   still resolves on the deployed site. The stored URL is the second try;
   the component draws a labelled slate when both fail. Never a blank.

   No imports, on purpose: tests/refs.test.mjs loads this file with node's
   type stripping, where the "@/..." alias does not resolve. */

export type ParsedRef = {
  kind: "refs" | "character" | "prop" | "location";
  plural: string;
  slug: string;
  filename: string;
};

const ROOTS: Record<string, ParsedRef["kind"]> = {
  characters: "character",
  props: "prop",
  locations: "location",
};

const decode = (s: string) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

export function parseRef(url: string | null | undefined): ParsedRef | null {
  let raw = String(url || "").split("?")[0].trim();
  if (!raw) return null;
  if (raw.includes("://")) {
    try {
      raw = new URL(raw).pathname;
    } catch {
      return null;
    }
  }
  let parts = raw.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
  if (!parts.length || parts.some((p) => p === "." || p === "..")) return null;
  if (parts.length === 4 && parts[2] === "photo") parts = [parts[0], parts[1], parts[3]];
  if (parts.length === 2 && parts[0] === "refs") {
    return { kind: "refs", plural: "refs", slug: "", filename: parts[1] };
  }
  if (parts.length === 3 && ROOTS[parts[0]]) {
    return { kind: ROOTS[parts[0]], plural: parts[0], slug: parts[1], filename: parts[2] };
  }
  return null;
}

function localRoute(ref: ParsedRef, thumb: boolean): string {
  const file = encodeURIComponent(decode(ref.filename));
  if (ref.kind === "refs") return `/refs/${file}`;
  return `/${ref.plural}/${encodeURIComponent(decode(ref.slug))}/photo/${file}${thumb ? "?thumb=1" : ""}`;
}

/** Every URL worth trying for this picture, best first. `base` is the API
 *  origin ("" when the Next proxy serves the photo routes same-origin);
 *  `thumb` asks the photo route for its cached small JPEG first; `small`
 *  is the server's own thumbnail for it (the card payload's `ref_thumbs`,
 *  parallel to `refs` -- BACKLOG #0) and goes before everything else, so
 *  an R2 photo draws its 480px derivative instead of the master. */
export function sourcesFor(url: string, opts: { thumb?: boolean; base?: string; small?: string } = {}): string[] {
  const { thumb = false, base = "", small = "" } = opts;
  const ref = parseRef(url);
  const out: string[] = [];
  const push = (u: string) => {
    if (u && !out.includes(u)) out.push(u);
  };
  if (small) push(small.startsWith("/") ? base + small : small);
  if (ref) {
    push(base + localRoute(ref, thumb));
    if (thumb && ref.kind !== "refs") push(base + localRoute(ref, false));
  }
  push(url.startsWith("/") ? base + url : url);
  return out;
}

export function fileName(url: string): string {
  const ref = parseRef(url);
  if (ref) return decode(ref.filename);
  const path = String(url || "").split("?")[0];
  return decode(path.slice(path.lastIndexOf("/") + 1)) || "image";
}

/** What the URL itself proves about where a picture came from. The card
 *  payload carries a ref as a bare URL -- no source_url, no attribution
 *  (that lives on scout_bin rows the card API does not join) -- so this is
 *  the shelf, not the source. A caller that HAS a source passes it. */
export function sourceLabel(url: string): string {
  const ref = parseRef(url);
  if (ref) {
    return ref.kind === "refs" ? "REFERENCE BIN" : `ASSET BANK · ${ref.kind.toUpperCase()} · ${decode(ref.slug)}`;
  }
  if (/\/renders\//.test(String(url))) return "DRAWN BY THE PIPELINE";
  try {
    return new URL(url, "http://local.invalid").hostname.replace("local.invalid", "").toUpperCase();
  } catch {
    return "";
  }
}

export type RefSource = { url: string; kind: string; slug: string; filename: string; source_url: string; title: string; lane: string };

/** The caption for a row of the card's `ref_sources` (2026-09-17): the page
 *  a scouted frame was taken from, as a LINK -- these are other people's
 *  frames held as mood reference, and the attribution has to be one click
 *  from the picture. An upload has no page and says so; a bin image the bin
 *  has no row for says THAT rather than implying a source. Only http(s) is
 *  ever linked. (app/static/zpf/preview.js `sourcedItem` is the twin.) */
export function sourced(row: RefSource): { url: string; name: string; source: string; href?: string } {
  const base = { url: row.url, name: fileName(row.url), source: sourceLabel(row.url) };
  const href = /^https?:\/\//i.test(row.source_url || "") ? row.source_url : "";
  if (href) {
    let host = href;
    try {
      host = new URL(href).hostname.replace(/^www\./, "");
    } catch {
      /* keep the url */
    }
    return { ...base, href, source: `${(row.lane || "scouted").toUpperCase()} · ${host}${row.title ? " · " + row.title : ""}` };
  }
  if (row.kind === "refs") {
    return {
      ...base,
      source: row.lane === "composer" ? "YOUR UPLOAD · NO SOURCE PAGE" : row.lane ? `${row.lane.toUpperCase()} · NO SOURCE ON FILE` : "REFERENCE BIN · NO SOURCE ON FILE",
    };
  }
  return base;
}
