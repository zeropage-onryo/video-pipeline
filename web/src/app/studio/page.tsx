"use client";

/* Studio — where an idea is typed, and the only place (2026-09-11,
   ported from the Vite composer onto the Next shell). One box,
   references from uploads or the asset bank, and Create posts multipart
   to /api/scenes/run — the same route the Jinja composer posts. Create
   WRITES concepts and stops on the board: enhancing, keyframing and
   rendering are the Director's job.

   ONE Create writes ONE scene (2026-09-10, Mike's call; the server
   enforces it as SCENE_COUNT_MAX = 1). The 1–4 takes pill this page
   shipped with promised four and delivered one, so it is gone
   (2026-09-15) and the result card names the scene that was written.

   Guide mode (talk the idea through first) shows only when the server
   reports the creative_guide capability, so Create is the primary action
   rather than a button that 404s. The model / length / frame pills
   likewise appear only when their routes answer. */
import Link from "next/link";
import { Suspense, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useSearchParams } from "next/navigation";
import {
  AtSign,
  Brain,
  Clapperboard,
  Clock,
  Ellipsis,
  Image as ImageIcon,
  ImageOff,
  MessageSquare,
  Play,
  Plus,
  RectangleVertical,
  Search,
  Sparkles,
  Workflow,
  X,
} from "lucide-react";
import { API_URL, apiFetch } from "@/lib/api";
import {
  announceQueueChange,
  getAssets,
  getCapabilities,
  runCreativeGuide,
  runScenes,
  waitForJob,
  type Asset,
  type AssetHit,
  type Capabilities,
  runGuideAction,
  type GuideProposal,
  type GuideReply,
} from "@/lib/studio-api";
import { useMentions } from "@/components/studio/mentions";
import { useShell } from "@/components/studio/shell";
import { AddElement } from "@/components/studio/add-element";
import { ElementSheet } from "@/components/studio/element-sheet";
import { ELEMENT_KINDS, displayPhoto, drawable, elementKind, isElement, kindLabel, type ElementKind } from "@/lib/elements";

type Attachment = { id: string; name: string; file: File; url: string };
type Option = { id: string; label: string; note?: string };
/* `failed` marks a turn the guide never answered. It is drawn on the
   bubble itself and dropped from the next turn's conversation, so a
   retry neither repeats it on screen nor sends it twice. */
type GuideMessage = {
  role: "user" | "assistant";
  content: string;
  failed?: boolean;
  /** which board tools the guide looked at before this answer */
  looked?: string[];
  /** a write the guide proposed; drawn as a confirm card until decided */
  proposal?: GuideProposal | null;
  decided?: "done" | "skipped";
};
type Written = { conceptId: number | null; detail: string };
/* the shelf under the box is ELEMENTS only -- the characters, props,
   products and places a person created to @ in a prompt (Mike's call,
   2026-09-15). Blank until one exists; the Assets wall's generated
   stills never appear here. */
type Filter = "all" | ElementKind;

const FILTERS: [Filter, string][] = [
  ["all", "All elements"],
  ...ELEMENT_KINDS.map(({ id, label }) => [id, label] as [Filter, string]),
];

const FRAMES_PER_ASSET = 3;

function PillMenu({
  heading,
  options,
  value,
  onChange,
  trigger,
  end,
}: {
  heading: string;
  options: Option[];
  value: string;
  onChange: (id: string) => void;
  trigger: (open: boolean) => React.ReactNode;
  end?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", off);
    return () => document.removeEventListener("pointerdown", off);
  }, [open]);
  return (
    <span className="pillwrap" ref={box}>
      <span onClick={() => setOpen((v) => !v)}>{trigger(open)}</span>
      {open ? (
        <span className={`pillmenu${end ? " end" : ""}`} role="menu">
          <span className="m">{heading}</span>
          {options.map((o) => (
            <button
              type="button"
              key={o.id}
              aria-current={o.id === value ? "true" : undefined}
              onClick={() => {
                onChange(o.id);
                setOpen(false);
              }}
            >
              {o.label}
              {o.note ? <small>{o.note}</small> : null}
            </button>
          ))}
        </span>
      ) : null}
    </span>
  );
}

/* useSearchParams needs a Suspense boundary above it for the static
   shell Next prerenders; the composer itself is the client page */
export default function StudioPage() {
  return (
    <Suspense fallback={null}>
      <Composer />
    </Suspense>
  );
}

const imageFiles = (list: FileList | File[] | null | undefined) =>
  Array.from(list ?? []).filter((f) => f.type.startsWith("image/"));

function Composer() {
  const { brand, toast } = useShell();
  const params = useSearchParams();
  const attachId = params.get("attach");
  // An idea typed into the landing page's hero arrives as ?spark= and the
  // composer opens already carrying it -- the sentence a visitor wrote is
  // the one thing on that page that must not be thrown away.
  const [idea, setIdea] = useState(params.get("spark") ?? "");
  const [caps, setCaps] = useState<Capabilities>({});
  const [assets, setAssets] = useState<Asset[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<Asset | null>(null);
  const [picked, setPicked] = useState<string[]>([]); // asset photo urls
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  // Two kinds of note, and they used to render identically: progress
  // ("Writing…") and failure. A failure in the hint's own slot, small
  // caps and ellipsised, is how a 403 on every Guide turn read as the
  // composer saying nothing at all (2026-09-14). `say(text, true)`
  // marks the failing kind -- it turns the line signal-red and also
  // raises the shell's error toast, which is the loud surface.
  const [note, setNote] = useState<string | null>(null);
  const [noteBad, setNoteBad] = useState(false);
  const [progress, setProgress] = useState(0);
  const [written, setWritten] = useState<Written | null>(null);
  const [dragging, setDragging] = useState(false);
  const [wantMode, setMode] = useState<"guide" | "create">("guide");
  const [thread, setThread] = useState<GuideMessage[]>([]);
  const [choices, setChoices] = useState<string[]>([]);
  const [brief, setBrief] = useState("");
  // the optional pills: each shows only when its route answers
  const [brains, setBrains] = useState<Option[]>([]);
  const [brain, setBrain] = useState("");
  const [lengths, setLengths] = useState<number[]>([]);
  const [seconds, setSeconds] = useState(0);
  const [ratios, setRatios] = useState<Option[]>([]);
  const [ratio, setRatio] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const dragDepth = useRef(0);

  const loadAssets = () =>
    getAssets()
      .then((r) => setAssets(r.items))
      .catch(() => setAssets([]));

  useEffect(() => {
    getCapabilities().then(setCaps).catch(() => setCaps({}));
    // the picker lists elements only; a render handed over from the
    // Assets wall ("Use in a shot") needs the wider scope to resolve
    getAssets(undefined, attachId?.startsWith("generated-") ? "all" : "elements")
      .then((r) => {
        setAssets(r.items.filter((a) => (a.category as string) !== "generated"));
        // "Use in a shot" on Assets lands here with the asset attached
        const hit = attachId ? r.items.find((a) => a.id === attachId) : null;
        if (hit) setPicked(hit.photos.slice(0, FRAMES_PER_ASSET));
      })
      .catch(() => setAssets([]));
    apiFetch<{ brains: { id: string; label: string; note: string }[]; default: string }>("/brains")
      .then((r) => {
        setBrains(r.brains.map((b) => ({ id: b.id, label: b.label, note: b.note })));
        setBrain(r.default);
      })
      .catch(() => setBrains([]));
    apiFetch<{ choices: number[]; default: number }>("/scene-lengths")
      .then((r) => {
        setLengths(r.choices);
        setSeconds(r.default);
      })
      .catch(() => setLengths([]));
    apiFetch<{ ratios: { id: string; label: string; size: string }[]; default: string }>("/render-choices")
      .then((r) => {
        setRatios(r.ratios.map((x) => ({ id: x.id, label: x.label, note: x.size })));
        setRatio(r.default);
      })
      .catch(() => setRatios([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // object URLs for uploads are revoked when the composer unmounts
  useEffect(() => {
    return () => attachments.forEach((a) => URL.revokeObjectURL(a.url));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Guide only when the server says the route is there; otherwise the
  // primary action is Create rather than a button that 404s
  const guideReady = caps.creative_guide === true;
  const mode: "guide" | "create" = guideReady ? wantMode : "create";

  // @Michael in the box attaches his frames as references
  const attachAsset = (hit: AssetHit) => {
    const asset = assets.find((a) => a.name === hit.name && a.category === hit.category);
    const urls = asset ? asset.photos.slice(0, FRAMES_PER_ASSET) : hit.thumb ? [hit.thumb] : [];
    if (!urls.length) {
      toast(`${hit.name} has no photos on file — add some on Elements`, "err");
      return;
    }
    setPicked((was) => [...new Set([...was, ...urls])]);
    toast(`${hit.name} attached · ${urls.length} frame${urls.length === 1 ? "" : "s"}`);
  };
  const mentions = useMentions(textarea, idea, setIdea, attachAsset);

  const canSend = !busy && (mode === "create" ? !!(idea.trim() || brief.trim()) : !!idea.trim());
  const referenceCount = picked.length + attachments.length;

  // The references on screen, in the two field names the API reads
  // (app/api.py:_collect_refs): `files` for uploads, `asset_photos` for
  // picks out of the asset bank. ONE helper for both buttons, the way
  // the vanilla composer's collectRunForm is -- when the Guide built its
  // own FormData it sent neither, so the model was told "0 reference
  // images supplied" over two visible thumbnails; and Create sent the
  // picks as `refs`, a field nothing server-side has ever read, so a
  // @Michael pick reached the scene only when it was also a file
  // (2026-09-18).
  const appendReferences = (form: FormData) => {
    attachments.forEach((a) => form.append("files", a.file, a.name));
    picked.forEach((u) => form.append("asset_photos", u));
  };

  const say = (text: string | null, bad = false) => {
    setNote(text);
    setNoteBad(bad);
    if (bad && text) toast(text, "err");
  };

  async function send() {
    if (!canSend) return;
    setBusy(true);
    setProgress(0);
    setWritten(null);
    say(null);
    let asking: GuideMessage[] | null = null;
    try {
      if (mode === "create") {
        const form = new FormData();
        form.append("idea", brief.trim() || idea.trim());
        if (brand) form.append("brand", brand);
        form.append("count", "1");
        if (brain) form.append("brain", brain);
        if (seconds) form.append("seconds", String(seconds));
        if (ratio) form.append("ratio", ratio);
        appendReferences(form);
        const started = await runScenes(form);
        say("Writing the scene…");
        const job = await waitForJob(started.job_id, (j) => {
          setProgress(j.progress || 0);
          say(j.detail || "Writing the scene…");
        });
        if (job.status === "done") {
          setProgress(1);
          say(null);
          setWritten({ conceptId: job.ref_id ?? null, detail: job.detail || "on the board" });
          toast("Scene written · it is on Pipeline to pick");
          setIdea("");
          announceQueueChange();
        } else {
          say(job.error || "That run did not finish.", true);
        }
      } else {
        const next: GuideMessage[] = [
          ...thread.filter((m) => !m.failed),
          { role: "user", content: idea.trim() },
        ];
        const asked = idea.trim();
        asking = next;
        setThread(next);
        setIdea("");
        setChoices([]);
        const form = new FormData();
        form.append("conversation", JSON.stringify({ messages: next }));
        if (brand) form.append("brand", brand);
        form.append("guide_provider", "gemini");
        form.append("idea", asked);
        // The same Fast / Reasoning pill Create sends. Without it the
        // Guide answered every turn on the reasoning tier -- ~1.5c a
        // message for "which direction?" -- and the pill did nothing
        // in this mode. Server clamps it; absent means Fast.
        if (brain) form.append("brain", brain);
        // The same photos a Create would carry: the guide grounds on them
        // (scene_chain.ground) and the model is shown them, so it can
        // answer about a face instead of asking where the photos are.
        appendReferences(form);
        // runCreativeGuide, never a bare fetch: the route is behind
        // mutation_header and a call without GUARDED_HEADERS is refused
        // 403 -- which lands in `note` and reads as the guide saying
        // nothing at all, since the thread and the box are already
        // cleared by then.
        const started = await runCreativeGuide(form);
        const job = await waitForJob(started.job_id, (j) => {
          setProgress(j.progress || 0);
          say(j.detail || "Considering your direction…");
        });
        const reply = (job as unknown as { reply?: GuideReply }).reply;
        if (job.status !== "done" || !reply) throw new Error(job.error || "The guide stopped.");
        setThread([
          ...next,
          {
            role: "assistant",
            content: reply.message,
            looked: (reply.tool_runs ?? []).filter((r) => r.ok).map((r) => r.tool),
            proposal: reply.proposal ?? null,
          },
        ]);
        setChoices(reply.choices ?? []);
        if (reply.brief) setBrief(reply.brief);
        say(
          reply.proposal
            ? "Confirm on the card, or skip it."
            : reply.brief
              ? "Brief ready below — keep refining, or Create from it."
              : "Choose a direction or reply.",
        );
      }
    } catch (e) {
      // The thread and the box were cleared before the request went out,
      // so a failed turn must say so ON its own bubble, and hand the
      // words back for a retry.
      if (asking) {
        const last = asking[asking.length - 1];
        setThread([...asking.slice(0, -1), { ...last, failed: true }]);
        setIdea((now) => now || last.content);
      }
      say(e instanceof Error ? e.message : "That did not go through.", true);
    } finally {
      setBusy(false);
    }
  }

  /* The confirm card. Nothing has run until this: the guide's turn
     ended on the proposal, and the click is what posts it. The result
     goes into the thread as the guide's own words, so the next turn's
     conversation says what was banked. */
  async function decide(i: number, yes: boolean) {
    const entry = thread[i];
    if (!entry?.proposal || entry.decided || busy) return;
    if (!yes) {
      setThread((t) => t.map((m, j) => (j === i ? { ...m, decided: "skipped" } : m)));
      return;
    }
    setBusy(true);
    try {
      const done = await runGuideAction(entry.proposal);
      setThread((t) => [
        ...t.map((m, j) => (j === i ? { ...m, decided: "done" as const } : m)),
        { role: "assistant", content: `Done — ${done.result}` },
      ]);
      say("Banked.");
    } catch (e) {
      say(e instanceof Error ? e.message : "That did not go through.", true);
    } finally {
      setBusy(false);
    }
  }

  const attach = (files: FileList | File[] | null | undefined) => {
    const images = imageFiles(files);
    if (!images.length) return;
    setAttachments((was) => [
      ...was,
      ...images.map((f) => ({
        id: crypto.randomUUID(),
        name: f.name,
        file: f,
        url: URL.createObjectURL(f),
      })),
    ]);
    toast(`${images.length} image${images.length === 1 ? "" : "s"} attached as reference`);
  };
  const removeAttachment = (id: string) =>
    setAttachments((w) => {
      const gone = w.find((x) => x.id === id);
      if (gone) URL.revokeObjectURL(gone.url);
      return w.filter((x) => x.id !== id);
    });

  /* drop anywhere on the box; the depth counter keeps the highlight
     steady while the cursor crosses the box's own children */
  const onDragEnter = (e: DragEvent) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    dragDepth.current += 1;
    setDragging(true);
  };
  const onDragLeave = () => {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    attach(e.dataTransfer.files);
  };

  const elements = useMemo(() => assets.filter(isElement), [assets]);
  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: elements.length, character: 0, prop: 0, product: 0, place: 0 };
    for (const a of elements) {
      const k = elementKind(a);
      if (k) c[k] += 1;
    }
    return c;
  }, [elements]);
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const pool = filter === "all" ? elements : elements.filter((a) => elementKind(a) === filter);
    const hit = needle
      ? pool.filter((a) => `${a.name} ${a.text || ""}`.toLowerCase().includes(needle))
      : pool;
    // things with frames first: an empty plate cannot be attached
    return [...hit].sort((a, b) => Number(!!b.photos.length) - Number(!!a.photos.length));
  }, [elements, filter, query]);

  const togglePlate = (a: Asset) => {
    const urls = a.photos.slice(0, FRAMES_PER_ASSET);
    if (!urls.length) {
      toast(`${a.name} has no frames yet — add photos on Elements`, "err");
      return;
    }
    const on = urls.some((u) => picked.includes(u));
    setPicked((was) => (on ? was.filter((u) => !urls.includes(u)) : [...new Set([...was, ...urls])]));
  };

  const modeSwitch = guideReady ? (
    <span className="cmode" role="radiogroup" aria-label="What Send does">
      <button
        type="button"
        role="radio"
        aria-checked={mode === "guide"}
        title="Talk the idea through first"
        onClick={() => setMode("guide")}
      >
        <MessageSquare strokeWidth={1.6} /> Guide
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={mode === "create"}
        title="Write the scene from what is in the box"
        onClick={() => setMode("create")}
      >
        <Play strokeWidth={1.6} /> Create
      </button>
    </span>
  ) : null;

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className="hero">
        <h1>
          What do you
          <br />
          want to create?
        </h1>
        <div className="stack">
          <div
            className={`glass cbox${idea ? " awake" : ""}${dragging ? " drop" : ""}${busy ? " busy" : ""}`}
            onDragEnter={onDragEnter}
            onDragOver={(e) => e.preventDefault()}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            {busy ? (
              <span
                className="cprogress"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={1}
                aria-valuenow={progress}
                style={{ width: `${Math.max(6, Math.round(progress * 100))}%` }}
              />
            ) : null}
            {dragging ? (
              <span className="cdrop" aria-hidden>
                <ImageIcon strokeWidth={1.5} />
                Drop to attach as a reference
              </span>
            ) : null}

            {thread.length && mode === "guide" ? (
              <div className="cthread">
                {thread.map((m, i) => (
                  <div key={i} className="cturn">
                    {m.looked?.length ? (
                      <span className="clooked">looked at {m.looked.join(", ")}</span>
                    ) : null}
                    <p className={`cmsg${m.role === "user" ? " me" : ""}${m.failed ? " failed" : ""}`}>
                      {m.content}
                      {m.failed ? <span className="cmsg-failed">Not sent — try again</span> : null}
                    </p>
                    {m.proposal ? (
                      <div className={`ccard${m.decided ? ` ${m.decided}` : ""}`}>
                        <b>{m.proposal.label}</b>
                        <dl>
                          {Object.entries(m.proposal.args).map(([k, v]) => (
                            <div key={k}>
                              <dt>{k}</dt>
                              <dd>{String(v)}</dd>
                            </div>
                          ))}
                        </dl>
                        {m.decided ? (
                          <span className="ccard-state">{m.decided === "done" ? "Done" : "Skipped"}</span>
                        ) : (
                          <div className="ccard-actions">
                            <button type="button" className="yes" disabled={busy} onClick={() => decide(i, true)}>
                              Confirm
                            </button>
                            <button type="button" disabled={busy} onClick={() => decide(i, false)}>
                              Skip
                            </button>
                          </div>
                        )}
                      </div>
                    ) : null}
                  </div>
                ))}
                {choices.length ? (
                  <div className="cchoices">
                    {choices.map((c) => (
                      <button type="button" key={c} onClick={() => setIdea(c)}>
                        {c}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="cslots">
              <button type="button" className="cslot" onClick={() => fileInput.current?.click()}>
                <ImageIcon strokeWidth={1.5} />
                <b>
                  Add image
                  <br />
                  reference
                </b>
              </button>
              <button
                type="button"
                className="cslot"
                onClick={() => {
                  setIdea((v) => `${v}${v && !v.endsWith(" ") ? " " : ""}@`);
                  textarea.current?.focus();
                }}
              >
                <AtSign strokeWidth={1.5} />
                <b>
                  Consistent
                  <br />
                  element
                </b>
              </button>
              {attachments.map((a) => (
                <span key={a.id} className="cattach" title={a.name} style={{ backgroundImage: `url(${a.url})` }}>
                  <button type="button" aria-label={`Remove ${a.name}`} onClick={() => removeAttachment(a.id)}>
                    <X strokeWidth={2} />
                  </button>
                </span>
              ))}
              {picked.map((u) => (
                <span
                  key={u}
                  className={`cattach${drawable(u) ? "" : " raw"}`}
                  title={u}
                  data-ext={drawable(u) ? undefined : u.split(".").pop()?.split("?")[0]?.toUpperCase()}
                  style={drawable(u) ? { backgroundImage: `url(${API_URL}${u})` } : undefined}
                >
                  <button
                    type="button"
                    aria-label="Remove reference"
                    onClick={() => setPicked((w) => w.filter((x) => x !== u))}
                  >
                    <X strokeWidth={2} />
                  </button>
                </span>
              ))}
              {referenceCount > 1 ? (
                <button
                  type="button"
                  className="cclear"
                  onClick={() => {
                    attachments.forEach((a) => URL.revokeObjectURL(a.url));
                    setAttachments([]);
                    setPicked([]);
                  }}
                >
                  Clear {referenceCount}
                </button>
              ) : null}
            </div>
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) => {
                attach(e.target.files);
                e.target.value = "";
              }}
            />

            <div style={{ position: "relative" }}>
              <textarea
                ref={textarea}
                value={idea}
                maxLength={10000}
                rows={3}
                onChange={(e) => setIdea(e.target.value)}
                onKeyDown={(e) => {
                  if (mentions.onKeyDown(e)) return;
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void send();
                }}
                onPaste={(e) => {
                  const files = Array.from(e.clipboardData.items)
                    .filter((it) => it.kind === "file")
                    .map((it) => it.getAsFile())
                    .filter((f): f is File => !!f);
                  if (imageFiles(files).length) {
                    e.preventDefault();
                    attach(files);
                  }
                }}
                onBlur={mentions.onBlur}
                placeholder={
                  mode === "create"
                    ? "A rider suits up in a dark garage and something is already wrong… (@ to reference an element)"
                    : "Describe your video or ask for a direction. We'll work through the story, look and pacing…"
                }
                aria-label="Your idea"
              />
              {mentions.dropdown}
            </div>

            {brief ? (
              // The brief is shown in BOTH modes. It used to render only
              // in Create, so the guide's "the text block below is your
              // paste-ready prompt" pointed at an empty idea box while
              // the brief sat in state behind the mode pill (2026-09-18).
              <div className="cbrief">
                <span className="m" style={{ fontSize: 8.5, display: "block", marginBottom: 6 }}>
                  {mode === "create"
                    ? "Brief from the guide · editable · this is what Create writes from"
                    : "Brief from the guide · editable · Create writes from this, not from the box"}
                </span>
                <textarea value={brief} onChange={(e) => setBrief(e.target.value)} rows={5} />
                {mode === "guide" ? (
                  <button type="button" className="pill chosen cbrief-go" onClick={() => setMode("create")}>
                    <Play strokeWidth={1.6} />
                    Create from this brief
                  </button>
                ) : null}
              </div>
            ) : null}

            {written ? (
              <div className="cresult" role="status">
                <span className="m">Scene written · {written.detail}</span>
                <span className="cresult-links">
                  <Link href="/studio/pipeline" className="pill chosen">
                    <Workflow strokeWidth={1.6} /> Pick on Pipeline
                  </Link>
                  {written.conceptId ? (
                    <Link href={`/studio/flows?concept=${written.conceptId}&shot=1`} className="pill">
                      <Clapperboard strokeWidth={1.6} /> Open in Director
                    </Link>
                  ) : null}
                  <button type="button" className="pill" onClick={() => setWritten(null)}>
                    Write another
                  </button>
                </span>
              </div>
            ) : null}

            <div className="cfoot">
              {modeSwitch}
              <button type="button" className="pill" title="Add media" onClick={() => fileInput.current?.click()}>
                <Plus strokeWidth={1.6} />
              </button>
              <span className="spacer" />
              {brains.length ? (
                <PillMenu
                  heading={mode === "guide" ? "Which model answers" : "Which model writes"}
                  value={brain}
                  onChange={setBrain}
                  options={brains}
                  end
                  trigger={(open) => (
                    <button type="button" className="pill" aria-expanded={open}>
                      <Brain strokeWidth={1.6} />
                      {brains.find((b) => b.id === brain)?.label ?? "Model"}
                    </button>
                  )}
                />
              ) : null}
              {lengths.length ? (
                <PillMenu
                  heading="How long the scene is"
                  value={String(seconds)}
                  onChange={(v) => setSeconds(Number(v))}
                  options={lengths.map((s) => ({ id: String(s), label: `${s} sec` }))}
                  end
                  trigger={(open) => (
                    <button type="button" className="pill" aria-expanded={open}>
                      <Clock strokeWidth={1.6} />
                      {seconds} sec
                    </button>
                  )}
                />
              ) : null}
              {ratios.length ? (
                <PillMenu
                  heading="Frame"
                  value={ratio}
                  onChange={setRatio}
                  options={ratios}
                  end
                  trigger={(open) => (
                    <button type="button" className="pill" aria-expanded={open}>
                      <RectangleVertical strokeWidth={1.6} />
                      {ratios.find((r) => r.id === ratio)?.label ?? "Frame"}
                    </button>
                  )}
                />
              ) : null}
              <button type="button" className="go" disabled={!canSend} onClick={() => void send()}>
                <Sparkles strokeWidth={2} />
                {busy ? (mode === "create" ? "Writing…" : "Thinking…") : mode === "create" ? "Create" : "Send"}
              </button>
            </div>
            <div className="cstatus">
              <span
                className={`m cnote${noteBad ? " bad" : note && !busy && !written ? " said" : ""}`}
                role={noteBad ? "alert" : undefined}
                title={noteBad && note ? note : undefined}
              >
                {note ??
                  (referenceCount
                    ? `${referenceCount} reference${referenceCount === 1 ? "" : "s"} attached · they ride into the prompt, the keyframe and the clip`
                    : "references ride into every node — prompt, keyframe and clip")}
              </span>
              <span className="m ckbd">
                <kbd>⌘</kbd>
                <kbd>⏎</kbd> {mode === "create" ? "create" : "send"}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="row">
        <div className="rowfilters">
          {FILTERS.map(([id, label]) => (
            <button
              type="button"
              key={id}
              className="cat"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
            >
              {label}
              <u>{counts[id]}</u>
            </button>
          ))}
          <label className="csearch">
            <Search strokeWidth={1.6} />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find an element…"
              aria-label="Find an element"
            />
          </label>
          <span className="spacer" />
          <button type="button" className="cat" onClick={() => setAdding(true)}>
            <Plus strokeWidth={2} size={12} style={{ marginRight: 6, verticalAlign: -2 }} />
            New element
          </button>
          <Link href="/studio/elements" className="cat">
            Elements ↗
          </Link>
        </div>
        {shown.length ? (
          <div className="hrail">
            {shown.map((a) => {
              const frames = a.photos.length;
              const on = a.photos.slice(0, FRAMES_PER_ASSET).some((u) => picked.includes(u));
              const kind = kindLabel(elementKind(a) ?? "prop");
              return (
                <div key={a.id} className={`plate${frames ? "" : " empty"}`} data-on={on ? "1" : undefined}>
                  <button
                    type="button"
                    className="pattach"
                    aria-pressed={on}
                    title={
                      !frames
                        ? "No frames yet — add photos on Elements"
                        : on
                          ? "Attached — click to detach"
                          : "Attach as a reference"
                    }
                    style={displayPhoto(a) ? { backgroundImage: `url(${API_URL}${displayPhoto(a)})` } : undefined}
                    onClick={() => togglePlate(a)}
                  >
                    {on ? <span className="pick">✓</span> : null}
                    {!frames ? <ImageOff className="pempty" strokeWidth={1.2} aria-hidden /> : null}
                    <span className="pn">
                      <b>{a.name}</b>
                      <span>{frames ? `${kind} · ${frames} frame${frames === 1 ? "" : "s"}` : `${kind} · no frames yet`}</span>
                    </span>
                  </button>
                  <button
                    type="button"
                    className="pmore"
                    title={`${a.name} · options`}
                    aria-label={`${a.name} options`}
                    onClick={() => setOpen(a)}
                  >
                    <Ellipsis strokeWidth={2} />
                  </button>
                </div>
              );
            })}
          </div>
        ) : elements.length ? (
          <div className="stateline">{query ? `Nothing matches “${query}”` : "Nothing of this kind yet"}</div>
        ) : (
          <div className="cblank">
            <AtSign strokeWidth={1.4} />
            <div>
              <b>No elements yet</b>
              <p>
                Create a character, prop, product or place and its frames become something you can @ in a
                prompt. They hold every shot to the same face, object or room.
              </p>
            </div>
            <button type="button" className="go" style={{ padding: "11px 22px" }} onClick={() => setAdding(true)}>
              <Plus strokeWidth={2} /> New element
            </button>
          </div>
        )}
      </div>

      {open ? (
        <ElementSheet
          asset={open}
          onClose={() => setOpen(null)}
          onAttach={(a) => {
            setOpen(null);
            const urls = a.photos.slice(0, FRAMES_PER_ASSET);
            setPicked((was) => [...new Set([...was, ...urls])]);
            toast(`${a.name} attached · ${urls.length} frame${urls.length === 1 ? "" : "s"}`);
          }}
          onDeleted={(a) => {
            setOpen(null);
            setPicked((was) => was.filter((u) => !a.photos.includes(u)));
            toast(`${a.name} deleted`);
            void loadAssets();
          }}
        />
      ) : null}

      {adding ? (
        <AddElement
          title="New element"
          onClose={() => setAdding(false)}
          onSaved={(name, photos) => {
            setAdding(false);
            toast(`${name} saved · ${photos} photo${photos === 1 ? "" : "s"} · teaching the assets shelf`);
            void loadAssets();
          }}
        />
      ) : null}
    </section>
  );
}
