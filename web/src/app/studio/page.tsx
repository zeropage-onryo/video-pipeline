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

   THERE IS NO GUIDE TOGGLE (2026-10-04, Mike: "it is all in one place
   where you can toggle between image and video that are connected to the
   reasoning/brain"). Every send is a Guide turn carrying the Image | Video
   switch: the brain talks when the person is bouncing ideas and MAKES when
   they ask for the thing -- a make_image / make_video proposal comes back
   (lib/composer.ts MAKE_TOOLS), on the brain's own prompt, through the same
   two routes a send used to post to directly. A scene is written at once;
   a still spends credits, so it is a STEP CARD (2026-10-08, after Runway
   Agent's chat): the prompt, the model, what it costs -- and, with "Ask
   first" on (the settings line's pill, Runway's "Ask before generating
   media"), an Approve it waits on, with the model and its price below.
   The Fast / Reasoning pill is the brain's and shows in both outputs; the
   Image output also picks WHICH MODEL DRAWS (GET /api/image-models: Nano
   Banana on the Gemini key, or fal's image models). Without the guide
   (capabilities.creative_guide false) a send makes directly, as before.
   The model / length / frame pills appear only when their routes answer.

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
   send -- IMAGE is one still through /api/generate/run on the picked
   model, VIDEO is the Create above -- and what was made is saved on the
   turn that made it (lib/composer.ts `Made`: the brain's answer when it
   made it, the person's own bubble when they pressed Make on the brief or
   the guide is off), so a still drawn here survives a trip to Pipeline. A
   send left running is picked up again on return (its job id is on the turn). */
import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowUp,
  ArrowUpFromLine,
  AtSign,
  ChevronDown,
  Ellipsis,
  Image as ImageIcon,
  ImageOff,
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
  getEffects,
  getRender,
  getCapabilities,
  getConceptDetail,
  createAsset,
  getPresets,
  getProject,
  getSkills,
  isProjectTool,
  pickConcept,
  recallActiveProject,
  rememberActiveProject,
  runCreativeGuide,
  runEffect,
  runGuideAction,
  runImage,
  runScenes,
  uploadRefs,
  waitForJob,
  workspaceHref,
  type Asset,
  type AssetHit,
  type Capabilities,
  type EffectsCatalogue,
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
  asProjectConversation,
  keepReferences,
  takePendingFill,
  type ContactSheet,
  type Turn,
} from "@/lib/assistant";
import { keepersOf } from "@/components/studio/contact-sheet";
import {
  BASE_COMMANDS,
  IMAGE_ASPECTS,
  MAKE_TOOLS,
  SHEET_MODEL,
  SHEET_TOOL,
  GENERATE_MODES,
  loadGenerateMode,
  saveGenerateMode,
  type GenerateMode,
  isEffectTool,
  isMake,
  isPlanTool,
  loadImageModel,
  loadOutput,
  matchCommands,
  mediaSrc,
  newMadeId,
  pollJob,
  saveImageModel,
  saveOutput,
  type Made,
  type MadeStatus,
  type Output,
  type SlashCommand,
} from "@/lib/composer";
import {
  approveAll,
  approveStep,
  blockedBy,
  editStep,
  finished,
  needsApproval,
  nextStep,
  patchStep,
  picturesFor,
  planOf,
  reconcile,
  restoreStep,
  sceneOf,
  skipStep,
  stepAt,
  stepText,
  type Plan,
  type PlanStep,
  type Prices,
} from "@/lib/make-plan";
import { failLine, madeStatus } from "@/lib/made-state";
import { begin, candidateOf, candidates, requestOf, type Candidate, type Effect, type EffectState } from "@/lib/effects";
import { assetId, sendCost, type ContinueAction } from "@/lib/continue";
import { EffectGallery } from "@/components/studio/effect-gallery";
import type { PlanHandlers } from "@/components/studio/make-plan-card";
import { ComposerStream, type Live } from "@/components/studio/composer/turns";
import { creditsText } from "@/lib/render-choice";
import { SlashMenu } from "@/components/studio/composer/slash-menu";
import { lookedOf, skillCommands, skillOfCommand, type Skill } from "@/lib/skills";
import "@/components/studio/composer/composer.css";
import { AssistantAvatar } from "@/components/studio/assistant-avatar";

/* an upload on its way to the bin: drawn from its object URL until the
   server answers with the URL the draft keeps */
type Pending = { id: string; name: string; url: string };
type Option = { id: string; label: string; note?: string };
/* the shelf under the box is ELEMENTS only -- the characters, props,
   products and places a person created to @ in a prompt (Mike's call,
   2026-09-15). Blank until one exists; the Assets wall's generated
   stills never appear here. */
type Filter = "all" | ElementKind;
/** What came of one make: its record's id, how it ended, and what it left. */
type MadeOut = { madeId: string; status: MadeStatus; conceptId?: number | null; image?: string | null; detail: string };

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
  const { brand, toast, balance } = useShell();
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
  const { turns: thread, setTurns: setThread, draft, setDraft, ready, finishProject, clearProject } = useAssistantThread();
  const router = useRouter();
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
  // an element deleted from the shelf took its frames off the box; an Undo
  // puts them back (keyed by element, until the toast closes)
  const unpicked = useRef(new Map<string, string[]>());
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<Asset | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [busy, setBusy] = useState(false);
  // the Guide's progress line while it answers (null = not answering)
  const [guideWorking, setGuideWorking] = useState<string | null>(null);
  // the Guide's answer as the model writes it (the job's `partial`), typed
  // into the stream until the turn lands with the same words
  const [guideWriting, setGuideWriting] = useState("");
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
  // which model draws a still (2026-10-04): the picker is GET /api/image-models,
  // the choice is remembered beside the output; "" until the route answers
  const [imageModels, setImageModels] = useState<(Option & { credits: number })[]>([]);
  const [imageModel, setImageModelState] = useState("");
  const setImageModel = (id: string) => {
    setImageModelState(id);
    saveImageModel(id);
  };
  // whether a still waits on its card's Approve; read after mount, like the output
  const [generate, setGenerateState] = useState<GenerateMode>("ask");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after mount
    setGenerateState(loadGenerateMode());
  }, []);
  const setGenerate = (mode: string) => {
    const m: GenerateMode = mode === "auto" ? "auto" : "ask";
    setGenerateState(m);
    saveGenerateMode(m);
  };
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState<Preset | null>(null);
  // the skill shelf (GET /api/skills), and the one picked for the next send
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skill, setSkill] = useState<Skill | null>(null);
  // the effects table (GET /api/effects), and whether its gallery is open
  const [fx, setFx] = useState<EffectsCatalogue | null>(null);
  const [fxOpen, setFxOpen] = useState(false);
  // an action taken on ONE result ("Animate" under a still, the Library's
  // Effects button): the gallery, and the card a pick makes, are bound to it
  const [fxOn, setFxOn] = useState<Candidate[] | null>(null);
  const [fxTab, setFxTab] = useState<string | undefined>(undefined);
  // "Make element" under a still: the add-element form, the still attached
  const [elementFrom, setElementFrom] = useState<Made | null>(null);
  const [slashAt, setSlashAt] = useState(0);
  // progress per running send, by made id -- page state, never saved: a
  // save per tick would be a PUT a second
  const [live, setLive] = useState<Record<string, Live>>({});
  // the send this page is waiting on (one at a time), and every made id
  // this page has a poll running for, so a resume never doubles one up
  const running = useRef<{ madeId: string; jobId?: number; stopped: boolean } | null>(null);
  const polling = useRef(new Set<string>());
  // PLANS (lib/make-plan.ts). A plan's loop awaits its steps one after
  // another, and the person may skip or edit a later step meanwhile -- so
  // the plan as it stands NOW is held here, and mirrored onto its turn.
  const plans = useRef(new Map<string, Plan>());
  const planLoops = useRef(new Set<string>());
  const planLive = useRef(new Map<string, number>());
  const threadRef = useRef<Turn[]>([]);
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
    getSkills()
      .then((r) => setSkills(r.items))
      .catch(() => setSkills([]));
    getEffects()
      .then(setFx)
      .catch(() => setFx(null));
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
    apiFetch<{ items: { id: string; label: string; note: string; credits: number }[]; default: string }>("/image-models")
      .then((r) => {
        const items = r.items.map((m) => ({ id: m.id, label: m.label, note: `${m.note} · ${m.credits} credits`, credits: m.credits }));
        setImageModels(items);
        const kept = loadImageModel();
        setImageModelState(items.some((m) => m.id === kept) ? kept : r.default);
      })
      .catch(() => setImageModels([]));
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
  // A NEW spark is applied again while the page is open (2026-10-08): the
  // ⌘K palette's "New project" and "Find references" arrive as ?spark= on
  // a Create that may already be showing, and they leave the caret at the
  // end of the box, ready for the rest of the sentence.
  const appliedSpark = useRef<string | null>(null);
  useEffect(() => {
    if (!ready) return;
    if (!paramsApplied.current) {
      if (attachId && attachPhotos === null) return; // its photos are still being looked up
      paramsApplied.current = true;
      if (attachPhotos?.length) setPicked((was) => [...new Set([...was, ...attachPhotos])]);
    }
    if (sparkParam && sparkParam !== appliedSpark.current) {
      appliedSpark.current = sparkParam;
      setIdea(sparkParam);
      setTimeout(() => {
        const box = textarea.current;
        if (!box) return;
        box.focus();
        box.setSelectionRange(box.value.length, box.value.length);
      }, 50);
    }
  }, [ready, sparkParam, attachId, attachPhotos, setIdea, setPicked]);

  // The Library's "Effects" lands here as ?on=gen:<id>: the gallery opens on
  // that render, which is how a clip the conversation never held (a Queue
  // render) gets finished. Applied once the gallery's table has loaded,
  // then taken off the address so a reload does not open it again.
  const onParam = params.get("on");
  const appliedOn = useRef<string | null>(null);
  useEffect(() => {
    if (!ready || !fx || !onParam || onParam === appliedOn.current) return;
    appliedOn.current = onParam;
    const id = assetId(onParam);
    const rest = new URLSearchParams(params.toString());
    rest.delete("on");
    router.replace(`/studio${rest.size ? `?${rest}` : ""}`, { scroll: false });
    if (id === null) return;
    getRender(id)
      .then((r) => {
        const clip = r.kind === "video";
        setFxOn([{ ref: r.ref, kind: clip ? "clip" : "image", thumb: (clip ? r.thumb : r.url) ?? undefined, from: "the render from your Library" }]);
        setFxTab(clip ? "finish" : "image_edit");
        setFxOpen(true);
      })
      .catch(() => toast("That render is not on your Library wall", "err"));
  }, [ready, fx, onParam, params, router, toast]);

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

  // The brain answers every send when the server says the route is there;
  // without it (no Gemini key) a send makes directly, the way it used to.
  const guideReady = caps.creative_guide === true;

  // the slash menu: the fixed commands, the skill shelf (only where there
  // is a brain to read one), and GET /api/presets as camera chips
  const commands = useMemo<SlashCommand[]>(
    () => [
      ...BASE_COMMANDS,
      ...(guideReady ? skillCommands(skills) : []),
      ...presets.map((p) => ({
        id: `preset:${p.id}`,
        cmd: p.id.replace(/[^\w-]+/g, "-").toLowerCase(),
        desc: p.label,
        group: "camera" as const,
      })),
    ],
    [presets, skills, guideReady],
  );
  const hasImage = thread.some((t) => t.made?.output === "image" && t.made.status === "done" && !!t.made.image);
  const slashItems = matchCommands(idea, commands, output, hasImage);

  // The newest turn is lifted clear of the docked box -- on the send, and
  // again when it finishes (a finished turn is taller). Without it a still
  // landed with its bottom under the box and nothing on screen said so.
  const lastMade = last?.made;
  // An answer being typed is lifted too, a line at a time.
  const writingLines = Math.ceil(guideWriting.length / 70);
  useEffect(() => {
    const stack = stackRef.current;
    const box = stack?.querySelector<HTMLElement>(".zc-box");
    const turn =
      stack?.querySelector<HTMLElement>(".zc-typing") ?? stack?.querySelector<HTMLElement>(".zc-turn:last-of-type");
    if (!box || !turn) return;
    const hidden = turn.getBoundingClientRect().bottom + 16 - box.getBoundingClientRect().top;
    if (hidden <= 0) return;
    window.scrollBy({ top: hidden, behavior: still ? "auto" : "smooth" });
  }, [thread.length, lastMade?.status, guideWorking, writingLines, still]);

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
  const canSend = !busy && !pending.length && !!(idea.trim() || brief.trim());
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
    async (madeId: string, output: Output, job: Job, inPlan = false): Promise<MadeOut> => {
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
        const why = job.error || "That run did not finish.";
        patchMade(madeId, { status: "failed", detail: why });
        toast(why, "err");
        return { madeId, status: "failed", detail: why };
      }
      // a composer send returns the concept it wrote (an id, never a cut uuid)
      const conceptId = typeof job.ref_id === "number" ? job.ref_id : null;
      const detail = conceptId ? await getConceptDetail(conceptId).catch(() => null) : null;
      if (output === "image") {
        const shots = detail?.shots ?? [];
        const image = detail?.reference_image || shots[shots.length - 1]?.reference_image || null;
        if (!image) {
          // the job "finished" because the row it rides on was saved; the
          // still is what was asked for, and it is not there (2026-10-10)
          const why = failLine(job.detail);
          patchMade(madeId, { status: "failed", conceptId, image: null, detail: why });
          toast(why, "err");
          return { madeId, status: "failed", conceptId, image: null, detail: why };
        }
        // its id on the Assets wall, so an effect can name it (lib/effects.ts)
        const asset = (job as unknown as { asset?: string | null }).asset ?? null;
        patchMade(madeId, { status: "done", conceptId, image, asset, detail: job.detail || "" });
        return { madeId, status: "done", conceptId, image, detail: job.detail || "" };
      }
      const timeline = detail?.timeline ?? detail?.shots?.[0]?.timeline ?? null;
      const said = job.detail || "on the board";
      patchMade(madeId, {
        status: "done",
        conceptId,
        detail: said,
        title: detail?.title,
        parts: timeline?.parts ?? [],
        seconds: timeline?.seconds ?? detail?.duration ?? null,
      });
      announceQueueChange();
      // a plan's scene is one step of several: the conversation, the box and
      // its references stay until the plan is through (runPlan clears them)
      if (inPlan) return { madeId, status: "done", conceptId, detail: said };
      // the conversation did its job: the scene is on the board with its
      // prompt and references, so the Guide talk, the brief and the box
      // go away (2026-10-02, Mike's call). The send's own turn stays --
      // it IS the "scene written" card here, with the timed shots under it.
      finishProject({ conceptId, detail: said });
      // a scene filed under a project is picked in its workspace; one made
      // outside any project has no board, only the tiles' Send to Queue
      toast(
        detail?.project_id
          ? "Scene written · it is in the project, ready to pick"
          : "Scene written · Send to Queue when you want it rendered",
      );
      return { madeId, status: "done", conceptId, detail: said };
    },
    [patchMade, toast, finishProject],
  );

  /* An effect's job, finished: the still or the clip it made lands on its
     turn, named by its render id so a later effect can act on it. */
  const finishEffect = useCallback(
    (madeId: string, job: Job) => {
      polling.current.delete(madeId);
      setLive((l) => {
        const n = { ...l };
        delete n[madeId];
        return n;
      });
      announceBalanceChange();
      const out = typeof job.output === "string" ? job.output : "";
      if (job.status !== "done" || !out) {
        const why = job.error || "The effect was not made. Nothing was charged.";
        patchMade(madeId, { status: "failed", detail: why });
        toast(why, "err");
        return;
      }
      const extra = job as unknown as { media?: string; asset?: string | null };
      patchMade(madeId, {
        status: "done",
        detail: job.detail || "",
        asset: extra.asset ?? null,
        ...(extra.media === "video" ? { clip: out, image: null } : { image: out, clip: null }),
      });
    },
    [patchMade, toast],
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
      const isEffect = !!m.effect;
      pollJob(m.jobId, (j) => tick(id, j), () => false)
        .then(async (job) => {
          if (!job) return;
          if (isEffect) finishEffect(id, job);
          else await finish(id, out, job);
        })
        .catch(() => {
          polling.current.delete(id);
          patchMade(id, { status: "failed", detail: "That run was lost (the server restarted while it ran)." });
        });
    }
  }, [ready, thread, patchMade, tick, finish, finishEffect]);

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
      setGuideWriting("");
      setFilledBy(null);
      setPreset(null);
      setSkill(null);
      plans.current.clear();
      planLive.current.clear();
      setTimeout(() => textarea.current?.focus(), 50);
    };
    window.addEventListener(NEW_SESSION_EVENT, on);
    return () => window.removeEventListener(NEW_SESSION_EVENT, on);
  }, [stop]);

  /* IMAGE and VIDEO makes: one turn each, one output each.

     `by` says whose turn carries the result: the BRAIN's one-line answer
     when it made the thing (a make_image / make_video proposal, with the
     prompt it wrote), or the PERSON's own bubble when they pressed Make on
     the brief or the guide is off. `on` overrides a setting the brain was
     asked for in so many words (an aspect, a length); the pills stay the
     controls otherwise. */
  async function make(
    text: string,
    out: Output,
    by:
      | { role: "user" }
      // `at`: the Approve card's own turn, which the still fills in place
      | { role: "assistant"; message: string; reply: GuideReply; at?: Turn },
    on: { aspect?: string; seconds?: number } = {},
    // a plan's step (lib/make-plan.ts): the pictures it is held to, and the
    // box, the brief and the conversation are left as they are
    step: { plan?: boolean; refs?: string[] } = {},
  ): Promise<MadeOut> {
    const madeId = newMadeId();
    const isImage = out === "image";
    const useAspect = on.aspect && IMAGE_ASPECTS.some((a) => a.id === on.aspect) ? on.aspect : aspect;
    const useSeconds = on.seconds && lengths ? Math.max(lengths.min, Math.min(lengths.max, on.seconds)) : seconds;
    const frame = isImage ? useAspect : ratios.find((r) => r.id === ratio)?.label;
    const refThumbs = [...uploads.map((u) => u.url), ...picked, ...(step.refs ?? [])].filter(drawable);
    const made: Made = {
      id: madeId,
      output: out,
      refs: refThumbs,
      status: "running",
      detail: "",
      frame,
      prompt: text,
      ...(isImage && imageModel ? { model: imageModel } : {}),
    };
    const approved = by.role === "assistant" ? by.at : undefined;
    setThread((ts) =>
      approved && ts.includes(approved)
        ? ts.map((x) => (x === approved ? { ...x, decided: "done" as const, made } : x))
        : [
            ...ts,
            by.role === "user"
              ? { role: "user", content: text, made }
              : {
                  role: "assistant",
                  content: by.message,
                  reply: by.reply,
                  decided: "done",
                  looked: lookedOf(by.reply.tool_runs, skills),
                  made,
                },
          ],
    );
    const me = { madeId, stopped: false } as { madeId: string; jobId?: number; stopped: boolean };
    running.current = me;
    polling.current.add(madeId);
    // the box and the brief are spent: what they held is in the prompt now.
    // Not on an Approve: the send that asked was earlier, and the box may
    // hold what the person is typing next.
    if (!approved && !step.plan) setDraft({ idea: "", brief: "" });

    const form = new FormData();
    if (brand) form.append("brand", brand);
    if (isImage) {
      form.append("prompt", text);
      form.append("output", "image");
      if (preset) form.append("preset", preset.id);
      form.append("aspect", useAspect);
      if (imageModel) form.append("image_model", imageModel);
    } else {
      // a camera preset is a line the writer reads, not a hidden field:
      // /scenes/run has no preset input, so it rides in the idea
      form.append("idea", preset ? `${text}\n\nCamera: ${preset.how}` : text);
      form.append("count", "1");
      if (brain) form.append("brain", brain);
      if (useSeconds) form.append("seconds", String(useSeconds));
      if (ratio) form.append("ratio", ratio);
      // written against the project's brief + memory and filed under it;
      // /generate/run takes no project, so a still is filed outside one
      if (project) form.append("project_id", String(project.id));
    }
    appendReferences(form);
    (step.refs ?? []).forEach((u) => form.append("asset_photos", u));

    const started = isImage ? await runImage(form) : await runScenes(form);
    me.jobId = started.job_id;
    patchMade(madeId, { jobId: started.job_id });
    const job = await pollJob(started.job_id, (j) => tick(madeId, j), () => me.stopped);
    if (!job) return { madeId, status: "stopped", detail: "" }; // stopped: stop() already drew it
    running.current = null;
    return finish(madeId, out, job, !!step.plan);
  }

  /* The conversation the brain answers: every turn that went through,
     including what was made -- a make is an assistant turn whose line is
     its words, and the model is told what came of it so "do it again but
     warmer" has something to refer to. */
  const conversationOf = (turns: Turn[]) =>
    turns
      .filter((m) => !m.failed)
      .map(({ role, content, made, plan, effect }) => ({
        role,
        content: effect
          ? `${content}\n[effect ${effect.label} — ${made ? madeStatus(made) : "waiting for approval"}]`
          : made
          ? `${content}\n[made ${made.output} from the prompt: "${made.prompt ?? content}" — ${madeStatus(made)}]`
          : plan
            ? `${content}\n[plan: ${plan.steps.map((s) => `${s.n} ${s.do} — ${s.status}`).join("; ")}]`
            : content,
      }));

  /* A still's step: the brain's answer turn carries the make_image
     proposal, and the still is drawn on its prompt into that same turn --
     on the card's Approve, or at once with Ask first off. A step whose
     still failed or was stopped can be approved again. */
  async function runStill(t: Turn) {
    const proposal = t.reply?.proposal;
    // a still that "finished" with nothing drawn can be approved again too
    const was = t.made ? madeStatus(t.made) : undefined;
    const again = was === "failed" || was === "stopped";
    if (!t.reply || !proposal || MAKE_TOOLS[proposal.tool] !== "image" || (t.made && !again)) return;
    const args = proposal.args as { prompt?: unknown; aspect?: unknown };
    const prompt = typeof args.prompt === "string" && args.prompt.trim() ? args.prompt.trim() : t.content;
    // a Variation is held to the pictures its first draw was held to; one
    // the box still holds is not sent twice
    const boxed = [...uploads.map((u) => u.url), ...picked];
    await make(
      prompt,
      "image",
      { role: "assistant", message: t.content, reply: t.reply, at: t },
      { aspect: typeof args.aspect === "string" ? args.aspect : undefined },
      { refs: (t.held ?? []).filter((u) => !boxed.includes(u)) },
    );
  }
  async function approveStill(i: number) {
    const t = thread[i];
    if (busy || !t) return;
    setBusy(true);
    try {
      await runStill(t);
    } catch (e) {
      failRun(e);
    } finally {
      setBusy(false);
    }
  }
  /* An element sheet's step (2026-10-09): save the person in the attached
     photos as a character -- the Elements create route, the composer's
     references handed over as photo_urls, sheet on -- then follow the
     sheet job the route started and land the sheet as this turn's tile.
     The route draws the sheet from THESE photos, not from an older folder
     under the same name. A sheet that failed can be approved again (the
     character is saved again under the same name; the photos are
     content-addressed, so the folder does not double). */
  async function runSheet(t: Turn): Promise<MadeOut | null> {
    const proposal = t.reply?.proposal;
    const again = t.made?.status === "failed" || t.made?.status === "stopped";
    if (!proposal || proposal.tool !== SHEET_TOOL || (t.made && !again)) return null;
    const photos = [...uploads.map((u) => u.url), ...picked];
    if (!photos.length) {
      toast("Attach photos of the person first -- the sheet is drawn from them", "err");
      return null;
    }
    const args = proposal.args as { name?: unknown; notes?: unknown };
    const name = typeof args.name === "string" && args.name.trim() ? args.name.trim() : "Character";
    const notes = typeof args.notes === "string" ? args.notes.trim() : "";
    const id = newMadeId();
    const made: Made = {
      id,
      output: "image",
      refs: photos.filter(drawable).slice(0, 8),
      status: "running",
      detail: `Saving ${name} to Elements…`,
      frame: "16:9",
      model: SHEET_MODEL,
      prompt: t.content,
    };
    setThread((all) => all.map((m) => (m === t ? { ...m, made } : m)));
    try {
      const form = new FormData();
      form.append("name", name);
      if (notes) form.append("notes", notes);
      form.append("sheet", "1");
      photos.forEach((u) => form.append("photo_urls", u));
      const saved = await createAsset("characters", form);
      if (!saved.sheet_job) {
        throw new Error(`${name} is saved in Elements, but ${saved.sheet_note || "the sheet could not start"}`);
      }
      patchMade(id, { jobId: saved.sheet_job, detail: `${name} saved · drawing the sheet…` });
      const job = await waitForJob(saved.sheet_job, (j) => tick(id, j));
      if (job.status !== "done" || !job.output) throw new Error(job.error || "The sheet was not drawn.");
      patchMade(id, { status: "done", image: job.output, detail: job.detail || `${name} · sheet drawn` });
      toast(`${name} saved to Elements with the sheet`);
      return { madeId: id, status: "done", image: job.output, detail: `${name} saved to Elements with the sheet` };
    } catch (e) {
      const why = e instanceof Error ? e.message : "The sheet was not drawn.";
      patchMade(id, { status: "failed", detail: why });
      toast(why, "err");
      return { madeId: id, status: "failed", detail: why };
    }
  }
  async function approveSheet(i: number) {
    const t = thread[i];
    if (busy || !t) return;
    setBusy(true);
    try {
      await runSheet(t);
    } finally {
      setBusy(false);
    }
  }
  // a sheet is one Nano Banana Pro still, priced like the Elements card's button
  const sheetLine = `Nano Banana Pro${balance?.prices ? ` · ${creditsText(balance.prices.still, !!balance.exempt)}` : ""}`;

  // what a step card says under its Approve: the model that draws the still
  // (the one it was drawn on, or the picker's as it stands) and what one costs
  const stillLine = (modelId?: string) => {
    const m = imageModels.find((x) => x.id === (modelId || imageModel)) ?? imageModels[0];
    if (!m) return "";
    return `${m.label} · ${balance?.exempt ? "not charged" : `${m.credits.toLocaleString()} credits`}`;
  };

  /* ── A PLAN (lib/make-plan.ts; docs/tasks/task-studio-agent.md item 2) ──
     Several makes in a row, proposed by the brain as one answer and run
     here in order through the doors each step always had: `make` for a
     still and a scene, `runSheet`, the keep, the keyframes approve, the
     pick. A step's result is its own turn under the plan's card. */
  useEffect(() => {
    threadRef.current = thread;
  }, [thread]);
  const getPlan = (id: string): Plan | null =>
    plans.current.get(id) ?? threadRef.current.find((t) => t.plan?.id === id)?.plan ?? null;
  const applyPlan = (id: string, fn: (p: Plan) => Plan): Plan | null => {
    const cur = getPlan(id);
    if (!cur) return null;
    const next = fn(cur);
    plans.current.set(id, next);
    setThread((ts) => ts.map((t) => (t.plan?.id === id ? { ...t, plan: next } : t)));
    return next;
  };

  // what a paid step costs on this account, for the card's totals
  const planPrices = useMemo<Prices>(
    () => ({
      image: balance?.exempt
        ? 0
        : ((imageModels.find((m) => m.id === imageModel) ?? imageModels[0])?.credits ?? null),
      sheet: balance?.exempt ? 0 : (balance?.prices?.still ?? null),
    }),
    [balance, imageModels, imageModel],
  );
  const planPriceLine = (st: PlanStep) => {
    if (st.do === "image") return stillLine();
    if (st.do === "sheet") return sheetLine;
    if (typeof st.credits !== "number") return "Priced once the scene is written";
    const n = st.stills ?? 0;
    return `${n} still${n === 1 ? "" : "s"} · ${creditsText(st.credits, !!balance?.exempt)}`;
  };

  /* After a reload, or when a step's own card ran it again: each step
     follows the turn its result was drawn into. */
  useEffect(() => {
    if (!ready) return;
    const mades: Record<string, { status: string; image?: string | null; conceptId?: number | null }> = {};
    for (const t of thread) {
      if (t.made) mades[t.made.id] = { status: madeStatus(t.made), image: t.made.image, conceptId: t.made.conceptId };
    }
    for (const t of thread) {
      if (!t.plan) continue;
      const cur = plans.current.get(t.plan.id) ?? t.plan;
      const live = planLive.current.get(cur.id);
      const next = reconcile(cur, mades, live ? [live] : []);
      if (next !== cur) {
        plans.current.set(cur.id, next);
        setThread((ts) => ts.map((x) => (x.plan?.id === cur.id ? { ...x, plan: next } : x)));
      }
    }
  }, [ready, thread, setThread]);

  const outOf = (out: MadeOut | null, what: "image" | "scene"): Partial<PlanStep> => {
    if (!out) return { status: "failed", note: "it did not start" };
    // stopped by the person: the step waits, it did not fail
    if (out.status === "stopped") return { status: "pending", madeId: out.madeId, note: "stopped" };
    const made = what === "scene" ? !!out.conceptId : !!out.image;
    return out.status === "done" && made
      ? { status: "done", madeId: out.madeId, image: out.image ?? null, conceptId: out.conceptId ?? null, note: undefined }
      : { status: "failed", madeId: out.madeId, note: out.detail || "it did not finish" };
  };

  /* A scene's keyframes are priced once the scene exists: the step reads
     its quote here, and is done already when every shot has its frame. */
  async function priceKeyframes(plan: Plan, st: PlanStep): Promise<Partial<PlanStep>> {
    const scene = sceneOf(plan, st);
    if (!scene?.conceptId) return { status: "failed", note: "there is no scene to draw them for" };
    try {
      const quote = (await getConceptDetail(scene.conceptId)).keyframes;
      if (!quote || !quote.stills) {
        return { status: "done", credits: 0, stills: 0, note: "every shot already has its first frame" };
      }
      // the real price even on an account that is not charged: the card
      // says "30 credits · not charged", as the Queue does
      return { credits: quote.credits, stills: quote.stills };
    } catch (e) {
      return { status: "failed", note: e instanceof Error ? e.message : "the price could not be read" };
    }
  }

  async function runPlanStep(planId: string, st: PlanStep): Promise<Partial<PlanStep>> {
    const plan = getPlan(planId);
    if (!plan) return { status: "failed", note: "the plan is gone" };
    try {
      if (st.do === "image") {
        const prompt = typeof st.args.prompt === "string" ? st.args.prompt : "";
        const aspect = typeof st.args.aspect === "string" ? st.args.aspect : undefined;
        const reply: GuideReply = {
          message: prompt,
          proposal: { tool: "make_image", args: { prompt, ...(aspect ? { aspect } : {}) }, label: "Generate this image" },
        };
        // a step run again is drawn into the turn it failed in, not a new one
        const prior = st.madeId ? threadRef.current.find((t) => t.made?.id === st.madeId) : undefined;
        const out = await make(
          prompt,
          "image",
          { role: "assistant", message: prompt, reply, ...(prior ? { at: prior } : {}) },
          { aspect },
          { plan: true, refs: picturesFor(plan, st) },
        );
        return outOf(out, "image");
      }
      if (st.do === "scene") {
        const prompt = typeof st.args.prompt === "string" ? st.args.prompt : "";
        const line = st.why || "Writing the scene";
        const reply: GuideReply = { message: line, proposal: { tool: "make_video", args: st.args, label: "Write this scene" } };
        const out = await make(
          prompt,
          "video",
          { role: "assistant", message: line, reply },
          { seconds: typeof st.args.seconds === "number" ? st.args.seconds : undefined },
          { plan: true, refs: picturesFor(plan, st) },
        );
        return outOf(out, "scene");
      }
      if (st.do === "sheet") {
        const line = stepText(plan, st);
        const turn: Turn = {
          role: "assistant",
          content: line,
          reply: {
            message: line,
            proposal: { tool: SHEET_TOOL, args: st.args, label: "Save as a character and draw the reference sheet" },
          },
        };
        setThread((all) => [...all, turn]);
        const out = await runSheet(turn);
        if (!out) return { status: "failed", note: "attach photos of the person first: the sheet is drawn from them" };
        return out.status === "done"
          ? { status: "done", madeId: out.madeId, image: out.image ?? null, note: out.detail }
          : { status: "failed", madeId: out.madeId, note: out.detail };
      }
      if (st.do === "keep") {
        const ids = Array.isArray(st.args.candidate_ids) ? st.args.candidate_ids.filter((x): x is string => typeof x === "string") : [];
        const res = await keepReferences(ids);
        const urls = res.result.kept.map((k) => k.url);
        if (urls.length) setPicked((was) => [...new Set([...was, ...urls])]);
        const refused = res.result.refused.length;
        return urls.length
          ? { status: "done", note: `${urls.length} added to the box${refused ? ` · ${refused} could not be kept` : ""}` }
          : { status: "failed", note: "none of those frames could be kept" };
      }
      const scene = sceneOf(plan, st);
      if (!scene?.conceptId) return { status: "failed", note: "there is no scene for it" };
      if (st.do === "keyframes") {
        const started = await drawKeyframes(scene.conceptId);
        if (started.job_id) {
          const job = await waitForJob(started.job_id, () => {});
          if (job.status !== "done") throw new Error(job.error || "The keyframes were not drawn.");
        }
        announceBalanceChange();
        // the scene's tiles show the frames now
        const detail = await getConceptDetail(scene.conceptId).catch(() => null);
        const parts = detail?.timeline?.parts ?? detail?.shots?.[0]?.timeline?.parts;
        if (scene.madeId && parts) patchMade(scene.madeId, { parts });
        const n = started.keyframes?.stills ?? st.stills ?? 0;
        return { status: "done", note: `${n} first frame${n === 1 ? "" : "s"} drawn` };
      }
      await pickConcept(scene.conceptId, true);
      announceQueueChange();
      return { status: "done", note: "in the Queue: approving there renders it" };
    } catch (e) {
      // a make that threw before its job started still has its record
      failRun(e);
      return { status: "failed", note: e instanceof Error ? e.message : "it did not finish" };
    }
  }

  /* Run a plan from its first unfinished step. Free steps run on; a step
     that costs credits stops for its Approve (with Ask first on, unless it
     was approved ahead); the first failure stops the plan where it is. */
  async function runPlan(id: string, how: { approve?: number; all?: boolean } = {}) {
    if (planLoops.current.has(id)) return;
    planLoops.current.add(id);
    setBusy(true);
    try {
      applyPlan(id, (p) => {
        let next: Plan = { ...p, started: true, stopped: false };
        if (how.all) next = approveAll(next, planPrices);
        if (how.approve) next = approveStep(next, how.approve);
        return next;
      });
      for (;;) {
        const plan = getPlan(id);
        if (!plan || plan.stopped) break;
        let st = nextStep(plan);
        if (!st) break;
        const n = st.n;
        const blocked = blockedBy(plan, st);
        if (blocked) {
          applyPlan(id, (p) => patchStep(p, n, { status: "skipped", note: blocked }));
          continue;
        }
        if (st.do === "keyframes" && typeof st.credits !== "number") {
          const priced = await priceKeyframes(plan, st);
          applyPlan(id, (p) => patchStep(p, n, priced));
          if (priced.status === "done") continue;
          if (priced.status === "failed") break;
          st = { ...st, ...priced };
        }
        const now = getPlan(id);
        if (!now || now.stopped) break;
        if (needsApproval(now, st, generate)) {
          applyPlan(id, (p) => patchStep(p, n, { status: "waiting", note: undefined }));
          break;
        }
        planLive.current.set(id, n);
        applyPlan(id, (p) => patchStep(p, n, { status: "running", note: undefined }));
        const out = await runPlanStep(id, st);
        planLive.current.delete(id);
        applyPlan(id, (p) => patchStep(p, n, out));
        if (out.status !== "done") break;
      }
      const end = getPlan(id);
      const wrote = end?.steps.find((x) => x.do === "scene" && x.status === "done" && x.conceptId);
      if (end && finished(end) && wrote && !end.closed) {
        // the plan is through and a scene is written: the talk, the brief
        // and the box go away as they do after any scene; the plan and what
        // it made stay (assistant-thread finishProject). Once only: a step
        // edited and run again later must not empty the box a second time.
        applyPlan(id, (p) => ({ ...p, closed: true }));
        finishProject({ conceptId: wrote.conceptId ?? null, detail: "plan finished" });
      }
    } finally {
      planLive.current.delete(id);
      planLoops.current.delete(id);
      setBusy(false);
    }
  }
  function stopPlan(id: string) {
    applyPlan(id, (p) => ({ ...p, stopped: true }));
    stop(); // ends the wait on a make that is running; its hold is released
  }
  const planHandlers = (id: string): PlanHandlers => ({
    busy,
    mode: generate,
    prices: planPrices,
    exempt: !!balance?.exempt,
    priceLine: planPriceLine,
    onStart: (all) => void runPlan(id, { all }),
    onApprove: (n) => void runPlan(id, { approve: n }),
    onEdit: (n, prompt) => void applyPlan(id, (p) => editStep(p, n, { prompt })),
    onSkip: (n) => {
      const was = getPlan(id);
      const waiting = stepAt(was ?? { id, summary: "", steps: [], approved: [] }, n)?.status === "waiting";
      applyPlan(id, (p) => skipStep(p, n));
      // skipping the step the plan was waiting on lets it carry on
      if (waiting) void runPlan(id);
    },
    onRestore: (n) => void applyPlan(id, (p) => restoreStep(p, n)),
    onStop: () => stopPlan(id),
  });

  /* ── AN EFFECT (lib/effects.ts; item 3) ──
     Change something that already exists. What there is to act on: the
     images attached to the box, then the thread's results, newest first. */
  const fxCandidates = useMemo(
    () =>
      candidates(
        [...uploads.map((u) => u.url), ...picked],
        thread
          .filter((t) => t.made && madeStatus(t.made) === "done")
          .map((t) => ({ image: t.made?.clip ? null : t.made?.image, clip: t.made?.clip, asset: t.made?.asset })),
      ),
    [uploads, picked, thread],
  );
  // a pick from the gallery: a card in the thread, and nothing has run
  function startEffect(item: Effect) {
    const state = begin(item, fxCandidates, newMadeId(), { on: fxOn });
    setThread((all) => [...all, { role: "assistant", content: item.label, effect: state }]);
    closeEffects();
  }
  /* The gallery, opened plainly (`/effects`) or ON one result: then it
     lists what that result can take, and a pick is bound to it. */
  function openEffects(on?: Candidate[] | null, tab?: string) {
    setFxOn(on?.length ? on : null);
    setFxTab(tab);
    setFxOpen(true);
  }
  function closeEffects() {
    setFxOpen(false);
    setFxOn(null);
    setFxTab(undefined);
  }
  const changeEffect = (next: EffectState) =>
    setThread((all) => all.map((t) => (t.effect?.id === next.id && !isRunning(t) ? { ...t, effect: next } : t)));
  const isRunning = (t: Turn) => t.made?.status === "running";
  /* The card's Approve: the click that spends, at the price it showed. */
  async function approveEffect(id: string, credits: number, charged: boolean) {
    const turn = threadRef.current.find((t) => t.effect?.id === id);
    const state = turn?.effect;
    if (!state || busy || (turn?.made && isRunning(turn))) return;
    const madeId = newMadeId();
    const made: Made = {
      id: madeId,
      output: "image",
      refs: state.sources.map((x) => x.thumb ?? "").filter(drawable),
      status: "running",
      detail: `${state.label}…`,
      prompt: state.prompt,
      effect: state.effect,
      model: state.effect,
    };
    setBusy(true);
    setThread((all) =>
      all.map((t) => (t.effect?.id === id && t.effect ? { ...t, made, effect: { ...t.effect, paid: { credits, charged } } } : t)),
    );
    polling.current.add(madeId);
    try {
      const started = await runEffect({ ...requestOf(state), expect_credits: credits });
      patchMade(madeId, { jobId: started.job_id });
      const job = await waitForJob(started.job_id, (j) => tick(madeId, j));
      finishEffect(madeId, job);
    } catch (e) {
      // refused before anything ran (a price that moved, a source that is
      // gone): the card goes back to waiting and prices itself again
      polling.current.delete(madeId);
      setThread((all) =>
        all.map((t) => (t.effect?.id === id && t.effect ? { ...t, made: undefined, effect: { ...t.effect, paid: undefined } } : t)),
      );
      toast(e instanceof Error ? e.message : "That did not go through.", "err");
    } finally {
      setBusy(false);
    }
  }

  /* Make from the brief: the person's own click on the card the brain
     wrote, so it rides on their turn. */
  async function makeBrief() {
    if (!brief.trim() || busy) return;
    setBusy(true);
    try {
      await make(brief.trim(), output, { role: "user" });
    } catch (e) {
      failRun(e);
    } finally {
      setBusy(false);
    }
  }
  const failRun = (e: unknown) => {
    const r = running.current;
    if (r && !r.stopped) {
      polling.current.delete(r.madeId);
      patchMade(r.madeId, { status: "failed", detail: e instanceof Error ? e.message : "That did not go through." });
      running.current = null;
    }
    toast(e instanceof Error ? e.message : "That did not go through.", "err");
  };

  async function send() {
    if (!canSend) return;
    setBusy(true);
    setFilledBy(null);
    let asking: Turn | null = null;
    try {
      const asked = idea.trim();
      if (!guideReady || !asked) {
        // no brain to ask (no key), or nothing typed but a brief to make
        // from: make directly, on the person's own turn
        await make(asked || brief.trim(), output, { role: "user" });
      } else {
        // the skill picked from the `/` menu rides on THIS send only
        const using = skill;
        const mine: Turn = { role: "user", content: asked, ...(using ? { skill: using.title } : {}) };
        const next = [...conversationOf(thread), { role: mine.role, content: mine.content }];
        asking = mine;
        setThread((all) => [...all, mine]);
        setIdea("");
        setGuideWorking("Thinking…");
        const form = new FormData();
        form.append("conversation", JSON.stringify({ messages: next }));
        if (brand) form.append("brand", brand);
        form.append("guide_provider", "gemini");
        form.append("idea", asked);
        // the Image | Video switch: which thing a "make it" makes
        form.append("output", output);
        if (using) form.append("skill", using.name);
        if (project) form.append("project_id", String(project.id));
        // The Fast / Reasoning pill. Without it the Guide answered every
        // turn on the reasoning tier -- ~1.5c a message for "which
        // direction?". Server clamps it; absent means Fast.
        if (brain) form.append("brain", brain);
        // The same photos a make carries: the guide grounds on them
        // (scene_chain.ground) and the model is shown them, so it can
        // answer about a face instead of asking where the photos are.
        appendReferences(form);
        // runCreativeGuide, never a bare fetch: the route is behind
        // mutation_header and a call without GUARDED_HEADERS is refused 403.
        const started = await runCreativeGuide(form);
        // polled faster once its words are arriving, so the typing keeps up
        const job = await waitForJob(
          started.job_id,
          (j) => {
            setGuideWorking(j.detail || "Considering your direction…");
            setGuideWriting(j.status === "running" ? (j.partial ?? "") : "");
          },
          (j) => (j.partial ? 500 : 1500),
        );
        const reply = (job as unknown as { reply?: GuideReply }).reply;
        if (job.status !== "done" || !reply) throw new Error(job.error || "The guide stopped.");
        setGuideWorking(null);
        setGuideWriting("");
        // answered: the skill was for that message. A turn that failed
        // keeps the chip, beside the words handed back to the box.
        if (using) setSkill((now) => (now === using ? null : now));
        const looked = lookedOf(reply.tool_runs, skills);
        const proposal = reply.proposal;
        if (proposal && MAKE_TOOLS[proposal.tool] === "image") {
          // A STILL SPENDS: the answer is its step card -- held on Approve
          // with Ask first on, drawn at once with it off
          if (output !== "image") setOutput("image");
          const step: Turn = { role: "assistant", content: reply.message, reply, looked };
          setThread((all) => [...all, step]);
          if (generate === "auto") await runStill(step);
        } else if (proposal && proposal.tool === SHEET_TOOL) {
          // AN ELEMENT SHEET (2026-10-09): its step card, held on Approve
          // with Ask first on, saved and drawn at once with it off
          const step: Turn = { role: "assistant", content: reply.message, reply, looked };
          setThread((all) => [...all, step]);
          if (generate === "auto") await runSheet(step);
        } else if (proposal && isEffectTool(proposal.tool)) {
          // AN EFFECT (lib/effects.ts): the brain named the effect, its
          // options and its words; what it acts on is bound here. Its card
          // waits for Approve beside its price, whatever the mode -- the
          // price is only known once the card has asked for it.
          const args = proposal.args as { effect?: unknown; options?: unknown; prompt?: unknown };
          const item = fx?.items.find((e) => e.id === args.effect);
          if (!item) {
            setThread((all) => [...all, { role: "assistant", content: reply.message, looked }]);
          } else {
            const state = begin(item, fxCandidates, newMadeId(), {
              options: args.options && typeof args.options === "object" ? (args.options as Record<string, unknown>) : null,
              prompt: typeof args.prompt === "string" ? args.prompt : "",
            });
            setThread((all) => [...all, { role: "assistant", content: reply.message, reply, looked, effect: state }]);
          }
        } else if (proposal && isPlanTool(proposal.tool)) {
          // A PLAN (lib/make-plan.ts): several makes in a row, as a
          // checklist. With Ask first on it waits for Start; with it off it
          // runs, as a single make would.
          const plan = planOf(proposal.args, newMadeId());
          if (!plan) {
            // not a plan a card can draw: its line stands as words
            setThread((all) => [...all, { role: "assistant", content: reply.message, looked }]);
          } else {
            plans.current.set(plan.id, plan);
            setThread((all) => [...all, { role: "assistant", content: reply.message, reply, looked, plan }]);
            if (generate === "auto") await runPlan(plan.id);
          }
        } else if (proposal && isMake(proposal.tool)) {
          // THE BRAIN MADE: its line is the turn, the tiles go under it.
          // The tool says which output -- the switch follows it, so a
          // "make that a video" lands where the person will look next.
          const made = MAKE_TOOLS[proposal.tool];
          if (made !== output) setOutput(made);
          const args = proposal.args as { prompt?: unknown; aspect?: unknown; seconds?: unknown };
          const prompt = typeof args.prompt === "string" && args.prompt.trim() ? args.prompt.trim() : asked;
          await make(prompt, made, { role: "assistant", message: reply.message, reply }, {
            aspect: typeof args.aspect === "string" ? args.aspect : undefined,
            seconds: typeof args.seconds === "number" ? args.seconds : undefined,
          });
        } else {
          // appended to whatever the thread holds NOW: the pill shares it and
          // may have added a turn while this one was out
          setThread((all) => [
            ...all,
            {
              role: "assistant",
              content: reply.message,
              reply,
              looked,
              chosen: keepersOf(reply.sheet),
            },
          ]);
          if (reply.brief) setBrief(reply.brief);
        }
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
      failRun(e);
    } finally {
      setGuideWorking(null);
      setGuideWriting("");
      setBusy(false);
    }
  }

  /* the slash menu: every command changes something visible */
  function runCommand(c: SlashCommand) {
    setIdea("");
    setSlashAt(0);
    if (c.id === "image" || c.id === "video") {
      setOutput(c.id);
    } else if (c.id === "animate") {
      const lastImage = [...thread].reverse().find((t) => t.made?.output === "image" && t.made.status === "done" && t.made.image);
      if (lastImage?.made) animate(lastImage.made);
      return;
    } else if (c.id === "effects") {
      openEffects();
      return;
    } else if (c.id === "ref") {
      fileInput.current?.click();
    } else if (c.id === "element") {
      setIdea("@");
    } else if (c.id.startsWith("preset:")) {
      const p = presets.find((x) => `preset:${x.id}` === c.id);
      if (p) setPreset(p);
    } else if (c.group === "skill") {
      // a chip on the box, and the switch follows what the skill ends in
      const picked = skillOfCommand(c.id, skills);
      if (picked) {
        setSkill(picked);
        if (picked.output) setOutput(picked.output);
      }
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
    textarea.current?.focus();
    toast("Image attached · describe how the shot moves");
  }
  /* A Variation: the same prompt, frame and references, drawn again. It is
     a still's step like any other -- a card with its price that waits for
     Approve (or draws at once with Auto on), on the model the picker shows. */
  function variation(m: Made) {
    const prompt = (m.prompt ?? "").trim();
    if (!prompt || busy) return;
    const shape = IMAGE_ASPECTS.some((a) => a.id === m.frame) ? m.frame : undefined;
    const reply: GuideReply = {
      message: prompt,
      proposal: { tool: "make_image", args: { prompt, ...(shape ? { aspect: shape } : {}) }, label: "Generate this image" },
    };
    const step: Turn = { role: "assistant", content: prompt, reply, held: m.refs };
    setThread((all) => [...all, step]);
    if (generate !== "auto") return;
    setBusy(true);
    runStill(step)
      .catch(failRun)
      .finally(() => setBusy(false));
  }
  /* A "continue" action under a result (lib/continue.ts). The ones that
     are links -- Download, the Library, the editor, the canvas -- are
     drawn as links and never come here. */
  function continueOn(t: Turn, a: ContinueAction) {
    const m = t.made;
    if (!m) return;
    const self = candidateOf({ image: m.clip ? null : m.image, clip: m.clip, asset: m.asset }, m.clip ? "this clip" : "this still");
    if (a.kind === "effect") {
      const item = fx?.items.find((e) => e.id === a.effect);
      if (!item || !self) return;
      const state = begin(item, fxCandidates, newMadeId(), { on: [self] });
      setThread((all) => [...all, { role: "assistant", content: item.label, effect: state }]);
    } else if (a.kind === "gallery") openEffects(self ? [self] : null, a.tab);
    else if (a.kind === "variation") variation(m);
    else if (a.kind === "shot") animate(m);
    else if (a.kind === "reference") attachResult(m);
    else if (a.kind === "element") setElementFrom(m);
    else if (a.kind === "queue") void sendMadeToQueue(m);
    else if (a.kind === "reuse") reuse(t);
  }
  /* "Reuse prompt" fills the box; it never spends on its own */
  function reuse(t: Turn) {
    if (t.made) setOutput(t.made.output);
    setIdea(t.made?.prompt ?? t.content);
    textarea.current?.focus();
  }
  const select = (madeId: string, n: number) => patchMade(madeId, { shot: n });

  /* Send to Queue, off a written scene's tiles: the PICK, which is all it
     is -- approving in the Queue is what renders (2026-10-07). It replaced
     "Pick on Pipeline": a scene made outside any project has no board, and
     one inside a project is picked in its workspace or here. */
  async function sendMadeToQueue(m: Made) {
    if (!m.conceptId || busy) return;
    try {
      await pickConcept(m.conceptId, true);
      announceQueueChange();
      toast("In the Queue — approving there renders it");
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through.", "err");
    }
  }

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
      // save_as_project files this conversation and the scenes its sends
      // made into the new project (2026-10-07); the thread is the project's
      // history after that, so it is cleared here and opened there
      const done = await runGuideAction(
        proposal,
        proposal.tool === "save_as_project" ? asProjectConversation(thread.slice(0, i)) : undefined,
      );
      if (done.project && isProjectTool(proposal.tool)) {
        setThread((t) => t.map((m, j) => (j === i ? { ...m, decided: "done" as const } : m)));
        toast(`“${done.project.title}” is on the Projects board`);
        if (proposal.tool === "save_as_project") await clearProject().catch(() => {});
        router.push(workspaceHref(done.project.id));
        return;
      }
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
  const sendLabel = "Send";
  // what THIS send can spend without another click (lib/continue.ts):
  // nothing, unless a still is drawn on the send
  const cost = sendCost({
    guide: guideReady,
    output,
    generate,
    stillCredits: (imageModels.find((m) => m.id === imageModel) ?? imageModels[0])?.credits ?? null,
    exempt: !!balance?.exempt,
  });
  const placeholder = guideReady
    ? output === "image"
      ? empty
        ? "Describe an image, or talk the idea through…"
        : "Refine, vary, ask, or describe the next image…"
      : empty
        ? "Describe a scene, or talk the idea through…"
        : "Refine, extend, ask, or describe the next shot…"
    : output === "image"
      ? "Describe an image, a look, or a still…"
      : "Describe a shot, scene, or sequence…";
  const starters: { label: string; run: () => void }[] = [
    ...(guideReady
      ? [
          {
            label: "Pitch a concept",
            run: () => {
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
        setIdea("Storyboard a scene: ");
        textarea.current?.focus();
      },
    },
    { label: "Match a reference look", run: () => fileInput.current?.click() },
    {
      label: "Turn a still into a shot",
      run: () => {
        setOutput("video");
        fileInput.current?.click();
      },
    },
  ];
  const frameLabel = ratios.find((r) => r.id === ratio)?.label ?? "Frame";
  const brainLabel = brains.find((b) => b.id === brain)?.label ?? "Model";
  const imageModelLabel = imageModels.find((m) => m.id === imageModel)?.label ?? "Model";
  const modelLabel = (id?: string) =>
    id === SHEET_MODEL
      ? "Element sheet · Nano Banana Pro"
      : (imageModels.find((m) => m.id === id)?.label ?? fx?.items.find((e) => e.id === id)?.label);

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
              writing={guideWriting}
              handlers={{
                busy,
                modelLabel,
                onContinue: continueOn,
                continueHas: { effects: fx?.items.map((e) => e.id) ?? [], ready: !!fx?.ready },
                onSelect: select,
                onChip: (c) => {
                  setIdea(c);
                  textarea.current?.focus();
                },
                onDecide: decide,
                onPick: sendMadeToQueue,
                onApprove: (i) => void approveStill(i),
                stillLine,
                onApproveSheet: (i) => void approveSheet(i),
                sheetLine,
                plan: planHandlers,
                effectItem: (effectId) => fx?.items.find((e) => e.id === effectId),
                effectExempt: !!fx?.exempt,
                onEffectChange: changeEffect,
                onEffectApprove: (id, credits, charged) => void approveEffect(id, credits, charged),
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

            {referenceCount || preset || skill ? (
              <div className="zc-chips">
                {skill ? (
                  <span className="zc-chip preset skill" title={skill.summary}>
                    <span className="zc-chip-kind">Skill</span>
                    <span className="zc-chip-name">{skill.title}</span>
                    <button type="button" aria-label={`Remove the ${skill.title} skill`} onClick={() => setSkill(null)}>
                      <X strokeWidth={2} />
                    </button>
                  </span>
                ) : null}
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
                {fxOpen && fx ? (
                  <EffectGallery
                    key={`effects:${fxTab ?? ""}:${fxOn?.[0]?.ref ?? ""}`}
                    effects={fx.items}
                    categories={fx.categories}
                    ready={fx.ready}
                    exempt={fx.exempt}
                    candidates={fxOn ?? fxCandidates}
                    on={fxOn?.[0]?.from}
                    tab={fxTab}
                    onPick={startEffect}
                    onClose={closeEffects}
                  />
                ) : null}
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
              // The brain's brief, editable, with the one button that makes
              // from it without another turn -- the person's own click, so
              // the result rides on their bubble.
              <div className="cbrief">
                <span className="m" style={{ fontSize: 8.5, display: "block", marginBottom: 6 }}>
                  Brief from the brain · editable · Make draws from this, not from the box
                </span>
                <textarea value={brief} onChange={(e) => setBrief(e.target.value)} rows={5} />
                <button type="button" className="pill chosen cbrief-go" disabled={busy || !!pending.length} onClick={() => void makeBrief()}>
                  <Play strokeWidth={1.6} />
                  {output === "image" ? "Make this image" : "Write this scene"}
                </button>
              </div>
            ) : null}

            <div className="zc-tools">
              <span className="zc-seg" role="radiogroup" aria-label="What to make">
                <button type="button" role="radio" aria-checked={output === "image"} onClick={() => setOutput("image")}>
                  <ImageIcon strokeWidth={1.6} /> Image
                </button>
                <button type="button" role="radio" aria-checked={output === "video"} onClick={() => setOutput("video")}>
                  <Video strokeWidth={1.6} /> Video
                </button>
              </span>
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
                {output === "image" ? (
                  <OptMenu heading="Image shape" value={aspect} onChange={setAspect} options={IMAGE_ASPECTS} label={aspect} />
                ) : null}
                {output === "image" && imageModels.length ? (
                  <>
                    <span className="zc-dot" aria-hidden>
                      ·
                    </span>
                    <OptMenu
                      heading="Which model draws"
                      value={imageModel}
                      onChange={setImageModel}
                      options={imageModels}
                      label={imageModelLabel}
                      chevron
                    />
                  </>
                ) : null}
                {output === "video" && ratios.length ? (
                  <OptMenu heading="Frame" value={ratio} onChange={setRatio} options={ratios} label={frameLabel} />
                ) : null}
                {output === "video" && lengths ? (
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
                      heading={guideReady ? "Which model thinks" : "Which model writes"}
                      value={brain}
                      onChange={setBrain}
                      options={brains}
                      label={brainLabel}
                      chevron
                    />
                  </>
                ) : null}
                {guideReady ? (
                  <>
                    <span className="zc-dot" aria-hidden>
                      ·
                    </span>
                    <OptMenu
                      heading="Before a still is drawn"
                      value={generate}
                      onChange={setGenerate}
                      options={GENERATE_MODES}
                      label={generate === "ask" ? "Ask first" : "Auto"}
                      chevron
                    />
                  </>
                ) : null}
              </span>
              <span className="spacer" />
              {filledBy && idea.trim() ? (
                <span className="zpa-filled">
                  {filledBy.avatar ? <AssistantAvatar avatar={filledBy.avatar} size="xs" className="zpa-filled-face" /> : null}
                  Filled by {filledBy.name}
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
                  {cost.credits !== null ? (
                    <span className="zc-cost" title={cost.line}>
                      {cost.credits.toLocaleString()} credits
                    </span>
                  ) : null}
                <motion.button
                  type="button"
                  className={`zc-send${filledBy && idea.trim() ? " zpa-ring" : ""}`}
                  disabled={!canSend}
                  aria-label={`${sendLabel}. ${cost.line}`}
                  title={`${sendLabel} (Enter) · ${cost.line}`}
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
            // the delete is held behind an Undo: hide it here rather than
            // re-read a listing that still has it
            setAssets((was) => was.filter((x) => x.id !== a.id));
            const dropped = picked.filter((u) => a.photos.includes(u));
            unpicked.current.set(a.id, dropped);
            setPicked((was) => was.filter((u) => !a.photos.includes(u)));
          }}
          onRestored={(a) => {
            // Undo: nothing was deleted -- the shelf reads it back and the
            // frames it took off the box go back on
            const dropped = unpicked.current.get(a.id) ?? [];
            unpicked.current.delete(a.id);
            if (dropped.length) setPicked((was) => [...new Set([...was, ...dropped])]);
            void loadAssets();
          }}
        />
      ) : null}

      {elementFrom?.image ? (
        <AddElement
          title="Make element"
          initialPhotoUrls={[elementFrom.image]}
          initialNotes={elementFrom.prompt ?? ""}
          onClose={() => setElementFrom(null)}
          onSaved={(name, photos, note, sheetJob) => {
            setElementFrom(null);
            toast(
              `${name} saved as an element · ${photos} photo${photos === 1 ? "" : "s"}${sheetJob ? " · drawing its sheet" : ""}${note ? ` · ${note}` : ""}`,
            );
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
