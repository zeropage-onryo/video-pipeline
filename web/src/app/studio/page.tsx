"use client";

/* Studio — where an idea is typed, and the only place (2026-09-11,
   ported from the Vite composer onto the Next shell). One box,
   references from uploads or the asset bank, and a VIDEO send posts
   multipart to /api/scenes/run — the same route the Jinja composer posts.
   Create WRITES concepts and stops on the board: enhancing, keyframing
   and rendering are the Director's job.

   ONE Create writes ONE scene (2026-09-10, Mike's call; the server
   enforces it as SCENE_COUNT_MAX = 1). The 1–4 takes pill this page
   shipped with promised four and delivered one, so it is gone
   (2026-09-15) and the result names the scene that was written.

   Guide mode (talk the idea through first) shows only when the server
   reports the creative_guide capability, so Create is the primary action
   rather than a button that 404s. The model / length / frame pills
   likewise appear only when their routes answer.

   NOTHING IN THE BOX IS THIS PAGE'S TO LOSE (2026-10-02). The Guide
   thread, the idea, the brief, the references and what every send made
   are the studio's: the thread is the same one the assistant pill talks
   in (components/studio/assistant-thread.tsx, saved to the server as the
   open project), the box is its `draft`, and an upload is saved to the
   reference bin the moment it is dropped (POST /api/refs/upload) so what
   the draft remembers is a URL that resolves on every machine. Leaving
   and coming back -- or opening the pill on another page -- picks up
   exactly where the talk was.

   THE LOOK IS THE "ZPF COMPOSER DIRECTIONS" MOCK (2026-10-02, Mike:
   "create a similar look to the images shown in our mock design"). One
   centred box under "What are we making?", the settings as one line, a
   red round send; a result becomes tiles above a docked box; `/` opens
   commands; a drop covers the box; a running job can be stopped.

   THE BOX IS THE CONVERSATION, AND READY IS THE HAND-OFF (2026-10-03,
   Mike, from the live studio: "get rid of the create mode in there and
   only have a button ... when we're ready to send it to concept,
   director, or approve render"). There is no Create mode and no
   Image | Video switch any more: every send is a Guide turn, and the
   Guide develops the idea into an editable brief. The READY menu beside
   send is the only door out of the talk, and each item is one existing
   step: WRITE THE SCENE (one concept through /api/scenes/run, from the
   brief when there is one, else the box -- it lands on Pipeline), DRAW A
   STILL (one Nano Banana still through /api/generate/run), OPEN IN
   DIRECTOR (the last scene written here) and SEND TO QUEUE (picks that
   scene; approving in Queue is still the one click that spends). Each
   hand-off is saved on its turn (lib/composer.ts `Made`), so a still
   drawn here survives a trip to Pipeline, and a job left running is
   picked up again on return (its job id is on the turn). */
import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowUp,
  ArrowUpFromLine,
  AtSign,
  ChevronDown,
  Clapperboard,
  Ellipsis,
  ImageOff,
  ImagePlus,
  ListVideo,
  Paperclip,
  Play,
  Plus,
  Search,
  X,
} from "lucide-react";
import { API_URL, apiFetch } from "@/lib/api";
import {
  announceBalanceChange,
  announceQueueChange,
  cancelJob,
  getAssets,
  getCapabilities,
  getConceptDetail,
  getPresets,
  getProject,
  pickConcept,
  recallActiveProject,
  rememberActiveProject,
  runCreativeGuide,
  runGuideAction,
  runImage,
  runScenes,
  uploadRefs,
  waitForJob,
  type Asset,
  type AssetHit,
  type Capabilities,
  type GuideReply,
  type Job,
  type Preset,
  type Project,
} from "@/lib/studio-api";
import { useMentions } from "@/components/studio/mentions";
import { useShell } from "@/components/studio/shell";
import { useAssistantThread } from "@/components/studio/assistant-thread";
import { AddElement } from "@/components/studio/add-element";
import { DurationPill, type SceneLengths } from "@/components/studio/duration-pill";
import { ElementSheet } from "@/components/studio/element-sheet";
import { ELEMENT_KINDS, displayPhoto, drawable, elementKind, isElement, kindLabel, type ElementKind } from "@/lib/elements";
import {
  FILL_EVENT,
  NEW_SESSION_EVENT,
  keepReferences,
  takePendingFill,
  type ContactSheet,
  type ElementMade,
  type Turn,
} from "@/lib/assistant";
import { keepersOf } from "@/components/studio/contact-sheet";
import {
  BASE_COMMANDS,
  IMAGE_ASPECTS,
  matchCommands,
  mediaSrc,
  newMadeId,
  pollJob,
  type Made,
  type Output,
  type SlashCommand,
} from "@/lib/composer";
import { ComposerStream, type Live } from "@/components/studio/composer/turns";
import { SlashMenu } from "@/components/studio/composer/slash-menu";
import "@/components/studio/composer/composer.css";

/* an upload on its way to the bin: drawn from its object URL until the
   server answers with the URL the draft keeps */
type Pending = { id: string; name: string; url: string };
type Option = { id: string; label: string; note?: string };
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
const EASE = [0.22, 0.61, 0.36, 1] as const;

/* one of the settings in the toolbar's line: a word, a menu under it */
function OptMenu({
  heading,
  options,
  value,
  onChange,
  label,
  chevron,
}: {
  heading: string;
  options: Option[];
  value: string;
  onChange: (id: string) => void;
  label: string;
  chevron?: boolean;
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
      <button type="button" className="zc-opt" aria-expanded={open} title={heading} onClick={() => setOpen((v) => !v)}>
        {label}
        {chevron ? <ChevronDown strokeWidth={2} /> : null}
      </button>
      {open ? (
        <span className="pillmenu" role="menu">
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

/* The hand-off out of the conversation: one menu, four doors, each an
   existing step (write the scene, draw a still, Director, Queue). An
   item that cannot run yet says why instead of hiding. */
export type Handoff = "scene" | "still" | "director" | "queue";
type HandoffItem = { id: Handoff; label: string; note: string; icon: React.ReactNode; disabled?: boolean };

function ReadyMenu({ items, onPick, disabled }: { items: HandoffItem[]; onPick: (id: Handoff) => void; disabled: boolean }) {
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
      <button
        type="button"
        className="zc-ready"
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={disabled}
        title="When the idea is ready: write it, draw it, direct it, or render it"
        onClick={() => setOpen((v) => !v)}
      >
        Ready
        <ChevronDown strokeWidth={2} />
      </button>
      {open ? (
        <span className="pillmenu end zc-ready-menu" role="menu">
          <span className="m">Send it on</span>
          {items.map((it) => (
            <button
              type="button"
              key={it.id}
              role="menuitem"
              disabled={it.disabled}
              onClick={() => {
                setOpen(false);
                onPick(it.id);
              }}
            >
              {it.icon}
              <span>
                {it.label}
                <small>{it.note}</small>
              </span>
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
  const router = useRouter();
  const params = useSearchParams();
  const attachId = params.get("attach");
  // An idea typed into the landing page's hero arrives as ?spark= and the
  // composer opens already carrying it -- the sentence a visitor wrote is
  // the one thing on that page that must not be thrown away. It is put
  // in the box once the saved draft has loaded, so the draft cannot
  // land on top of it (and it outranks whatever the draft held).
  const sparkParam = params.get("spark");
  // The thread and the box are the studio's (assistant-thread.tsx): the
  // same turns the pill shows, and a draft that survives leaving the page.
  const { turns: thread, setTurns: setThread, draft, setDraft, ready } = useAssistantThread();
  const { idea, picked, brief, uploads } = draft;
  const setIdea = useCallback(
    (v: string | ((s: string) => string)) => setDraft((d) => ({ ...d, idea: typeof v === "function" ? v(d.idea) : v })),
    [setDraft],
  );
  const setPicked = useCallback(
    (v: string[] | ((s: string[]) => string[])) =>
      setDraft((d) => ({ ...d, picked: typeof v === "function" ? v(d.picked) : v })),
    [setDraft],
  );
  const setBrief = (v: string) => setDraft({ brief: v });
  // The project this composer writes inside (2026-09-28): handed over by
  // the Projects page as ?project=, remembered per browser, cleared by the
  // chip's ×. Create and the Guide both send it, so the scene is written
  // against the project's brief + memory and filed under it.
  const projectParam = params.get("project");
  const [project, setProject] = useState<Project | null>(null);
  const [caps, setCaps] = useState<Capabilities>({});
  const [assets, setAssets] = useState<Asset[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<Asset | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [busy, setBusy] = useState(false);
  // the Guide's progress line while it answers (null = not answering)
  const [guideWorking, setGuideWorking] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  // the frames "Use in a shot" handed over, held until the draft has loaded
  const [attachPhotos, setAttachPhotos] = useState<string[] | null>(null);
  const paramsApplied = useRef(false);
  // the guide's offered replies: the newest answer's, gone once replied to
  const last = thread[thread.length - 1];
  const choices = last && last.role === "assistant" && !last.failed ? last.reply?.choices ?? [] : [];
  // the optional pills: each shows only when its route answers
  const [brains, setBrains] = useState<Option[]>([]);
  const [brain, setBrain] = useState("");
  // the scene length's slider bounds, off /scene-lengths; null hides the control
  // (#131: any whole second between min and max, not a menu of five)
  const [lengths, setLengths] = useState<SceneLengths | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [ratios, setRatios] = useState<Option[]>([]);
  const [ratio, setRatio] = useState("");
  // the assistant pill filled the box: who, so the tag can say so and
  // send can wear a ring until the person presses it (or edits it away)
  const [filledBy, setFilledBy] = useState<{ name: string; avatar?: string } | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState<Preset | null>(null);
  const [slashAt, setSlashAt] = useState(0);
  // progress per running send, by made id -- page state, never saved: a
  // save per tick would be a PUT a second
  const [live, setLive] = useState<Record<string, Live>>({});
  // the send this page is waiting on (one at a time), and every made id
  // this page has a poll running for, so a resume never doubles one up
  const running = useRef<{ madeId: string; jobId?: number; stopped: boolean } | null>(null);
  const polling = useRef(new Set<string>());
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const stackRef = useRef<HTMLDivElement>(null);
  const dragDepth = useRef(0);
  const still = useReducedMotion();

  const loadAssets = useCallback(
    () =>
      getAssets()
        .then((r) => setAssets(r.items))
        .catch(() => setAssets([])),
    [],
  );

  useEffect(() => {
    getCapabilities().then(setCaps).catch(() => setCaps({}));
    getPresets()
      .then((r) => setPresets(r.items))
      .catch(() => setPresets([]));
    // the picker lists elements only; a render handed over from the
    // Assets wall ("Use in a shot") needs the wider scope to resolve
    getAssets(undefined, attachId?.startsWith("generated-") ? "all" : "elements")
      .then((r) => {
        setAssets(r.items.filter((a) => (a.category as string) !== "generated"));
        // "Use in a shot" on Assets lands here with the asset attached
        const hit = attachId ? r.items.find((a) => a.id === attachId) : null;
        if (hit) setAttachPhotos(hit.photos.slice(0, FRAMES_PER_ASSET));
      })
      .catch(() => setAssets([]));
    apiFetch<{ brains: { id: string; label: string; note: string }[]; default: string }>("/brains")
      .then((r) => {
        setBrains(r.brains.map((b) => ({ id: b.id, label: b.label, note: b.note })));
        setBrain(r.default);
      })
      .catch(() => setBrains([]));
    apiFetch<SceneLengths>("/scene-lengths")
      .then((r) => {
        setLengths({ min: r.min, max: r.max, default: r.default });
        setSeconds(r.default);
      })
      .catch(() => setLengths(null));
    apiFetch<{ ratios: { id: string; label: string; size: string }[]; default: string }>("/render-choices")
      .then((r) => {
        setRatios(r.ratios.map((x) => ({ id: x.id, label: x.label, note: x.size })));
        setRatio(r.default);
      })
      .catch(() => setRatios([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // What the URL asked for goes in AFTER the saved draft has loaded, or the
  // load would land on top of it: ?spark= replaces the idea (the visitor's
  // sentence outranks an old draft), ?attach= adds its frames to the picks.
  useEffect(() => {
    if (!ready || paramsApplied.current) return;
    if (attachId && attachPhotos === null) return; // its photos are still being looked up
    paramsApplied.current = true;
    if (sparkParam) setIdea(sparkParam);
    if (attachPhotos?.length) setPicked((was) => [...new Set([...was, ...attachPhotos])]);
  }, [ready, sparkParam, attachId, attachPhotos, setIdea, setPicked]);

  // The assistant pill writes into this box through a window event (it
  // floats over every page). A fill asked for from another page waited in
  // sessionStorage and is taken on mount. It only ever FILLS: the send is
  // still the person's click.
  useEffect(() => {
    const take = () => {
      const fill = takePendingFill();
      if (!fill) return;
      if (fill.text) {
        setIdea(fill.text);
        setFilledBy({ name: fill.by, avatar: fill.avatar });
      }
      if (fill.refs?.length) setPicked((was) => [...new Set([...was, ...fill.refs!])]);
    };
    take();
    window.addEventListener(FILL_EVENT, take);
    return () => window.removeEventListener(FILL_EVENT, take);
  }, [setIdea, setPicked]);

  // object URLs for uploads still in flight are revoked when the composer unmounts
  useEffect(() => {
    return () => pending.forEach((a) => URL.revokeObjectURL(a.url));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // the box grows with what is typed, up to the stylesheet's max-height
  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [idea]);

  // the Guide answers every send; without the route (no Gemini key) the
  // box says so rather than 404ing on Enter
  const guideReady = caps.creative_guide === true;

  // the slash menu: the fixed commands plus GET /api/presets as camera chips
  const commands = useMemo<SlashCommand[]>(
    () => [
      ...BASE_COMMANDS,
      ...presets.map((p) => ({
        id: `preset:${p.id}`,
        cmd: p.id.replace(/[^\w-]+/g, "-").toLowerCase(),
        desc: p.label,
        group: "camera" as const,
      })),
    ],
    [presets],
  );
  const hasImage = thread.some((t) => t.made?.output === "image" && t.made.status === "done" && !!t.made.image);
  const slashItems = matchCommands(idea, commands, hasImage);

  // The newest turn is lifted clear of the docked box -- on the send, and
  // again when it finishes (a finished turn is taller). Without it a still
  // landed with its bottom under the box and nothing on screen said so.
  const lastMade = last?.made;
  useEffect(() => {
    const stack = stackRef.current;
    const box = stack?.querySelector<HTMLElement>(".zc-box");
    const turn = stack?.querySelector<HTMLElement>(".zc-turn:last-of-type");
    if (!box || !turn) return;
    const hidden = turn.getBoundingClientRect().bottom + 16 - box.getBoundingClientRect().top;
    if (hidden <= 0) return;
    window.scrollBy({ top: hidden, behavior: still ? "auto" : "smooth" });
  }, [thread.length, lastMade?.status, guideWorking, still]);

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

  // an upload still on its way to the bin would be left out of the turn
  const canSend = !busy && !pending.length && !!idea.trim();
  // what Ready writes or draws from: the Guide's brief when there is one,
  // else whatever is in the box
  const handoffText = brief.trim() || idea.trim();
  // the last scene written here, for Director and the Queue
  const lastScene = [...thread].reverse().find((t) => t.made?.output === "video" && t.made.status === "done" && !!t.made.conceptId)?.made ?? null;
  const referenceCount = picked.length + uploads.length + pending.length;

  useEffect(() => {
    const id = Number(projectParam) || recallActiveProject();
    if (!id) return;
    getProject(id)
      .then((p) => {
        if (p.archived) throw new Error("archived");
        setProject(p);
        rememberActiveProject(p.id);
      })
      .catch(() => {
        setProject(null);
        rememberActiveProject(null);
      });
  }, [projectParam]);

  const leaveProject = () => {
    setProject(null);
    rememberActiveProject(null);
  };

  // The references on screen, in the field name the API reads for a
  // stored reference (app/api.py:_collect_refs, `asset_photos`). Uploads
  // go first -- refs[0] is the frame the clip anchors on -- then the picks
  // out of the asset bank. ONE helper for every send.
  const appendReferences = (form: FormData) => {
    [...uploads.map((u) => u.url), ...picked].forEach((u) => form.append("asset_photos", u));
  };

  /* A send's record is patched by its id, on the shared thread: the
     status changes and the result are what get saved. */
  const patchMade = useCallback(
    (id: string, p: Partial<Made>) =>
      setThread((ts) => ts.map((t) => (t.made?.id === id ? { ...t, made: { ...t.made, ...p } } : t))),
    [setThread],
  );
  const tick = useCallback(
    (id: string, j: Job) => setLive((l) => ({ ...l, [id]: { progress: j.progress || 0, detail: j.detail || "" } })),
    [],
  );

  /* The result, read back off the concept the job wrote: the still for an
     IMAGE send, the title and timed shots for a VIDEO one. Shared by a send
     made here and a send picked up again after a reload. */
  const finish = useCallback(
    async (madeId: string, output: Output, job: Job) => {
      polling.current.delete(madeId);
      setLive((l) => {
        const n = { ...l };
        delete n[madeId];
        return n;
      });
      // charged quietly, the InVideo way: no price on the button, the
      // balance pill just moves (2026-09-28)
      announceBalanceChange();
      if (job.status !== "done") {
        patchMade(madeId, { status: "failed", detail: job.error || "That run did not finish." });
        toast(job.error || "That run did not finish.", "err");
        return;
      }
      const conceptId = job.ref_id ?? null;
      const detail = conceptId ? await getConceptDetail(conceptId).catch(() => null) : null;
      if (output === "image") {
        const shots = detail?.shots ?? [];
        const image = detail?.reference_image || shots[shots.length - 1]?.reference_image || null;
        patchMade(madeId, { status: "done", conceptId, image, detail: job.detail || "" });
        if (!image) toast(job.detail || "Saved, but no image came back.", "err");
      } else {
        const timeline = detail?.timeline ?? detail?.shots?.[0]?.timeline ?? null;
        patchMade(madeId, {
          status: "done",
          conceptId,
          detail: job.detail || "on the board",
          title: detail?.title,
          parts: timeline?.parts ?? [],
          seconds: timeline?.seconds ?? detail?.duration ?? null,
        });
        toast("Scene written · it is on Pipeline to pick");
        announceQueueChange();
      }
    },
    [patchMade, toast],
  );

  /* An element's reference sheet is a job (cents, Nano Banana Pro); the
     turn carrying the element shows it drawing, then the sheet. One poll
     per job id, shared by the click and a resume after a reload. */
  const sheetPolls = useRef(new Set<number>());
  const patchElement = useCallback(
    (jobId: number, p: Partial<ElementMade>) =>
      setThread((ts) =>
        ts.map((t) => (t.element?.sheetJob === jobId ? { ...t, element: { ...t.element, ...p } } : t)),
      ),
    [setThread],
  );
  const watchSheet = useCallback(
    (jobId: number) => {
      if (sheetPolls.current.has(jobId)) return;
      sheetPolls.current.add(jobId);
      waitForJob(jobId)
        .then((job) => {
          const ok = job.status === "done" && !!job.output;
          patchElement(jobId, {
            drawing: false,
            sheet: ok ? job.output : null,
            note: ok ? null : job.error || job.detail || "The sheet did not draw.",
          });
          announceBalanceChange();
          if (ok) {
            toast("Reference sheet drawn");
            void loadAssets();
          } else toast(job.error || "The sheet did not draw.", "err");
        })
        .catch(() => {
          patchElement(jobId, { drawing: false, note: "The sheet was lost (the server restarted while it drew)." });
        })
        .finally(() => sheetPolls.current.delete(jobId));
    },
    [patchElement, toast, loadAssets],
  );
  useEffect(() => {
    if (!ready) return;
    for (const t of thread) {
      if (t.element?.drawing && t.element.sheetJob) watchSheet(t.element.sheetJob);
    }
  }, [ready, thread, watchSheet]);

  /* A send left running -- the page was left, or reloaded, mid-way -- is
     picked up again: its job id is on the turn, the job registry still
     holds it (or has finished it). A job the server no longer knows is a
     run lost to a restart, and the turn says so. */
  useEffect(() => {
    if (!ready) return;
    for (const t of thread) {
      const m = t.made;
      if (!m || m.status !== "running" || polling.current.has(m.id)) continue;
      if (!m.jobId) {
        patchMade(m.id, { status: "failed", detail: "That run was lost before it started." });
        continue;
      }
      polling.current.add(m.id);
      const id = m.id;
      const out = m.output;
      pollJob(m.jobId, (j) => tick(id, j), () => false)
        .then((job) => {
          if (job) return finish(id, out, job);
        })
        .catch(() => {
          polling.current.delete(id);
          patchMade(id, { status: "failed", detail: "That run was lost (the server restarted while it ran)." });
        });
    }
  }, [ready, thread, patchMade, tick, finish]);

  /* Stop: the wait ends at once and the turn says so. The server is
     asked to cancel too, but nothing waits on its answer -- a job that
     finishes anyway still lands on the board, the way it always has. */
  const stop = useCallback(() => {
    const r = running.current;
    if (!r) return;
    r.stopped = true;
    polling.current.delete(r.madeId);
    if (r.jobId) cancelJob(r.jobId).catch(() => {});
    patchMade(r.madeId, { status: "stopped" });
    running.current = null;
    setBusy(false);
  }, [patchMade]);

  // the header's New session: the provider archives and clears the thread;
  // this page ends a live wait and drops what is only its own
  useEffect(() => {
    const on = () => {
      stop();
      setLive({});
      setGuideWorking(null);
      setFilledBy(null);
      setPreset(null);
      setTimeout(() => textarea.current?.focus(), 50);
    };
    window.addEventListener(NEW_SESSION_EVENT, on);
    return () => window.removeEventListener(NEW_SESSION_EVENT, on);
  }, [stop]);

  /* The hand-offs that make something: ONE scene or ONE still per call,
     saved on its own turn. A still is drawn at the frame's shape when
     Nano takes it (16:9, 9:16, 1:1, 4:5), else at the first one. */
  async function make(output: Output, text: string, fromBrief = false) {
    const madeId = newMadeId();
    const isImage = output === "image";
    const frameLabel = ratios.find((r) => r.id === ratio)?.label;
    const aspect = IMAGE_ASPECTS.find((a) => a.id === frameLabel)?.id ?? IMAGE_ASPECTS[0].id;
    const frame = isImage ? aspect : frameLabel;
    const refThumbs = [...uploads.map((u) => u.url), ...picked].filter(drawable);
    // a hand-off from the brief says so in one line: the brief is already
    // on screen under the box, and a bubble echoing the whole spec buried
    // the tiles under it on a phone
    const made: Made = {
      id: madeId, output, refs: refThumbs, status: "running", detail: "", frame,
      ...(fromBrief ? { prompt: text } : {}),
    };
    const said = fromBrief ? (isImage ? "Draw a still from the brief" : "Write the scene from the brief") : text;
    setThread((ts) => [...ts, { role: "user", content: said, made }]);
    const me = { madeId, stopped: false } as { madeId: string; jobId?: number; stopped: boolean };
    running.current = me;
    polling.current.add(madeId);
    setIdea("");

    const form = new FormData();
    if (brand) form.append("brand", brand);
    if (isImage) {
      form.append("prompt", text);
      form.append("output", "image");
      if (preset) form.append("preset", preset.id);
      form.append("aspect", aspect);
    } else {
      // a camera preset is a line the writer reads, not a hidden field:
      // /scenes/run has no preset input, so it rides in the idea
      form.append("idea", preset ? `${text}\n\nCamera: ${preset.how}` : text);
      form.append("count", "1");
      if (brain) form.append("brain", brain);
      if (seconds) form.append("seconds", String(seconds));
      if (ratio) form.append("ratio", ratio);
      // written against the project's brief + memory and filed under it;
      // /generate/run takes no project, so a still is filed outside one
      if (project) form.append("project_id", String(project.id));
    }
    appendReferences(form);

    const started = isImage ? await runImage(form) : await runScenes(form);
    me.jobId = started.job_id;
    patchMade(madeId, { jobId: started.job_id });
    const job = await pollJob(started.job_id, (j) => tick(madeId, j), () => me.stopped);
    if (!job) return; // stopped: stop() already drew it
    running.current = null;
    await finish(madeId, output, job);
  }

  async function send() {
    if (!canSend) return;
    setBusy(true);
    setFilledBy(null);
    let asking: Turn | null = null;
    try {
      // Every send is a Guide turn (2026-10-03). The box used to be in
      // Create by default, so "Can we create an Element sheet of the
      // sugar free redbull can" went to the image renderer as a prompt;
      // now nothing leaves the talk until Ready is pressed.
      if (!guideReady) throw new Error("The Guide needs GEMINI_API_KEY on the server before it can answer.");
      const asked = idea.trim();
      const mine: Turn = { role: "user", content: asked };
      // the box's own sends (t.made) are not the Guide's turns: left out of
      // the conversation it answers
      const next: Turn[] = [...thread.filter((m) => !m.failed && !m.made), mine];
      asking = mine;
      setThread((all) => [...all, mine]);
      setIdea("");
      setGuideWorking("Thinking…");
      const form = new FormData();
      form.append(
        "conversation",
        JSON.stringify({ messages: next.map(({ role, content }) => ({ role, content })) }),
      );
      if (brand) form.append("brand", brand);
      form.append("guide_provider", "gemini");
      form.append("idea", asked);
      if (project) form.append("project_id", String(project.id));
      // The same Fast / Reasoning pill a send carries. Without it the
      // Guide answered every turn on the reasoning tier -- ~1.5c a
      // message for "which direction?". Server clamps it; absent means Fast.
      if (brain) form.append("brain", brain);
      // The same photos a send would carry: the guide grounds on them
      // (scene_chain.ground) and the model is shown them, so it can
      // answer about a face instead of asking where the photos are.
      appendReferences(form);
      // runCreativeGuide, never a bare fetch: the route is behind
      // mutation_header and a call without GUARDED_HEADERS is refused 403.
      const started = await runCreativeGuide(form);
      const job = await waitForJob(started.job_id, (j) => setGuideWorking(j.detail || "Considering your direction…"));
      const reply = (job as unknown as { reply?: GuideReply }).reply;
      if (job.status !== "done" || !reply) throw new Error(job.error || "The guide stopped.");
      // appended to whatever the thread holds NOW: the pill shares it and
      // may have added a turn while this one was out
      setThread((all) => [
        ...all,
        {
          role: "assistant",
          content: reply.message,
          reply,
          looked: (reply.tool_runs ?? []).filter((r) => r.ok).map((r) => r.tool),
          chosen: keepersOf(reply.sheet),
        },
      ]);
      if (reply.brief) setBrief(reply.brief);
    } catch (e) {
      // The thread and the box were cleared before the request went out,
      // so a failed turn must say so ON its own bubble, and hand the
      // words back for a retry.
      if (asking) {
        const mine = asking;
        setThread((all) => all.map((m) => (m === mine ? { ...m, failed: true } : m)));
        setIdea((now) => now || mine.content);
      }
      const r = running.current;
      if (r && !r.stopped) {
        polling.current.delete(r.madeId);
        patchMade(r.madeId, { status: "failed", detail: e instanceof Error ? e.message : "That did not go through." });
        running.current = null;
      }
      toast(e instanceof Error ? e.message : "That did not go through.", "err");
    } finally {
      setGuideWorking(null);
      setBusy(false);
    }
  }

  /* READY: the one door out of the conversation. Write the scene and
     Draw a still make a turn of their own (make); Director and Queue go
     to the last scene written here. Send to Queue PICKS -- approving in
     Queue is still the one click that spends. */
  async function handoff(what: Handoff) {
    if (busy) return;
    if (what === "director") {
      if (lastScene?.conceptId) router.push(`/studio/flows?concept=${lastScene.conceptId}&shot=${lastScene.shot ?? 1}`);
      return;
    }
    setBusy(true);
    setFilledBy(null);
    try {
      if (what === "queue") {
        if (!lastScene?.conceptId) return;
        await pickConcept(lastScene.conceptId);
        announceQueueChange();
        toast("Picked · approve the render in Queue");
        router.push("/studio/queue");
        return;
      }
      if (!handoffText) {
        toast("Nothing to write yet — say what the scene is first", "err");
        return;
      }
      await make(what === "still" ? "image" : "video", handoffText, !!brief.trim());
    } catch (e) {
      const r = running.current;
      if (r && !r.stopped) {
        polling.current.delete(r.madeId);
        patchMade(r.madeId, { status: "failed", detail: e instanceof Error ? e.message : "That did not go through." });
        running.current = null;
      }
      toast(e instanceof Error ? e.message : "That did not go through.", "err");
    } finally {
      setBusy(false);
    }
  }
  const handoffItems: HandoffItem[] = [
    {
      id: "scene",
      label: "Write the scene",
      note: handoffText ? (brief.trim() ? "from the brief · lands on Pipeline" : "from the box · lands on Pipeline") : "say what the scene is first",
      icon: <ListVideo strokeWidth={1.6} />,
      disabled: !handoffText,
    },
    {
      id: "still",
      label: "Draw a still",
      note: handoffText ? "one image, charged like any still" : "say what to draw first",
      icon: <ImagePlus strokeWidth={1.6} />,
      disabled: !handoffText,
    },
    {
      id: "director",
      label: "Open in Director",
      note: lastScene ? lastScene.title || "the last scene written here" : "write a scene first",
      icon: <Clapperboard strokeWidth={1.6} />,
      disabled: !lastScene,
    },
    {
      id: "queue",
      label: "Send to Queue",
      note: lastScene ? "picks it · approving there is what renders" : "write a scene first",
      icon: <Play strokeWidth={1.6} />,
      disabled: !lastScene,
    },
  ];

  /* the slash menu: every command changes something visible */
  function runCommand(c: SlashCommand) {
    setIdea("");
    setSlashAt(0);
    if (c.id === "scene" || c.id === "still") {
      void handoff(c.id);
      return;
    } else if (c.id === "animate") {
      const lastImage = [...thread].reverse().find((t) => t.made?.output === "image" && t.made.status === "done" && t.made.image);
      if (lastImage?.made) animate(lastImage.made);
      return;
    } else if (c.id === "ref") {
      fileInput.current?.click();
    } else if (c.id === "element") {
      setIdea("@");
    } else if (c.id.startsWith("preset:")) {
      const p = presets.find((x) => `preset:${x.id}` === c.id);
      if (p) setPreset(p);
    }
    textarea.current?.focus();
  }

  /* a finished still becomes a reference for what comes next */
  function attachResult(m: Made) {
    if (!m.image) return;
    setPicked((was) => [...new Set([...was, m.image!])]);
    toast("Image attached as a reference");
  }
  function animate(m: Made) {
    if (!m.image) return;
    setPicked((was) => [...new Set([...was, m.image!])]);
    setIdea((v) => v || "Animate this still: ");
    textarea.current?.focus();
    toast("Image attached · say how the shot moves, then Ready → Write the scene");
  }
  /* "Reuse prompt" fills the box -- or puts a brief-sourced hand-off's
     text back as the brief; it never spends on its own */
  function reuse(t: Turn) {
    if (t.made?.prompt) {
      setBrief(t.made.prompt);
      toast("Brief restored · edit it, then Ready → Write the scene");
    } else {
      setIdea(t.content);
    }
    textarea.current?.focus();
  }
  const select = (madeId: string, n: number) => patchMade(madeId, { shot: n });

  /* The confirm card. Nothing has run until this: the guide's turn
     ended on the proposal, and the click is what posts it. The result
     goes into the thread as the guide's own words, so the next turn's
     conversation says what was banked. */
  async function decide(i: number, yes: boolean) {
    const entry = thread[i];
    const proposal = entry?.reply?.proposal;
    if (!proposal || entry.decided || busy) return;
    if (!yes) {
      setThread((t) => t.map((m, j) => (j === i ? { ...m, decided: "skipped" } : m)));
      return;
    }
    setBusy(true);
    try {
      const done = await runGuideAction(proposal);
      // add_element (2026-10-03): the element it saved rides on the
      // turn -- its photos now, its sheet when the job has drawn it
      const element: ElementMade | undefined = done.element
        ? {
            kind: done.element.kind,
            name: done.element.name,
            slug: done.element.slug,
            photos: done.element.photos ?? [],
            sheet: null,
            sheetJob: done.element.sheet_job ?? null,
            drawing: !!done.element.sheet_job,
            note: done.element.note ?? null,
          }
        : undefined;
      setThread((t) => [
        ...t.map((m, j) => (j === i ? { ...m, decided: "done" as const } : m)),
        { role: "assistant", content: `Done — ${done.result}`, element },
      ]);
      if (element) {
        toast(`${element.name} saved as a ${element.kind} · it is on the shelf below`);
        void loadAssets();
        if (element.sheetJob) watchSheet(element.sheetJob);
      } else {
        toast("Banked.");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through.", "err");
    } finally {
      setBusy(false);
    }
  }

  /* Keep, from a contact sheet in the thread: the frames come back as
     /refs paths and go straight onto this composer's picks -- the same
     route the pill's Keep takes. Nothing is generated or charged. */
  const toggleFrame = (i: number, id: string) =>
    setThread((t) =>
      t.map((m, j) => (j === i ? { ...m, chosen: { ...(m.chosen ?? {}), [id]: !m.chosen?.[id] } } : m)),
    );
  async function keepFrames(i: number, sheet: ContactSheet) {
    const chosen = thread[i]?.chosen ?? {};
    const ids = sheet.sheet.flatMap((n) => [...n.keepers, ...n.rejected]).filter((f) => chosen[f.id]).map((f) => f.id);
    if (!ids.length || busy) return;
    setBusy(true);
    try {
      const res = await keepReferences(ids);
      const urls = res.result.kept.map((k) => k.url);
      if (urls.length) setPicked((was) => [...new Set([...was, ...urls])]);
      setThread((t) => t.map((m, j) => (j === i ? { ...m, kept: true } : m)));
      const refused = res.result.refused.length;
      toast(
        `${urls.length} reference${urls.length === 1 ? "" : "s"} added to the composer` +
          (refused ? ` · ${refused} could not be kept` : ""),
        urls.length ? "ok" : "err",
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "Those frames were not kept.", "err");
    } finally {
      setBusy(false);
    }
  }

  /* An upload goes to the reference bin the moment it lands
     (POST /api/refs/upload: JPEG-normalised, content-addressed, mirrored
     to R2). The draft then remembers a URL that resolves on every machine,
     which is what lets the box survive leaving the page; a File object
     never could. The chip draws from the object URL until the server answers. */
  const attach = (files: FileList | File[] | null | undefined) => {
    const images = imageFiles(files);
    if (!images.length) return;
    const rows: Pending[] = images.map((f) => ({ id: crypto.randomUUID(), name: f.name, url: URL.createObjectURL(f) }));
    setPending((was) => [...was, ...rows]);
    const settle = () => {
      rows.forEach((r) => URL.revokeObjectURL(r.url));
      setPending((was) => was.filter((p) => !rows.some((r) => r.id === p.id)));
    };
    uploadRefs(images)
      .then((r) => {
        // names pair by position, best-effort: the server drops a duplicate
        // or an unreadable file, and the name is only the chip's text
        const named = r.urls.map((url, i) => ({ url, name: rows[i]?.name ?? "reference" }));
        setDraft((d) => ({
          ...d,
          uploads: [...d.uploads, ...named.filter((n) => !d.uploads.some((u) => u.url === n.url))],
        }));
        settle();
        const n = r.urls.length;
        if (n) toast(`${n} image${n === 1 ? "" : "s"} attached as reference` + (r.skipped ? ` · ${r.skipped} could not be read` : ""));
        else toast("Those images could not be read", "err");
      })
      .catch((e) => {
        settle();
        toast(e instanceof Error ? e.message : "The upload did not go through.", "err");
      });
  };
  const removeUpload = (url: string) => setDraft((d) => ({ ...d, uploads: d.uploads.filter((u) => u.url !== url) }));

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

  const empty = !thread.length;
  const liveRun = running.current && busy;
  const sendLabel = "Send";
  const placeholder = empty
    ? "Describe the idea, ask for a direction, or drop in a photo…"
    : "Reply, steer, or ask for the next step…";
  const fill = (text: string) => {
    setIdea(text);
    textarea.current?.focus();
  };
  const starters: { label: string; run: () => void }[] = [
    { label: "Pitch a concept", run: () => fill("Pitch me three short concepts for ") },
    { label: "Spec a commercial", run: () => fill("I'm writing a spec for a commercial for ") },
    { label: "Match a reference look", run: () => fileInput.current?.click() },
    {
      label: "Turn a still into a shot",
      run: () => {
        fill("Animate this still: ");
        fileInput.current?.click();
      },
    },
  ];
  const frameLabel = ratios.find((r) => r.id === ratio)?.label ?? "Frame";
  const brainLabel = brains.find((b) => b.id === brain)?.label ?? "Model";

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className={`hero zc ${empty ? "zc-empty" : "zc-active"}`}>
        {empty ? (
          <motion.h1
            initial={still ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: EASE }}
          >
            What are we making?
          </motion.h1>
        ) : null}
        <div className="stack" ref={stackRef}>
          {!empty ? (
            <ComposerStream
              turns={thread}
              live={live}
              choices={choices}
              working={guideWorking}
              handlers={{
                busy,
                onAnimate: animate,
                onUseAsRef: attachResult,
                onReuse: reuse,
                onSelect: select,
                onChip: fill,
                onDecide: decide,
                onToggleFrame: toggleFrame,
                onKeep: keepFrames,
                onUseElement: (el) => {
                  // the real photos first -- refs[0] anchors the clip -- and
                  // the drawn sheet behind them, the same order Elements keeps
                  const urls = [...el.photos.slice(0, FRAMES_PER_ASSET), ...(el.sheet ? [el.sheet] : [])];
                  setPicked((was) => [...new Set([...was, ...urls])]);
                  toast(`${el.name} attached · ${urls.length} frame${urls.length === 1 ? "" : "s"}`);
                },
              }}
            />
          ) : null}
          {project ? (
            <div className="zc-project">
              <span>
                Project ·{" "}
                <Link href="/studio/projects">{project.title}</Link>
                <button type="button" onClick={leaveProject} aria-label="Leave this project" title="Write outside any project">
                  <X strokeWidth={2} size={11} />
                </button>
              </span>
              <span>written against its brief and {project.memory.length} learned</span>
            </div>
          ) : null}
          <motion.div
            className={`zc-box${idea ? " awake" : ""}${dragging ? " drop" : ""}`}
            initial={still || !empty ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.05, ease: EASE }}
            onDragEnter={onDragEnter}
            onDragOver={(e) => e.preventDefault()}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            <AnimatePresence>
              {dragging ? (
                <motion.div
                  className="zc-drop"
                  aria-hidden
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                >
                  <ArrowUpFromLine strokeWidth={1.8} />
                  <b>Drop to add as a reference</b>
                  <span>Images or clips: they guide the look, character, or location</span>
                </motion.div>
              ) : null}
            </AnimatePresence>

            {referenceCount || preset ? (
              <div className="zc-chips">
                {preset ? (
                  <span className="zc-chip preset" title={preset.how}>
                    <span className="zc-chip-name">{preset.label}</span>
                    <button type="button" aria-label={`Remove preset ${preset.label}`} onClick={() => setPreset(null)}>
                      <X strokeWidth={2} />
                    </button>
                  </span>
                ) : null}
                {uploads.map((a) => (
                  <span key={a.url} className="zc-chip" title={a.name || a.url}>
                    <span
                      className="zc-chip-thumb"
                      style={drawable(a.url) ? { backgroundImage: `url(${API_URL}${a.url})` } : undefined}
                    >
                      {drawable(a.url) ? null : a.url.split(".").pop()?.split("?")[0]?.toUpperCase()}
                    </span>
                    <span className="zc-chip-name">{a.name || "reference"}</span>
                    <button type="button" aria-label={`Remove ${a.name || "upload"}`} onClick={() => removeUpload(a.url)}>
                      <X strokeWidth={2} />
                    </button>
                  </span>
                ))}
                {pending.map((a) => (
                  <span key={a.id} className="zc-chip pending" title={`${a.name} · uploading…`} aria-busy="true">
                    <span className="zc-chip-thumb" style={{ backgroundImage: `url(${a.url})` }} />
                    <span className="zc-chip-name">{a.name}</span>
                  </span>
                ))}
                {picked.map((u) => {
                  const name = decodeURIComponent(u.split("/").pop()?.split("?")[0] ?? "reference");
                  return (
                    <span key={u} className="zc-chip" title={u}>
                      <span
                        className="zc-chip-thumb"
                        style={drawable(u) ? { backgroundImage: `url(${mediaSrc(u)})` } : undefined}
                      >
                        {drawable(u) ? null : u.split(".").pop()?.split("?")[0]?.toUpperCase()}
                      </span>
                      <span className="zc-chip-name">{name}</span>
                      <button
                        type="button"
                        aria-label={`Remove ${name}`}
                        onClick={() => setPicked((w) => w.filter((x) => x !== u))}
                      >
                        <X strokeWidth={2} />
                      </button>
                    </span>
                  );
                })}
                {referenceCount > 1 ? (
                  <button type="button" className="cclear" onClick={() => setDraft({ picked: [], uploads: [] })}>
                    Clear {referenceCount}
                  </button>
                ) : null}
              </div>
            ) : null}
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

            <div className="zc-field">
              <AnimatePresence>
                {slashItems ? (
                  <SlashMenu
                    key="slash"
                    items={slashItems}
                    active={Math.min(slashAt, Math.max(0, slashItems.length - 1))}
                    onPick={runCommand}
                    onHover={setSlashAt}
                  />
                ) : null}
              </AnimatePresence>
              <textarea
                ref={textarea}
                value={idea}
                maxLength={10000}
                rows={empty ? 2 : 1}
                onChange={(e) => {
                  setIdea(e.target.value);
                  setSlashAt(0);
                  if (!e.target.value.trim()) setFilledBy(null);
                }}
                onKeyDown={(e) => {
                  if (mentions.onKeyDown(e)) return;
                  if (slashItems) {
                    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                      e.preventDefault();
                      const n = slashItems.length || 1;
                      setSlashAt((i) => (i + (e.key === "ArrowDown" ? 1 : n - 1)) % n);
                      return;
                    }
                    if ((e.key === "Enter" || e.key === "Tab") && slashItems.length) {
                      e.preventDefault();
                      runCommand(slashItems[Math.min(slashAt, slashItems.length - 1)]);
                      return;
                    }
                    if (e.key === "Escape") {
                      e.preventDefault();
                      setIdea("");
                      return;
                    }
                  }
                  // Enter sends, Shift+Enter is a new line (⌘/Ctrl+Enter
                  // still sends, for the hands that learned it)
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    void send();
                  }
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
                placeholder={placeholder}
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
                  Brief from the guide · editable · Ready writes from this, not from the box
                </span>
                <textarea value={brief} onChange={(e) => setBrief(e.target.value)} rows={5} />
                <button type="button" className="pill chosen cbrief-go" disabled={busy} onClick={() => void handoff("scene")}>
                  <ListVideo strokeWidth={1.6} />
                  Write the scene
                </button>
              </div>
            ) : null}

            <div className="zc-tools">
              <button
                type="button"
                className="zc-tool"
                aria-label="Attach a reference image"
                title="Attach a reference image"
                onClick={() => fileInput.current?.click()}
              >
                <Paperclip strokeWidth={1.6} />
              </button>
              <button
                type="button"
                className="zc-tool"
                aria-label="Reference a saved element"
                title="Reference a saved element (@)"
                onClick={() => {
                  setIdea((v) => `${v}${v && !v.endsWith(" ") ? " " : ""}@`);
                  textarea.current?.focus();
                }}
              >
                <AtSign strokeWidth={1.6} />
              </button>
              <span className="zc-opts">
                {ratios.length ? (
                  <OptMenu heading="Frame" value={ratio} onChange={setRatio} options={ratios} label={frameLabel} />
                ) : null}
                {lengths ? (
                  <>
                    <span className="zc-dot" aria-hidden>
                      ·
                    </span>
                    <DurationPill
                      seconds={seconds}
                      span={lengths}
                      onChange={setSeconds}
                      trigger={(open) => (
                        <button type="button" className="zc-opt" aria-expanded={open} title="How long the scene is">
                          {seconds}s
                        </button>
                      )}
                    />
                  </>
                ) : null}
                {brains.length ? (
                  <>
                    <span className="zc-dot" aria-hidden>
                      ·
                    </span>
                    <OptMenu
                      heading="Which model answers and writes"
                      value={brain}
                      onChange={setBrain}
                      options={brains}
                      label={brainLabel}
                      chevron
                    />
                  </>
                ) : null}
              </span>
              <span className="spacer" />
              {filledBy && idea.trim() ? (
                <span className="zpa-filled">
                  {filledBy.avatar ? `${filledBy.avatar} ` : ""}Filled by {filledBy.name}
                </span>
              ) : null}
              {liveRun ? (
                <button type="button" className="zc-stop" onClick={stop}>
                  Stop
                </button>
              ) : busy ? (
                <span className="zc-thinking" role="status">
                  <span className="zc-live" aria-hidden /> Thinking…
                </span>
              ) : (
                <>
                  <ReadyMenu items={handoffItems} onPick={(id) => void handoff(id)} disabled={busy || !!pending.length} />
                  <motion.button
                  type="button"
                  className={`zc-send${filledBy && idea.trim() ? " zpa-ring" : ""}`}
                  disabled={!canSend}
                  aria-label={sendLabel}
                  title={`${sendLabel} (Enter)`}
                  whileHover={canSend && !still ? { scale: 1.06 } : undefined}
                  whileTap={canSend && !still ? { scale: 0.94 } : undefined}
                  onClick={() => void send()}
                >
                  <ArrowUp strokeWidth={2.2} />
                </motion.button>
                </>
              )}
            </div>
          </motion.div>
          {empty ? (
            <motion.div
              className="zc-starters"
              initial={still ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.12, ease: EASE }}
            >
              {starters.map((s) => (
                <button type="button" key={s.label} onClick={s.run}>
                  {s.label}
                </button>
              ))}
            </motion.div>
          ) : null}
        </div>
        {empty ? (
          <p className="zc-hint">
            <kbd>↵</kbd> send · <kbd>⇧↵</kbd> new line · <kbd>/</kbd> commands · drop files to add references · <b>Ready</b> when it is time to write, draw, direct or render
          </p>
        ) : null}
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
