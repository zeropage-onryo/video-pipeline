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
   likewise appear only when their routes answer.

   NOTHING IN THE BOX IS THIS PAGE'S TO LOSE (2026-10-02). The Guide
   thread, the idea, the brief, the references and the "scene written"
   card used to be React state here, so clicking to Pipeline and back
   threw the conversation and every frame a hunt had drawn away. They are
   the studio's now: the thread is the same one the assistant pill talks
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
   button clears it the same way. Nothing is archived. */
import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
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
  announceBalanceChange,
  announceQueueChange,
  getAssets,
  getCapabilities,
  runCreativeGuide,
  getProject,
  recallActiveProject,
  rememberActiveProject,
  type Project,
  runScenes,
  uploadRefs,
  waitForJob,
  type Asset,
  type AssetHit,
  type Capabilities,
  runGuideAction,
  type GuideReply,
} from "@/lib/studio-api";
import { useMentions } from "@/components/studio/mentions";
import { useShell } from "@/components/studio/shell";
import { useAssistantThread } from "@/components/studio/assistant-thread";
import { AddElement } from "@/components/studio/add-element";
import { ElementSheet } from "@/components/studio/element-sheet";
import { ELEMENT_KINDS, displayPhoto, drawable, elementKind, isElement, kindLabel, type ElementKind } from "@/lib/elements";
import { FILL_EVENT, keepReferences, takePendingFill, type ComposerDraft, type ContactSheet, type Turn } from "@/lib/assistant";
import { ContactSheetView, keepersOf } from "@/components/studio/contact-sheet";

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
  // the one thing on that page that must not be thrown away. It is put
  // in the box once the saved draft has loaded, so the draft cannot
  // land on top of it (and it outranks whatever the draft held).
  const sparkParam = params.get("spark");
  // The thread and the box are the studio's (assistant-thread.tsx): the
  // same turns the pill shows, and a draft that survives leaving the page.
  const { turns: thread, setTurns: setThread, draft, setDraft, ready, finishProject } = useAssistantThread();
  const { idea, picked, brief, written, uploads, mode: wantMode } = draft;
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
  const setWritten = (w: ComposerDraft["written"]) => setDraft({ written: w });
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
  // Two kinds of note, and they used to render identically: progress
  // ("Writing…") and failure. A failure in the hint's own slot, small
  // caps and ellipsised, is how a 403 on every Guide turn read as the
  // composer saying nothing at all (2026-09-14). `say(text, true)`
  // marks the failing kind -- it turns the line signal-red and also
  // raises the shell's error toast, which is the loud surface.
  const [note, setNote] = useState<string | null>(null);
  const [noteBad, setNoteBad] = useState(false);
  const [progress, setProgress] = useState(0);
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
  const [lengths, setLengths] = useState<number[]>([]);
  const [seconds, setSeconds] = useState(0);
  const [ratios, setRatios] = useState<Option[]>([]);
  const [ratio, setRatio] = useState("");
  // the assistant pill filled the box: who, so the tag can say so and
  // Create can wear a ring until the person presses it (or edits it away)
  const [filledBy, setFilledBy] = useState<{ name: string; avatar?: string } | null>(null);
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
        if (hit) setAttachPhotos(hit.photos.slice(0, FRAMES_PER_ASSET));
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
  // sessionStorage and is taken on mount. It only ever FILLS: Create is
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

  // an upload still on its way to the bin would be left out of the run
  const canSend = !busy && !pending.length && (mode === "create" ? !!(idea.trim() || brief.trim()) : !!idea.trim());
  const referenceCount = picked.length + uploads.length + pending.length;

  // The references on screen, in the field name the API reads for a
  // stored reference (app/api.py:_collect_refs, `asset_photos`). Uploads
  // go first -- refs[0] is the frame the clip anchors on, and an upload
  // was read before the picks when it rode as `files` -- then the picks
  // out of the asset bank. ONE helper for both buttons, the way the
  // vanilla composer's collectRunForm is -- when the Guide built its own
  // FormData it sent neither, so the model was told "0 reference images
  // supplied" over two visible thumbnails; and Create sent the picks as
  // `refs`, a field nothing server-side has ever read, so a @Michael pick
  // reached the scene only when it was also a file (2026-09-18). Since
  // 2026-10-02 an upload is already in the bin by the time Send is
  // pressed (attach() saves it), so it is a URL like any pick.
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

  const appendReferences = (form: FormData) => {
    [...uploads.map((u) => u.url), ...picked].forEach((u) => form.append("asset_photos", u));
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
    setFilledBy(null);
    say(null);
    let asking: Turn | null = null;
    try {
      if (mode === "create") {
        const form = new FormData();
        form.append("idea", brief.trim() || idea.trim());
        if (brand) form.append("brand", brand);
        form.append("count", "1");
        if (brain) form.append("brain", brain);
        if (seconds) form.append("seconds", String(seconds));
        if (ratio) form.append("ratio", ratio);
        if (project) form.append("project_id", String(project.id));
        appendReferences(form);
        const started = await runScenes(form);
        say("Writing the scene…");
        const job = await waitForJob(started.job_id, (j) => {
          setProgress(j.progress || 0);
          say(j.detail || "Writing the scene…");
        });
        // a Create is charged quietly, the way InVideo does it: no price on
        // the button, the balance pill just moves (2026-09-28, Mike's call)
        announceBalanceChange();
        if (job.status === "done") {
          setProgress(1);
          say(null);
          // the conversation did its job: the scene is on the board with
          // its prompt and references, so the talk, the brief and the box
          // go away and only this card stays (2026-10-02, Mike's call)
          finishProject({ conceptId: job.ref_id ?? null, detail: job.detail || "on the board" });
          toast("Scene written · it is on Pipeline to pick");
          announceQueueChange();
        } else {
          say(job.error || "That run did not finish.", true);
        }
      } else {
        const asked = idea.trim();
        const mine: Turn = { role: "user", content: asked };
        const next: Turn[] = [...thread.filter((m) => !m.failed), mine];
        asking = mine;
        setThread(next);
        setIdea("");
        const form = new FormData();
        form.append(
          "conversation",
          JSON.stringify({ messages: next.map(({ role, content }) => ({ role, content })) }),
        );
        if (brand) form.append("brand", brand);
        form.append("guide_provider", "gemini");
        form.append("idea", asked);
        if (project) form.append("project_id", String(project.id));
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
        const mine = asking;
        setThread((all) => all.map((m) => (m === mine ? { ...m, failed: true } : m)));
        setIdea((now) => now || mine.content);
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
      say("Banked.");
    } catch (e) {
      say(e instanceof Error ? e.message : "That did not go through.", true);
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
     to R2 -- the same bin a Create used to save it into). The draft then
     remembers a URL that resolves on every machine, which is what lets
     the box survive leaving the page; a File object never could. The tile
     draws from the object URL until the server answers. */
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
        // or an unreadable file, and the name is only the tile's tooltip
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
          {project ? (
            <div className="mb-2 flex items-center gap-2 text-[12px] text-white/60">
              <span className="rounded-full border border-white/15 bg-white/[0.06] px-3 py-1">
                Project ·{" "}
                <Link href="/studio/projects" className="text-white/90 hover:underline">
                  {project.title}
                </Link>
                <button
                  type="button"
                  onClick={leaveProject}
                  className="ml-2 text-white/40 hover:text-white/90"
                  aria-label="Leave this project"
                  title="Write outside any project"
                >
                  ×
                </button>
              </span>
              <span className="text-white/40">written against its brief and {project.memory.length} learned</span>
            </div>
          ) : null}
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
                    {m.reply?.sheet ? (
                      <ContactSheetView
                        sheet={m.reply.sheet}
                        chosen={m.chosen ?? {}}
                        kept={!!m.kept}
                        busy={busy}
                        name="The Guide"
                        onToggle={(id) => toggleFrame(i, id)}
                        onKeep={(sh) => keepFrames(i, sh)}
                      />
                    ) : null}
                    {m.reply?.proposal ? (
                      <div className={`ccard${m.decided ? ` ${m.decided}` : ""}`}>
                        <b>{m.reply.proposal.label}</b>
                        <dl>
                          {Object.entries(m.reply.proposal.args).map(([k, v]) => (
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
              {uploads.map((a) => (
                <span
                  key={a.url}
                  className={`cattach${drawable(a.url) ? "" : " raw"}`}
                  title={a.name || a.url}
                  data-ext={drawable(a.url) ? undefined : a.url.split(".").pop()?.split("?")[0]?.toUpperCase()}
                  style={drawable(a.url) ? { backgroundImage: `url(${API_URL}${a.url})` } : undefined}
                >
                  <button type="button" aria-label={`Remove ${a.name || "upload"}`} onClick={() => removeUpload(a.url)}>
                    <X strokeWidth={2} />
                  </button>
                </span>
              ))}
              {pending.map((a) => (
                <span
                  key={a.id}
                  className="cattach pending"
                  title={`${a.name} · uploading…`}
                  aria-busy="true"
                  style={{ backgroundImage: `url(${a.url})` }}
                />
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
                  onClick={() => setDraft({ picked: [], uploads: [] })}
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
                onChange={(e) => {
                  setIdea(e.target.value);
                  if (!e.target.value.trim()) setFilledBy(null);
                }}
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
              {filledBy && idea.trim() ? (
                <span className="zpa-filled">
                  {filledBy.avatar ? `${filledBy.avatar} ` : ""}Filled by {filledBy.name}
                </span>
              ) : null}
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
              <button
                type="button"
                className={`go${filledBy && idea.trim() && mode === "create" && !busy ? " zpa-ring" : ""}`}
                disabled={!canSend}
                onClick={() => void send()}
              >
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
