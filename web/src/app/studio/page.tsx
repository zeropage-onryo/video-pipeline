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
   exactly where the talk was. And ONLY that: a conversation is working
   memory, not a record (Mike's call, same day). Once Create has written
   the scene it goes away -- the talk, the brief, the box and its
   references -- leaving the "scene written" card; what it produced is on
   the concept and, rendered, on the asset with its prompt. The pill's
   button clears it the same way. Nothing is archived.

   THE LOOK IS THE "ZPF COMPOSER DIRECTIONS" MOCK (2026-10-02, Mike:
   "create a similar look to the images shown in our mock design"). One
   centred box under "What are we making?", an Image | Video switch, the
   settings as one line, a red round send; a send becomes a bubble with
   its result as tiles above a docked box; `/` opens commands; a drop
   covers the box; a running send can be stopped. Still ONE output per
   send -- IMAGE is one Nano Banana still through /api/generate/run, VIDEO
   is the Create above -- and a send is saved on its turn (lib/composer.ts
   `Made`), so a still drawn here survives a trip to Pipeline. A send
   left running is picked up again on return (its job id is on the turn). */
import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useSearchParams } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowUp,
  ArrowUpFromLine,
  AtSign,
  ChevronDown,
  Ellipsis,
  Image as ImageIcon,
  ImageOff,
  MessageSquare,
  Paperclip,
  Play,
  Plus,
  Search,
  Video,
  X,
} from "lucide-react";
import { API_URL, apiFetch } from "@/lib/api";
import {
  announceBalanceChange,
  announceQueueChange,
  cancelJob,
  drawKeyframes,
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
  type Turn,
} from "@/lib/assistant";
import { keepersOf } from "@/components/studio/contact-sheet";
import {
  BASE_COMMANDS,
  IMAGE_ASPECTS,
  loadOutput,
  matchCommands,
  mediaSrc,
  newMadeId,
  pollJob,
  saveOutput,
  type Made,
  type Output,
  type SlashCommand,
} from "@/lib/composer";
import { ComposerStream, type Drawing, type Live } from "@/components/studio/composer/turns";
import { creditsText } from "@/lib/render-choice";
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
  const { brand, balance, toast } = useShell();
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
  const { turns: thread, setTurns: setThread, draft, setDraft, ready, finishProject } = useAssistantThread();
  const { idea, picked, brief, uploads, mode: wantMode } = draft;
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
  const setMode = useCallback((m: "guide" | "create") => setDraft({ mode: m }), [setDraft]);
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
  // what a send makes (2026-10-02). The composer IS server-rendered (as
  // video), so the stored choice is read after mount -- read in the
  // initializer, a saved "image" failed hydration on every load.
  const [output, setOutputState] = useState<Output>("video");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after mount
    setOutputState(loadOutput());
  }, []);
  const setOutput = (o: Output) => {
    setOutputState(o);
    saveOutput(o);
  };
  const [aspect, setAspect] = useState(IMAGE_ASPECTS[0].id);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState<Preset | null>(null);
  const [slashAt, setSlashAt] = useState(0);
  // progress per running send, by made id -- page state, never saved: a
  // save per tick would be a PUT a second
  const [live, setLive] = useState<Record<string, Live>>({});
  // which shot each send is drawing a still for (the cue cards' approve,
  // 2026-10-04) -- page state, like `live`
  const [drawing, setDrawing] = useState<Drawing>({});
  // done video turns re-read once per visit, so a still drawn in the
  // Queue (or a pick made on Pipeline) shows on the cards here
  const refreshed = useRef(false);
  // the send this page is waiting on (one at a time), and every made id
  // this page has a poll running for, so a resume never doubles one up
  const running = useRef<{ madeId: string; jobId?: number; stopped: boolean } | null>(null);
  const polling = useRef(new Set<string>());
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const stackRef = useRef<HTMLDivElement>(null);
  const dragDepth = useRef(0);
  const still = useReducedMotion();

  const loadAssets = () =>
    getAssets()
      .then((r) => setAssets(r.items))
      .catch(() => setAssets([]));

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
        setMode("create");
        setFilledBy({ name: fill.by, avatar: fill.avatar });
      }
      if (fill.refs?.length) setPicked((was) => [...new Set([...was, ...fill.refs!])]);
    };
    take();
    window.addEventListener(FILL_EVENT, take);
    return () => window.removeEventListener(FILL_EVENT, take);
  }, [setIdea, setMode, setPicked]);

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

  // Guide only when the server says the route is there; otherwise the
  // primary action is a send rather than a button that 404s
  const guideReady = caps.creative_guide === true;
  const mode: "guide" | "create" = guideReady ? wantMode : "create";

  // the slash menu: the fixed commands plus GET /api/presets as camera chips
  const commands = useMemo<SlashCommand[]>(
    () => [
      ...BASE_COMMANDS.filter((c) => c.id !== "guide" || guideReady),
      ...presets.map((p) => ({
        id: `preset:${p.id}`,
        cmd: p.id.replace(/[^\w-]+/g, "-").toLowerCase(),
        desc: p.label,
        group: "camera" as const,
      })),
    ],
    [presets, guideReady],
  );
  const hasImage = thread.some((t) => t.made?.output === "image" && t.made.status === "done" && !!t.made.image);
  const slashItems = matchCommands(idea, commands, output, hasImage);

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

  // an upload still on its way to the bin would be left out of the run
  const canSend = !busy && !pending.length && (mode === "create" ? !!(idea.trim() || brief.trim()) : !!idea.trim());
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
          // the cards' approvals: what the missing stills cost, and the pick
          keyframes: detail?.keyframes ?? null,
          picked: !!detail?.picked,
          image: detail?.reference_image || null,
        });
        // the conversation did its job: the scene is on the board with its
        // prompt and references, so the Guide talk, the brief and the box
        // go away (2026-10-02, Mike's call). The send's own turn stays --
        // it IS the "scene written" card here, with the timed shots under it.
        finishProject({ conceptId, detail: job.detail || "on the board" });
        toast("Scene written · it is on Pipeline to pick");
        announceQueueChange();
      }
    },
    [patchMade, toast, finishProject],
  );

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

  /* The cue cards, read back off the concept: its stills, its price for
     the ones still missing, and whether it is picked. After a draw here,
     and once per visit for every finished video turn (a still drawn in
     the Queue, a pick made on Pipeline). Never a model call. */
  const refreshMade = useCallback(
    async (madeId: string, conceptId: number) => {
      const detail = await getConceptDetail(conceptId).catch(() => null);
      if (!detail) return;
      const timeline = detail.timeline ?? detail.shots?.[0]?.timeline ?? null;
      patchMade(madeId, {
        parts: timeline?.parts ?? [],
        keyframes: detail.keyframes ?? null,
        picked: !!detail.picked,
        image: detail.reference_image || null,
        title: detail.title,
      });
    },
    [patchMade],
  );
  useEffect(() => {
    if (!ready || refreshed.current) return;
    refreshed.current = true;
    for (const t of thread) {
      const m = t.made;
      if (m && m.output === "video" && m.status === "done" && m.conceptId) void refreshMade(m.id, m.conceptId);
    }
  }, [ready, thread, refreshMade]);

  /* The priced approve on a cue card (2026-10-04): one shot's still, or
     every missing one with `part` left out. The click IS the approval,
     the 2026-09-29 rule; a balance that cannot pay comes back as the
     server's 402 and is said on a toast, never drawn half-way. */
  const drawStills = async (m: Made, part?: number) => {
    if (!m.conceptId || !m.keyframes || drawing[m.id] != null) return;
    const conceptId = m.conceptId;
    const credits = part != null ? m.keyframes.each : m.keyframes.credits;
    setDrawing((d) => ({ ...d, [m.id]: part ?? "all" }));
    try {
      const res = await drawKeyframes(conceptId, part);
      toast(
        part != null
          ? `Drawing shot ${String(part).padStart(2, "0")} — ${creditsText(credits, !!balance?.exempt)}`
          : `Drawing ${res.keyframes.stills} stills — ${creditsText(credits, !!balance?.exempt)}`,
      );
      announceBalanceChange();
      if (res.job_id) {
        const job = await waitForJob(res.job_id);
        if (job.status === "failed") toast(job.error || "The still did not draw", "err");
      }
      announceBalanceChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through", "err");
    } finally {
      await refreshMade(m.id, conceptId);
      setDrawing((d) => {
        const n = { ...d };
        delete n[m.id];
        return n;
      });
    }
  };

  /* Pick, from the card: the board's own label (picked_at, the Queue's
     door), posted from here so a scene worth rendering need not be found
     again on Pipeline first. Spends nothing. */
  const pick = async (m: Made) => {
    if (!m.conceptId || m.picked) return;
    try {
      await pickConcept(m.conceptId, true);
      patchMade(m.id, { picked: true });
      toast("Picked · it is in the Queue to approve");
      announceQueueChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through", "err");
    }
  };

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

  /* IMAGE and VIDEO sends: one turn each, one output each. */
  async function make(text: string) {
    const madeId = newMadeId();
    const isImage = output === "image";
    const frame = isImage ? aspect : ratios.find((r) => r.id === ratio)?.label;
    const refThumbs = [...uploads.map((u) => u.url), ...picked].filter(drawable);
    const made: Made = { id: madeId, output, refs: refThumbs, status: "running", detail: "", frame };
    setThread((ts) => [...ts, { role: "user", content: text, made }]);
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
      if (mode === "create") {
        await make(brief.trim() || idea.trim());
      } else {
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
      }
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

  /* the slash menu: every command changes something visible */
  function runCommand(c: SlashCommand) {
    setIdea("");
    setSlashAt(0);
    if (c.id === "image" || c.id === "video") {
      setOutput(c.id);
      setMode("create");
    } else if (c.id === "guide") {
      if (guideReady) setMode("guide");
      else toast("The guide is not available on this account", "err");
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
    setOutput("video");
    setMode("create");
    textarea.current?.focus();
    toast("Image attached · describe how the shot moves");
  }
  /* "Reuse prompt" fills the box; it never spends on its own */
  function reuse(t: Turn) {
    if (t.made) setOutput(t.made.output);
    setMode("create");
    setIdea(t.content);
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
      setThread((t) => [
        ...t.map((m, j) => (j === i ? { ...m, decided: "done" as const } : m)),
        { role: "assistant", content: `Done — ${done.result}` },
      ]);
      toast("Banked.");
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
  const sendLabel = mode === "guide" ? "Send" : output === "image" ? "Generate" : "Create";
  const placeholder =
    mode === "guide"
      ? "Describe your idea or ask for a direction…"
      : output === "image"
        ? empty
          ? "Describe an image, a look, or a still…"
          : "Refine, vary, or describe the next image…"
        : empty
          ? "Describe a shot, scene, or sequence…"
          : "Refine, extend, or describe the next shot…";
  const starters: { label: string; run: () => void }[] = [
    ...(guideReady
      ? [
          {
            label: "Pitch a concept",
            run: () => {
              setMode("guide");
              setIdea("Pitch me three short concepts for ");
              textarea.current?.focus();
            },
          },
        ]
      : []),
    {
      label: "Storyboard a scene",
      run: () => {
        setOutput("video");
        setMode("create");
        setIdea("Storyboard a scene: ");
        textarea.current?.focus();
      },
    },
    { label: "Match a reference look", run: () => fileInput.current?.click() },
    {
      label: "Turn a still into a shot",
      run: () => {
        setOutput("video");
        setMode("create");
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
              drawing={drawing}
              choices={choices}
              working={guideWorking}
              handlers={{
                busy,
                exempt: !!balance?.exempt,
                onAnimate: animate,
                onUseAsRef: attachResult,
                onReuse: reuse,
                onSelect: select,
                onDraw: (m, part) => void drawStills(m, part),
                onPick: (m) => void pick(m),
                onChip: (c) => {
                  setMode("guide");
                  setIdea(c);
                  textarea.current?.focus();
                },
                onDecide: decide,
                onToggleFrame: toggleFrame,
                onKeep: keepFrames,
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

            <div className="zc-tools">
              <span className="zc-seg" role="radiogroup" aria-label="What to make">
                <button
                  type="button"
                  role="radio"
                  aria-checked={output === "image"}
                  onClick={() => {
                    setOutput("image");
                    setMode("create");
                  }}
                >
                  <ImageIcon strokeWidth={1.6} /> Image
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={output === "video"}
                  onClick={() => {
                    setOutput("video");
                    setMode("create");
                  }}
                >
                  <Video strokeWidth={1.6} /> Video
                </button>
              </span>
              {guideReady ? (
                <button
                  type="button"
                  className="zc-tool"
                  aria-pressed={mode === "guide"}
                  title="Talk the idea through first"
                  onClick={() => setMode(mode === "guide" ? "create" : "guide")}
                >
                  <MessageSquare strokeWidth={1.6} /> Guide
                </button>
              ) : null}
              <span className="zc-sep" aria-hidden />
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
                {output === "image" && mode !== "guide" ? (
                  <OptMenu heading="Image shape" value={aspect} onChange={setAspect} options={IMAGE_ASPECTS} label={aspect} />
                ) : null}
                {output === "video" && mode !== "guide" && ratios.length ? (
                  <OptMenu heading="Frame" value={ratio} onChange={setRatio} options={ratios} label={frameLabel} />
                ) : null}
                {output === "video" && mode !== "guide" && lengths ? (
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
                {brains.length && (output === "video" || mode === "guide") ? (
                  <>
                    {mode !== "guide" ? (
                      <span className="zc-dot" aria-hidden>
                        ·
                      </span>
                    ) : null}
                    <OptMenu
                      heading={mode === "guide" ? "Which model answers" : "Which model writes"}
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
                <motion.button
                  type="button"
                  className={`zc-send${filledBy && idea.trim() && mode === "create" ? " zpa-ring" : ""}`}
                  disabled={!canSend}
                  aria-label={sendLabel}
                  title={`${sendLabel} (Enter)`}
                  whileHover={canSend && !still ? { scale: 1.06 } : undefined}
                  whileTap={canSend && !still ? { scale: 0.94 } : undefined}
                  onClick={() => void send()}
                >
                  <ArrowUp strokeWidth={2.2} />
                </motion.button>
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
            <kbd>↵</kbd> {sendLabel.toLowerCase()} · <kbd>⇧↵</kbd> new line · <kbd>/</kbd> commands · drop files to add references
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
