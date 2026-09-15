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
  runScenes,
  waitForJob,
  type Asset,
  type AssetHit,
  type Capabilities,
} from "@/lib/studio-api";
import { useMentions } from "@/components/studio/mentions";
import { useShell } from "@/components/studio/shell";

type Attachment = { id: string; name: string; file: File; url: string };
type Option = { id: string; label: string; note?: string };
type GuideMessage = { role: "user" | "assistant"; content: string };
type Written = { conceptId: number | null; detail: string };
/* the rail's filters: real elements first; the studio's own generated
   stills are a shelf of their own rather than 69 identical plates
   drowning the seven things a person can @ */
type Filter = "elements" | Asset["category"];

const FILTERS: [Filter, string][] = [
  ["elements", "Elements"],
  ["location", "Rooms"],
  ["character", "Characters"],
  ["prop", "Props"],
  ["generated", "Generated"],
];

const IS_ELEMENT = (a: Asset) => a.category !== "generated";
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

const shortDate = (iso?: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

function Composer() {
  const { brand, toast } = useShell();
  const params = useSearchParams();
  const attachId = params.get("attach");
  const [idea, setIdea] = useState("");
  const [caps, setCaps] = useState<Capabilities>({});
  const [assets, setAssets] = useState<Asset[]>([]);
  const [filter, setFilter] = useState<Filter>("elements");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string[]>([]); // asset photo urls
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [note, setNote] = useState<string | null>(null);
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

  useEffect(() => {
    getCapabilities().then(setCaps).catch(() => setCaps({}));
    getAssets()
      .then((r) => {
        setAssets(r.items);
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

  async function send() {
    if (!canSend) return;
    setBusy(true);
    setProgress(0);
    setNote(null);
    setWritten(null);
    try {
      if (mode === "create") {
        const form = new FormData();
        form.append("idea", brief.trim() || idea.trim());
        if (brand) form.append("brand", brand);
        form.append("count", "1");
        if (brain) form.append("brain", brain);
        if (seconds) form.append("seconds", String(seconds));
        if (ratio) form.append("ratio", ratio);
        picked.forEach((u) => form.append("refs", u));
        attachments.forEach((a) => form.append("files", a.file, a.name));
        const started = await runScenes(form);
        setNote("Writing the scene…");
        const job = await waitForJob(started.job_id, (j) => {
          setProgress(j.progress || 0);
          setNote(j.detail || "Writing the scene…");
        });
        if (job.status === "done") {
          setProgress(1);
          setNote(null);
          setWritten({ conceptId: job.ref_id ?? null, detail: job.detail || "on the board" });
          toast("Scene written · it is on Pipeline to pick");
          setIdea("");
          announceQueueChange();
        } else {
          setNote(job.error || "That run did not finish.");
        }
      } else {
        const next: GuideMessage[] = [...thread, { role: "user", content: idea.trim() }];
        const asked = idea.trim();
        setThread(next);
        setIdea("");
        setChoices([]);
        const form = new FormData();
        form.append("conversation", JSON.stringify({ messages: next }));
        if (brand) form.append("brand", brand);
        form.append("guide_provider", "gemini");
        form.append("idea", asked);
        const res = await fetch(`${API_URL}/api/creative-guide`, {
          method: "POST",
          credentials: "include",
          body: form,
        });
        if (!res.ok) throw new Error(`The guide answered ${res.status}`);
        const started = (await res.json()) as { job_id: number };
        const job = await waitForJob(started.job_id, (j) => {
          setProgress(j.progress || 0);
          setNote(j.detail || "Considering your direction…");
        });
        const reply = (job as unknown as { reply?: { message: string; choices?: string[]; brief?: string } }).reply;
        if (job.status !== "done" || !reply) throw new Error(job.error || "The guide stopped.");
        setThread([...next, { role: "assistant", content: reply.message }]);
        setChoices(reply.choices ?? []);
        if (reply.brief) setBrief(reply.brief);
        setNote(reply.brief ? "Brief ready — switch to Create, or keep refining." : "Choose a direction or reply.");
      }
    } catch (e) {
      setNote(e instanceof Error ? e.message : "That did not go through.");
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

  const elements = useMemo(() => assets.filter(IS_ELEMENT), [assets]);
  const counts = useMemo(
    () => ({
      elements: elements.length,
      location: assets.filter((a) => a.category === "location").length,
      character: assets.filter((a) => a.category === "character").length,
      prop: assets.filter((a) => a.category === "prop").length,
      generated: assets.length - elements.length,
    }),
    [assets, elements],
  );
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const pool = filter === "elements" ? elements : assets.filter((a) => a.category === filter);
    const hit = needle
      ? pool.filter((a) => `${a.name} ${a.text || ""}`.toLowerCase().includes(needle))
      : pool;
    // things with frames first: an empty plate cannot be attached
    return [...hit].sort((a, b) => Number(!!b.photos.length) - Number(!!a.photos.length));
  }, [assets, elements, filter, query]);

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
                  <p key={i} className={`cmsg${m.role === "user" ? " me" : ""}`}>
                    {m.content}
                  </p>
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
                <span key={u} className="cattach" title={u} style={{ backgroundImage: `url(${API_URL}${u})` }}>
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

            {brief && mode === "create" ? (
              <div className="cbrief">
                <span className="m" style={{ fontSize: 8.5, display: "block", marginBottom: 6 }}>
                  Brief from the guide · editable · this is what Create writes from
                </span>
                <textarea value={brief} onChange={(e) => setBrief(e.target.value)} rows={5} />
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
                  heading="Which model writes"
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
              <span className={`m cnote${note && !busy && !written ? " said" : ""}`}>
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
          <Link href="/studio/elements" className="cat">
            Elements ↗
          </Link>
        </div>
        {shown.length ? (
          <div className="hrail">
            {shown.map((a) => {
              const frames = a.photos.length;
              const on = a.photos.slice(0, FRAMES_PER_ASSET).some((u) => picked.includes(u));
              const generated = a.category === "generated";
              return (
                <button
                  type="button"
                  key={a.id}
                  className={`plate${frames ? "" : " empty"}`}
                  aria-pressed={on}
                  title={
                    !frames
                      ? "No frames yet — add photos on Elements"
                      : on
                        ? "Attached — click to detach"
                        : "Attach as a reference"
                  }
                  style={a.poster ? { backgroundImage: `url(${API_URL}${a.poster})` } : undefined}
                  onClick={() => togglePlate(a)}
                >
                  {on ? <span className="pick">✓</span> : null}
                  {!frames ? <ImageOff className="pempty" strokeWidth={1.2} aria-hidden /> : null}
                  <span className="pn">
                    <b>{generated ? "Keyframe" : a.name}</b>
                    <span>
                      {generated
                        ? `${shortDate(a.created_at)} · ${String(a.meta?.provider ?? "generated")}`
                        : frames
                          ? `${a.category} · ${frames} frame${frames === 1 ? "" : "s"}`
                          : `${a.category} · no frames yet`}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="stateline">
            {assets.length
              ? query
                ? `Nothing matches “${query}”`
                : "Nothing on this shelf yet"
              : "No assets yet — add a character, room or prop on Elements"}
          </div>
        )}
      </div>
    </section>
  );
}
