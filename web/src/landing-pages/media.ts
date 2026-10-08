// Where a landing page's clips are served from (2026-10-08, Mike: "upload
// the clips to R2"). MP4s are gitignored (`*.mp4`), so the files cannot ship
// with the site the way the posters and stills under public/models/ do;
// they live in the R2 bucket under `site/` with the same path, and every
// component that draws a clip asks this one function for its URL. Entries
// keep writing the public path ("/models/<slug>/<name>.mp4"), so a clip is
// added by uploading it to `site/models/<slug>/` and naming it on the entry.
//
// The base is the bucket's public domain, the one landing-media.ts and the
// sign-in showcase already read; `site/` sits outside the `m/` and `t/`
// prefixes the media lifecycle rules match, so nothing ages these out.
export const CLIP_BASE = "https://pub-62d6d70ed50d44449d464cd43245b69d.r2.dev/site";

/** A clip's playable URL: a /models/ MP4 from the bucket, anything else as given. */
export function clipSrc(src?: string): string | undefined {
  if (!src) return src;
  return src.startsWith("/models/") && src.endsWith(".mp4") ? `${CLIP_BASE}${src}` : src;
}
