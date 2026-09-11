"use client";

/* Studio — where an idea is typed, and the only place (2026-09-11,
   ported from the Vite composer onto the Next shell). One box, a count
   of 1–4 takes, references from uploads or the asset bank, and Create
   posts multipart to /api/scenes/run — the same route the Jinja
   composer posts. Create WRITES concepts and stops on the board:
   enhancing, keyframing and rendering are the Director's job.

   Guide mode (talk the idea through first) shows only when the server
   reports the creative_guide capability; on this branch it does not
   exist yet, so Create is the primary action rather than a button that
   404s. The model / length / frame pills likewise appear only when
   their routes answer. */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  AtSign,
  Brain,
  Clock,
  Image as ImageIcon,
  MessageSquare,
  Play,
  Plus,
  RectangleVertical,
  Sparkles,
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

const COUNTS = [1, 2, 3, 4];

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

export default function StudioPage() {
  const { brand, toast } = useShell();
  const [idea, setIdea] = useState("");
  const [count, setCount] = useState(4);
  const [caps, setCaps] = useState<Capabilities>({});
  const [assets, setAssets] = useState<Asset[]>([]);
  const [filter, setFilter] = useState<"all" | Asset["category"]>("all");
  const [picked, setPicked] = useState<string[]>([]); // asset photo urls
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
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

  useEffect(() => {
    getCapabilities().then(setCaps).catch(() => setCaps({}));
    getAssets()
      .then((r) => setAssets(r.items))
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
  }, []);

  // Guide only when the server says the route is there; otherwise the
  // primary action is Create rather than a button that 404s
  const guideReady = caps.creative_guide === true;
  const mode: "guide" | "create" = guideReady ? wantMode : "create";

  // @Michael in the box attaches his frames as references
  const attachAsset = (hit: AssetHit) => {
    const asset = assets.find((a) => a.name === hit.name && a.category === hit.category);
    const urls = asset ? asset.photos.slice(0, 3) : hit.thumb ? [hit.thumb] : [];
    if (!urls.length) {
      toast(`${hit.name} has no photos on file — add some on Elements`, "err");
      return;
    }
    setPicked((was) => [...new Set([...was, ...urls])]);
    toast(`${hit.name} attached · ${urls.length} frame${urls.length === 1 ? "" : "s"}`);
  };
  const mentions = useMentions(textarea, idea, setIdea, attachAsset);

  const canSend = !busy && (mode === "create" ? !!(idea.trim() || brief.trim()) : !!idea.trim());

  async function send() {
    if (!canSend) return;
    setBusy(true);
    setNote(null);
    try {
      if (mode === "create") {
        const form = new FormData();
        form.append("idea", brief.trim() || idea.trim());
        if (brand) form.append("brand", brand);
        form.append("count", String(count));
        if (brain) form.append("brain", brain);
        if (seconds) form.append("seconds", String(seconds));
        if (ratio) form.append("ratio", ratio);
        picked.forEach((u) => form.append("refs", u));
        attachments.forEach((a) => form.append("files", a.file, a.name));
        const started = await runScenes(form);
        setNote("Writing — the takes appear on Pipeline as they land…");
        const job = await waitForJob(started.job_id, (j) => setNote(j.detail || "Writing…"));
        if (job.status === "done") {
          setNote(`Done — ${job.detail || "on the board"}`);
          toast(`${count} take${count === 1 ? "" : "s"} written · open Pipeline to pick`);
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
        const job = await waitForJob(started.job_id, (j) =>
          setNote(j.detail || "Considering your direction…"),
        );
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

  const attach = (files: FileList | null) => {
    if (!files) return;
    setAttachments((was) => [
      ...was,
      ...Array.from(files).map((f) => ({
        id: crypto.randomUUID(),
        name: f.name,
        file: f,
        url: URL.createObjectURL(f),
      })),
    ]);
  };

  const shown = assets.filter((a) => filter === "all" || a.category === filter);
  const counts = {
    all: assets.length,
    character: assets.filter((a) => a.category === "character").length,
    location: assets.filter((a) => a.category === "location").length,
    prop: assets.filter((a) => a.category === "prop").length,
  };
  const togglePlate = (a: Asset) => {
    const urls = a.photos.slice(0, 3);
    const on = urls.some((u) => picked.includes(u));
    setPicked((was) => (on ? was.filter((u) => !urls.includes(u)) : [...new Set([...was, ...urls])]));
  };

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className="hero">
        <h1>
          What do you
          <br />
          want to create?
        </h1>
        <div className="stack">
          <div className={`glass cbox${idea ? " awake" : ""}`}>
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
                  <button
                    type="button"
                    aria-label={`Remove ${a.name}`}
                    onClick={() => setAttachments((w) => w.filter((x) => x.id !== a.id))}
                  >
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
            </div>
            <input ref={fileInput} type="file" accept="image/*" multiple hidden onChange={(e) => attach(e.target.files)} />

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

            <div className="cfoot">
              {guideReady ? (
                <PillMenu
                  heading="Send does"
                  value={mode}
                  onChange={(id) => setMode(id as "guide" | "create")}
                  options={[
                    { id: "guide", label: "Guide", note: "Talk the idea through first." },
                    { id: "create", label: "Create", note: "Write scenes from what is in the box." },
                  ]}
                  trigger={(open) => (
                    <button type="button" className="pill chosen" aria-expanded={open}>
                      {mode === "create" ? <Play strokeWidth={1.6} /> : <MessageSquare strokeWidth={1.6} />}
                      {mode === "create" ? "Create" : "Guide"}
                    </button>
                  )}
                />
              ) : null}
              <button type="button" className="pill" title="Add media" onClick={() => fileInput.current?.click()}>
                <Plus strokeWidth={1.6} />
              </button>
              <span className="m cnote">{note ?? "references ride into every node — prompt, keyframe and clip"}</span>
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
              <PillMenu
                heading="How many takes"
                value={String(count)}
                onChange={(v) => setCount(Number(v))}
                options={COUNTS.map((n) => ({ id: String(n), label: `${n} concept${n === 1 ? "" : "s"}` }))}
                end
                trigger={(open) => (
                  <button type="button" className="pill" aria-expanded={open}>
                    {count} concept{count === 1 ? "" : "s"}
                  </button>
                )}
              />
              <button type="button" className="go" disabled={!canSend} onClick={() => void send()}>
                <Sparkles strokeWidth={2} />
                {busy ? "Writing…" : mode === "create" ? "Create" : "Send"}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="row">
        <div className="rowfilters">
          {(
            [
              ["all", "All"],
              ["location", "Rooms"],
              ["character", "Characters"],
              ["prop", "Props"],
            ] as const
          ).map(([id, label]) => (
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
          <span className="spacer" />
          <Link href="/studio/elements" className="cat">
            Elements ↗
          </Link>
        </div>
        {shown.length ? (
          <div className="hrail">
            {shown.map((a) => {
              const on = a.photos.slice(0, 3).some((u) => picked.includes(u));
              return (
                <button
                  type="button"
                  key={a.id}
                  className="plate"
                  aria-pressed={on}
                  title={on ? "Attached — click to detach" : "Attach as a reference"}
                  style={a.poster ? { backgroundImage: `url(${API_URL}${a.poster})` } : undefined}
                  onClick={() => togglePlate(a)}
                >
                  {on ? <span className="pick">✓</span> : null}
                  <span className="pn">
                    <b>{a.name}</b>
                    <span>
                      {a.category} · {a.photos.length} frame{a.photos.length === 1 ? "" : "s"}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="stateline">No assets yet — add a character, room or prop on Elements</div>
        )}
      </div>
    </section>
  );
}
