"use client";

/* What each send made, drawn above the composer: the prompt as a bubble,
   then the result. IMAGE turns show the still; VIDEO turns show the
   written scene as its timed shots -- a scene is text until the Queue
   renders it, so it is never drawn as finished footage. */
import Link from "next/link";
import { Clapperboard, Film, ImagePlus, RotateCcw, Workflow } from "lucide-react";
import { cssAspect, mediaSrc, type Turn } from "@/lib/composer";

const pad = (n: number) => String(n).padStart(2, "0");
const ratioOf = (t: Turn) => cssAspect(t.frame) ?? "4 / 5";

function Meta({ t }: { t: Turn }) {
  if (t.status === "running") {
    return (
      <div className="zc-meta">
        <span className="zc-live" aria-hidden />
        {t.detail || (t.output === "image" ? "Drawing the image…" : "Writing the scene…")}
      </div>
    );
  }
  if (t.status === "failed") return <div className="zc-meta bad">{t.detail || "That one did not finish."}</div>;
  if (t.status === "stopped") return <div className="zc-meta">Stopped</div>;
  const bits =
    t.output === "image"
      ? ["1 image", t.frame].filter(Boolean)
      : [
          "Scene",
          t.parts?.length ? `${t.parts.length} shot${t.parts.length === 1 ? "" : "s"}` : null,
          t.seconds ? `${t.seconds}s` : null,
          t.frame,
        ].filter(Boolean);
  return <div className="zc-meta">{bits.join(" · ")}</div>;
}

export function ComposerTurns({
  turns,
  busy,
  onAnimate,
  onUseAsRef,
  onRetry,
}: {
  turns: Turn[];
  busy: boolean;
  onAnimate: (t: Turn) => void;
  onUseAsRef: (t: Turn) => void;
  onRetry: (t: Turn) => void;
}) {
  if (!turns.length) return null;
  return (
    <div className="zc-turns" aria-live="polite">
      {turns.map((t) => (
        <article key={t.id} className="zc-turn">
          <div className="zc-ask">
            <div className="zc-bubble">
              {t.refs.length ? (
                <span className="zc-bubble-refs">
                  {t.refs.slice(0, 4).map((u) => (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img key={u} src={mediaSrc(u)} alt="" />
                  ))}
                  {t.refs.length > 4 ? <b>+{t.refs.length - 4}</b> : null}
                </span>
              ) : null}
              <p>{t.prompt}</p>
            </div>
          </div>

          <Meta t={t} />

          {t.output === "image" ? (
            <div
              className="zc-image"
              data-state={t.status}
              style={{ aspectRatio: ratioOf(t), maxWidth: `calc(560px * (${ratioOf(t)}))` }}
            >
              {t.status === "done" && t.image ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={mediaSrc(t.image)} alt={t.prompt} />
              ) : t.status === "running" ? (
                <span className="zc-pct">{Math.round(t.progress * 100)}%</span>
              ) : t.status === "done" ? (
                <span className="zc-pct">Saved without an image · {t.detail}</span>
              ) : null}
              {t.status === "running" ? (
                <span className="zc-bar" style={{ width: `${Math.max(4, Math.round(t.progress * 100))}%` }} />
              ) : null}
            </div>
          ) : t.status === "done" ? (
            <div className="zc-scene">
              {t.title ? <b className="zc-scene-title">{t.title}</b> : null}
              {t.parts?.length ? (
                <ol className="zc-shots">
                  {t.parts.map((p) => (
                    <li key={p.n} className="zc-shot">
                      <span className="zc-shot-frame">
                        {p.reference_image ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={mediaSrc(p.reference_image)} alt="" />
                        ) : (
                          <span>{pad(p.n)}</span>
                        )}
                      </span>
                      <span className="zc-shot-time">
                        {p.start}–{p.end}s
                      </span>
                      <span className="zc-shot-text">{p.text || p.prompt}</span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="zc-scene-one">One continuous shot · {t.detail}</p>
              )}
            </div>
          ) : t.status === "running" ? (
            <div className="zc-scene running">
              <span className="zc-bar" style={{ width: `${Math.max(4, Math.round(t.progress * 100))}%` }} />
            </div>
          ) : null}

          {t.status === "done" ? (
            <div className="zc-actions">
              {t.output === "image" && t.image ? (
                <>
                  <button type="button" className="zc-act" disabled={busy} onClick={() => onAnimate(t)}>
                    <Film strokeWidth={1.6} /> Animate into a scene
                  </button>
                  <button type="button" className="zc-act" disabled={busy} onClick={() => onUseAsRef(t)}>
                    <ImagePlus strokeWidth={1.6} /> Use as reference
                  </button>
                </>
              ) : null}
              {t.output === "video" ? (
                <Link href="/studio/pipeline" className="zc-act">
                  <Workflow strokeWidth={1.6} /> Pick on Pipeline
                </Link>
              ) : null}
              {t.conceptId ? (
                <Link href={`/studio/flows?concept=${t.conceptId}&shot=1`} className="zc-act">
                  <Clapperboard strokeWidth={1.6} /> Open in Director
                </Link>
              ) : null}
              <button type="button" className="zc-act" disabled={busy} onClick={() => onRetry(t)}>
                <RotateCcw strokeWidth={1.6} /> Reuse prompt
              </button>
            </div>
          ) : t.status === "failed" || t.status === "stopped" ? (
            <div className="zc-actions">
              <button type="button" className="zc-act" disabled={busy} onClick={() => onRetry(t)}>
                <RotateCcw strokeWidth={1.6} /> Try again
              </button>
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}
