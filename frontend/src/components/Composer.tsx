import { motion } from 'motion/react'
import {
  AtSign,
  Brain,
  Clock,
  Image as ImageIcon,
  MessageSquare,
  Play,
  Plus,
  RectangleHorizontal,
  Search,
  Settings2,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  askGuide,
  createScenes,
  getBrains,
  getCapabilities,
  getRenderChoices,
  getSceneLengths,
  waitForJob,
  type Brain as BrainTier,
  type GuideMessage,
  type RatioChoice,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { OptionPopover, type Option } from './ui/OptionPopover'
import { Pill } from './ui/Pill'
import { SendButton } from './ui/SendButton'

/* ── what the send button does ─────────────────────────────────────
   One box, two destinations. Guide talks the idea through; Create skips
   the conversation and writes scenes from whatever is in the box. */
const MODES: Option[] = [
  {
    id: 'guide',
    label: 'Guide',
    note: 'Talk the idea through first. Send goes to your creative partner.',
    icon: <MessageSquare className="size-3.5" strokeWidth={1.6} />,
  },
  {
    id: 'create',
    label: 'Create',
    note: 'Skip the conversation and write scenes from what is in the box.',
    icon: <Play className="size-3.5" strokeWidth={1.6} />,
  },
]

interface Attachment {
  id: string
  name: string
  file: File
  url: string
}

export function Composer({ brand = 'zeropage' }: { brand?: string }) {
  const [mode, setMode] = useState('guide')
  const [idea, setIdea] = useState('')
  const [brains, setBrains] = useState<BrainTier[]>([])
  const [brain, setBrain] = useState('fast')
  const [lengths, setLengths] = useState<number[]>([])
  const [seconds, setSeconds] = useState(8)
  const [ratios, setRatios] = useState<RatioChoice[]>([])
  const [ratio, setRatio] = useState('')
  const [caps, setCaps] = useState<Record<string, unknown>>({})
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [thread, setThread] = useState<GuideMessage[]>([])
  const [choices, setChoices] = useState<string[]>([])
  const [brief, setBrief] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    // Each of these degrades to hiding its own control rather than
    // failing the composer: a box you cannot pick a model in still
    // writes a scene on the server's own default.
    getBrains()
      .then((r) => {
        setBrains(r.brains)
        setBrain(r.default)
      })
      .catch(() => setBrains([]))
    getSceneLengths()
      .then((r) => {
        setLengths(r.choices)
        setSeconds(r.default)
      })
      .catch(() => setLengths([]))
    getRenderChoices()
      .then((r) => {
        setRatios(r.ratios)
        setRatio(r.default)
      })
      .catch(() => setRatios([]))
    getCapabilities().then(setCaps).catch(() => setCaps({}))
  }, [])

  // Guide is the default mode, but only when the server says the route
  // is there — otherwise the primary action of the box would be one
  // that 404s, and Create is the honest fallback.
  const guideReady = caps.creative_guide === true
  useEffect(() => {
    if (Object.keys(caps).length && !guideReady && mode === 'guide') setMode('create')
  }, [caps, guideReady, mode])

  const tier = brains.find((b) => b.id === brain)
  const typed = mode === 'create' ? idea.trim() || brief.trim() : idea.trim()
  const canSend = typed.length > 0 && !busy

  async function send() {
    if (!canSend) return
    setBusy(true)
    setNote(null)
    try {
      if (mode === 'create') {
        // the brief the guide wrote wins over the raw box when there is
        // one: it is the thing that was actually worked on
        const started = await createScenes({
          idea: brief.trim() || idea.trim(),
          brand,
          brain,
          seconds,
          ratio: ratio || undefined,
          files: attachments.map((a) => a.file),
        })
        const job = await waitForJob(started.job_id, (j) => setNote(j.detail || 'Writing…'))
        setNote(
          job.status === 'done'
            ? `Done — ${job.detail ?? 'on the board'}`
            : job.error || 'That run did not finish.',
        )
        if (job.status === 'done') setIdea('')
      } else {
        const next: GuideMessage[] = [...thread, { role: 'user', content: idea.trim() }]
        const asked = idea.trim()
        setThread(next)
        setIdea('')
        setChoices([])
        const started = await askGuide(next, { brand, idea: asked })
        const job = await waitForJob(started.job_id, (j) =>
          setNote(j.detail || 'Considering your direction…'),
        )
        if (job.status !== 'done' || !job.reply) {
          throw new Error(job.error || 'The guide stopped. Your reply is still here to retry.')
        }
        setThread([...next, { role: 'assistant', content: job.reply.message }])
        setChoices(job.reply.choices ?? [])
        if (job.reply.brief) setBrief(job.reply.brief)
        setNote(
          job.reply.brief
            ? 'Brief ready — switch to Create, or keep refining.'
            : 'Choose a direction or reply in your own words.',
        )
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setNote(`${e.message} Switch to the studio assistant to carry on.`)
      } else {
        setNote(e instanceof Error ? e.message : 'That did not go through.')
      }
    } finally {
      setBusy(false)
    }
  }

  function attach(files: FileList | null) {
    if (!files) return
    setAttachments((was) => [
      ...was,
      ...Array.from(files).map((f) => ({
        id: crypto.randomUUID(),
        name: f.name,
        file: f,
        url: URL.createObjectURL(f),
      })),
    ])
  }

  const slot =
    'flex h-15.5 min-w-19 flex-none cursor-pointer flex-col items-center justify-center gap-1.5 ' +
    'rounded-xl border border-transparent bg-white/4.5 px-2.5 text-dim transition-colors ' +
    'duration-200 hover:border-line hover:bg-white/8 hover:text-text'

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 0.61, 0.36, 1] }}
      className={cn(
        'w-full max-w-[880px] rounded-r3 border border-line border-t-line-hi',
        'bg-panel/55 backdrop-blur-3xl',
        'transition-[border-color,box-shadow] duration-300',
        'focus-within:border-line-hi focus-within:shadow-[0_0_0_1px_rgb(255_255_255/0.06),0_26px_80px_-40px_rgb(255_255_255/0.25)]',
      )}
    >
      {settingsOpen && mode === 'guide' ? (
        <div className="flex items-start justify-between gap-4 border-b border-white/5 px-6 pt-5 pb-4">
          <div>
            <h2 className="font-display text-base font-semibold tracking-wide">
              Your creative partner
            </h2>
            <p className="mt-1 text-[12.5px] text-dim">
              Work through the idea here, then create scenes from the brief.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setThread([])
              setChoices([])
              setBrief('')
              setNote(null)
              setSettingsOpen(false)
            }}
            className="cursor-pointer rounded-full border border-line px-3 py-1.5 text-[12px] text-dim hover:border-line-hi hover:text-text"
          >
            New conversation
          </button>
        </div>
      ) : null}

      {thread.length > 0 && mode === 'guide' ? (
        <div className="max-h-70 space-y-2.5 overflow-y-auto border-b border-white/5 px-5.5 py-4">
          {thread.map((m, i) => (
            <p
              key={i}
              className={cn(
                'rounded-xl border px-3.5 py-2.5 text-[13px] leading-relaxed whitespace-pre-wrap',
                m.role === 'user'
                  ? 'ml-8 border-line-hi bg-white/4 text-text'
                  : 'border-line bg-white/2 text-dim',
              )}
            >
              {m.content}
            </p>
          ))}
          {choices.length > 0 ? (
            <div className="flex flex-wrap gap-2 pt-1">
              {choices.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setIdea(c)}
                  className="cursor-pointer rounded-full border border-line px-3.5 py-1.5 text-[12px] text-dim transition-colors hover:border-line-hi hover:text-text"
                >
                  {c}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* LTX's slot row: the affordances live above the text, not in a menu */}
      <div className="flex flex-wrap gap-2 px-5 pt-4.5">
        <button type="button" onClick={() => fileInput.current?.click()} className={slot}>
          <ImageIcon className="size-4.5" strokeWidth={1.5} />
          <b className="label-mono max-w-20 text-center text-[7.5px] leading-tight font-normal">
            Add image
            <br />
            reference
          </b>
        </button>
        <button
          type="button"
          onClick={() => {
            setIdea((v) => `${v}@`)
            textarea.current?.focus()
          }}
          className={slot}
        >
          <AtSign className="size-4.5" strokeWidth={1.5} />
          <b className="label-mono max-w-20 text-center text-[7.5px] leading-tight font-normal">
            Consistent
            <br />
            element
          </b>
        </button>
        {attachments.map((a) => (
          <span
            key={a.id}
            title={a.name}
            className="group relative size-15.5 overflow-hidden rounded-xl border border-line bg-cover bg-center"
            style={{ backgroundImage: `url(${a.url})` }}
          >
            <button
              type="button"
              onClick={() => setAttachments((w) => w.filter((x) => x.id !== a.id))}
              className="absolute top-1 right-1 grid size-5 cursor-pointer place-items-center rounded-full bg-black/70 text-dim opacity-0 transition-opacity group-hover:opacity-100 hover:text-text"
            >
              <X className="size-3" strokeWidth={2} />
            </button>
          </span>
        ))}
      </div>

      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => attach(e.target.files)}
      />

      <textarea
        ref={textarea}
        value={idea}
        maxLength={10000}
        onChange={(e) => setIdea(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void send()
        }}
        placeholder={
          mode === 'create'
            ? 'Describe the scene to write… (@ to reference an asset)'
            : "Describe your video or ask for a direction. We'll work through the story, look and pacing…"
        }
        aria-label="Your idea"
        className="w-full resize-none bg-transparent px-5.5 pt-5 pb-1 text-base leading-relaxed font-light text-text outline-none placeholder:text-dimmer"
        rows={3}
      />

      {brief && mode === 'create' ? (
        <div className="px-5.5 pb-1">
          <label className="label-mono mb-1.5 block text-[8.5px]">
            Brief from the guide · editable · this is what Create writes from
          </label>
          <textarea
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            rows={5}
            className="w-full resize-none rounded-xl border border-line bg-white/2 px-3.5 py-2.5 text-[13px] leading-relaxed text-dim outline-none focus:border-line-hi focus:text-text"
          />
        </div>
      ) : null}

      {note ? <p className="px-5.5 pb-1 text-[11.5px] text-dim">{note}</p> : null}

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-white/4.5 px-3 pt-2.5 pb-3">
        <OptionPopover
          heading="Send does"
          options={guideReady ? MODES : MODES.filter((m) => m.id === 'create')}
          value={mode}
          onChange={setMode}
          trigger={
            <Pill
              tone="chosen"
              chevron
              icon={
                mode === 'create' ? (
                  <Play className="size-3.5" strokeWidth={1.6} />
                ) : (
                  <MessageSquare className="size-3.5" strokeWidth={1.6} />
                )
              }
            >
              {MODES.find((m) => m.id === mode)?.label}
            </Pill>
          }
        />
        <Pill
          icon={<Plus className="size-3.5" strokeWidth={1.6} />}
          title="Add media"
          aria-label="Add media"
          onClick={() => fileInput.current?.click()}
        />
        {mode === 'guide' ? (
          <Pill
            icon={<Settings2 className="size-3.5" strokeWidth={1.6} />}
            title="Conversation settings"
            aria-label="Conversation settings"
            open={settingsOpen}
            onClick={() => setSettingsOpen((v) => !v)}
          />
        ) : null}
        {caps.scout === true ? (
          <Pill
            icon={<Search className="size-3.5" strokeWidth={1.6} />}
            title="Crawl for a spark and its references"
            aria-label="Research an idea"
          />
        ) : null}

        <span className="min-w-2 flex-1" />

        {brains.length > 0 ? (
          <OptionPopover
            heading="Which model writes"
            align="end"
            value={brain}
            onChange={setBrain}
            options={brains.map((b) => ({
              id: b.id,
              label: b.label,
              note: b.note,
              badge: b.default ? undefined : 'slower',
              icon: <Brain className="size-3.5" strokeWidth={1.6} />,
            }))}
            trigger={
              <Pill
                tone={tier && !tier.default ? 'accent' : 'quiet'}
                chevron
                icon={<Brain className="size-3.5" strokeWidth={1.6} />}
                title="Which model writes the scene"
              >
                {tier?.label ?? 'Model'}
              </Pill>
            }
          />
        ) : null}

        {lengths.length > 0 ? (
          <OptionPopover
            heading="How long the scene is"
            align="end"
            value={String(seconds)}
            onChange={(v) => setSeconds(Number(v))}
            options={lengths.map((s) => ({
              id: String(s),
              label: `${s} sec`,
              note: 'Filled with timed shots, each rendered as its own clip',
              icon: <Clock className="size-3.5" strokeWidth={1.6} />,
            }))}
            trigger={
              <Pill chevron icon={<Clock className="size-3.5" strokeWidth={1.6} />}>
                {`${seconds} sec`}
              </Pill>
            }
          />
        ) : null}

        {ratios.length > 0 ? (
          <OptionPopover
            heading="Frame"
            align="end"
            value={ratio}
            onChange={setRatio}
            options={ratios.map((r) => ({
              id: r.id,
              label: r.label,
              note: r.size,
              icon: <RectangleHorizontal className="size-3.5" strokeWidth={1.6} />,
            }))}
            trigger={
              <Pill chevron icon={<RectangleHorizontal className="size-3.5" strokeWidth={1.6} />}>
                {ratios.find((r) => r.id === ratio)?.label ?? 'Frame'}
              </Pill>
            }
          />
        ) : null}

        <SendButton
          disabled={!canSend}
          busy={busy}
          label={mode === 'create' ? 'Create scenes' : 'Send to your creative partner'}
          onClick={() => void send()}
        />
      </div>
    </motion.div>
  )
}
