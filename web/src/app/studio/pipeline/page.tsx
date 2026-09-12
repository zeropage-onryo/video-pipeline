"use client";

/* Pipeline — the board you decide on, and nothing else (2026-09-12, the
   "ZPF Pipeline" design). A concept IS one scene IS one prompt, so this
   is one grid of cards and one question: which of these is worth the
   spend. The references it was written against ABOVE, the concept, then
   the prompt BELOW, folded away until a card is opened.

   Picking is the label (pick_rate) and puts the concept in front of the
   Queue; approving THERE renders. Leaving the board is archiving, never
   deleting — an unpicked row is the only negative signal this system
   collects. Only one-shot concepts are the unit; a legacy multi-shot row
   is left to the Dev Studio. */
/* eslint-disable @next/next/no-img-element */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Check, Clock, Image as ImageIcon, ListVideo, Monitor, RectangleVertical, Undo2, Workflow, X } from "lucide-react";
import { API_URL } from "@/lib/api";
import {
  announceQueueChange,
  archiveConcept,
  boardConcepts,
  pickConcept,
  queuePending,
  updateShotPrompt,
  type Concept,
  type PickRate,
  type RunwayState,
} from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";

type Filter = "open" | "picked" | "archived";
const ratioLabel = (r?: string) => (r === "720:1280" ? "9:16" : r === "1280:720" ? "16:9" : r || "9:16");

function statusOf(c: Concept) {
  if (c.archived) return "archived";
  if (c.media_url) return "rendered";
  if (c.picked) return "picked · awaiting approval in queue";
  if (c.parked) return "keyframed · awaiting approval in queue";
  return "open";
}

export default function PipelinePage() {
  const { brand, toast } = useShell();
  const [filter, setFilter] = useState<Filter>("open");
  const [all, setAll] = useState<Concept[] | null>(null);
  const [rate, setRate] = useState<PickRate | null>(null);
  const [runway, setRunway] = useState<RunwayState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<Record<number, boolean>>({});

  const load = () => {
    boardConcepts(brand || undefined, true)
      .then((r) => {
        setAll(r.items.filter((c) => c.is_scene));
        setRate(r.pick ?? null);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Concepts unavailable"));
  };
  useEffect(() => {
    if (brand === "" && all !== null) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brand]);
  useEffect(() => {
    queuePending()
      .then((r) => setRunway(r.runway))
      .catch(() => setRunway(null));
  }, []);

  const open = useMemo(() => (all || []).filter((c) => !c.archived), [all]);
  const gone = useMemo(() => (all || []).filter((c) => c.archived), [all]);
  const cards = filter === "archived" ? gone : filter === "picked" ? open.filter((c) => c.picked) : open;
  const scope = `${brand || "—"} · ${open.length} open · ${gone.length} archived`;
  const countLine = rate?.generated ? `${scope} · ${rate.picked}/${rate.generated} picked all time, all brands` : scope;

  const act = async (c: Concept, fn: () => Promise<unknown>, done?: string) => {
    setBusy((b) => ({ ...b, [c.id]: true }));
    try {
      await fn();
      if (done) toast(done);
      load();
      announceQueueChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through", "err");
    } finally {
      setBusy((b) => ({ ...b, [c.id]: false }));
    }
  };

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className="vhead" style={{ marginTop: 8 }}>
        <h2>Pipeline</h2>
        <span className="m">pick the ones worth the spend — approving them in Queue is what renders</span>
        <span className="spacer" />
        <span className="m">{countLine}</span>
      </div>
      <div className="chead">
        <h3>Concepts</h3>
        <span className="spacer" />
        <div className="cats" style={{ margin: 0, padding: 0 }}>
          {(["open", "picked", "archived"] as Filter[]).map((f) => (
            <button type="button" key={f} className="cat" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {error ? <div className="stateline err" style={{ padding: "0 42px 14px" }}>{error}</div> : null}
      {all && !cards.length ? (
        <p className="stateline" style={{ padding: "0 42px" }}>
          {filter === "archived"
            ? "Nothing archived yet"
            : filter === "picked"
              ? "Nothing picked yet — the check on a card sends it to Queue"
              : "No concepts open — type an idea on Studio and hit Create"}
        </p>
      ) : null}

      <div className="scenegrid">
        {cards.map((c) => {
          const isOpen = openId === c.id;
          const draft = drafts[c.id] ?? c.prompt;
          const dirty = draft.trim() !== (c.prompt || "").trim();
          return (
            <article
              key={c.id}
              className={`scene${c.picked || c.parked ? " on" : ""}${c.archived ? " off" : ""}${isOpen ? " open" : ""}`}
              onClick={() => setOpenId(isOpen ? null : c.id)}
            >
              <div className="screfs">
                {(c.refs || []).slice(0, 4).map((u) => (
                  <span key={u} className="scref" style={{ backgroundImage: `url("${API_URL}${u}")` }} />
                ))}
                {!(c.refs || []).length ? <span className="m">no references</span> : null}
                <span className="spacer" />
                <span className="m">{c.spark || ""}</span>
              </div>
              <div className="schead">
                <h4>{c.title}</h4>
                <span className="m">{c.n}</span>
                <span className="spacer" />
                {c.media_url ? (
                  <a className="tag" href={c.media_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                    clip ↗
                  </a>
                ) : null}
                <span className="m">{statusOf(c)}</span>
              </div>
              {c.summary ? <p className="scsum">{c.summary}</p> : null}

              {isOpen ? (
                <div className="scbody" onClick={(e) => e.stopPropagation()}>
                  <div className="scframe">
                    {c.reference_image ? (
                      <img src={c.reference_image.startsWith("/") ? `${API_URL}${c.reference_image}` : c.reference_image} alt="" />
                    ) : (
                      <span className="scempty">
                        <ImageIcon size={18} strokeWidth={1.4} />
                        <span className="m">no keyframe yet · the Director renders one</span>
                      </span>
                    )}
                  </div>
                  <div className="scchips">
                    <span className="chip">
                      <Clock size={11} /> {runway?.duration ?? 5} sec
                    </span>
                    <span className="chip">
                      <RectangleVertical size={11} /> {ratioLabel(runway?.ratio)}
                    </span>
                    <span className="chip">
                      <Monitor size={11} /> {runway?.model ?? "gen4_turbo"}
                    </span>
                    <span className="spacer" />
                    <span className="m">{runway?.estimate_usd != null ? `~$${runway.estimate_usd.toFixed(2)} a clip` : ""}</span>
                  </div>
                  <div className="scprompt">
                    <div className="scphead">
                      <span className="m">prompt · shot 1</span>
                      <span className="spacer" />
                      <span className="m">{draft.length} chars</span>
                    </div>
                    <textarea
                      rows={7}
                      value={draft}
                      onChange={(e) => setDrafts((d) => ({ ...d, [c.id]: e.target.value }))}
                      placeholder="What happens in this shot…"
                      aria-label={`Prompt for ${c.title}`}
                    />
                    <div className="scpfoot">
                      {dirty ? (
                        <button
                          type="button"
                          className="btn pri"
                          disabled={busy[c.id]}
                          onClick={() =>
                            act(c, () => updateShotPrompt(c.id, 1, draft.trim()), "Prompt saved to the concept").then(() =>
                              setDrafts((d) => {
                                const next = { ...d };
                                delete next[c.id];
                                return next;
                              }),
                            )
                          }
                        >
                          Save prompt
                        </button>
                      ) : null}
                      {!c.archived ? (
                        <button
                          type="button"
                          className={`btn${c.picked ? "" : " pri"}`}
                          disabled={busy[c.id] || !!c.media_url}
                          onClick={() =>
                            act(c, () => pickConcept(c.id, !c.picked), c.picked ? "Unpicked" : `${c.n} is in the Queue — approving it there renders`)
                          }
                        >
                          <ListVideo strokeWidth={1.8} /> {c.media_url ? "Rendered" : c.picked ? "In the Queue" : "Send to Queue"}
                        </button>
                      ) : null}
                      <Link href={`/studio/flows?concept=${c.id}&shot=1`} className="btn">
                        <Workflow strokeWidth={1.6} /> Open in Director
                      </Link>
                    </div>
                  </div>
                </div>
              ) : null}

              <div className="scfoot" onClick={(e) => e.stopPropagation()}>
                {c.archived ? (
                  <button type="button" className="tag" disabled={busy[c.id]} onClick={() => act(c, () => archiveConcept(c.id, false), "Back on the board")}>
                    <Undo2 size={12} strokeWidth={1.6} /> Put back on the board
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      className="swipe no"
                      title="Not this one — take it off the board"
                      aria-label="Not this one — take it off the board"
                      disabled={busy[c.id]}
                      onClick={() => act(c, () => archiveConcept(c.id, true), "Archived — it still counts")}
                    >
                      <X size={16} strokeWidth={2} />
                    </button>
                    <button
                      type="button"
                      className={`swipe yes${c.picked ? " on" : ""}`}
                      title={c.picked ? "Picked — click to unpick" : "Pick this"}
                      aria-label={c.picked ? "Unpick this concept" : "Pick this concept"}
                      aria-pressed={c.picked}
                      disabled={busy[c.id]}
                      onClick={() => act(c, () => pickConcept(c.id, !c.picked))}
                    >
                      <Check size={16} strokeWidth={2.2} />
                    </button>
                  </>
                )}
                <span className="spacer" />
                <Link href={`/studio/flows?concept=${c.id}&shot=1`} className="go" style={{ padding: "10px 22px" }}>
                  Open in Director
                </Link>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
