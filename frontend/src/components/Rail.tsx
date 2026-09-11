import {
  BarChart3,
  Clapperboard,
  Home,
  Layers,
  ListVideo,
  PanelLeft,
  Workflow,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { AccountMenu } from './AccountMenu'

/**
 * The rail collapses to icons and opens on hover.
 *
 * It OVERLAYS: the shell keeps its 84px margin whatever the rail is
 * doing, so opening it never shoves the hero and the composer sideways
 * — which is what makes brushing the left edge feel incidental instead
 * of destructive. The pin is the only part that needs state, and it
 * survives a reload or it is a toggle nobody uses twice.
 *
 * Hover is CSS (group-hover), not React state: a pointer-in/out
 * listener that re-renders a nav on every entry is work for nothing,
 * and it drops frames the moment the main thread is busy.
 */
const NAV = [
  { id: 'studio', label: 'Studio', icon: Home },
  { id: 'assets', label: 'Assets', icon: Layers },
  { id: 'pipeline', label: 'Pipeline', icon: Workflow },
  { id: 'director', label: 'Director', icon: Clapperboard },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'queue', label: 'Queue', icon: ListVideo },
] as const

export type ViewId = (typeof NAV)[number]['id']

const PIN_KEY = 'zpf.rail.pinned'

function usePinned() {
  const [pinned, setPinned] = useState(false)
  useEffect(() => {
    try {
      setPinned(localStorage.getItem(PIN_KEY) === '1')
    } catch {
      /* private window: the pin just forgets */
    }
  }, [])
  const toggle = () =>
    setPinned((was) => {
      const now = !was
      try {
        localStorage.setItem(PIN_KEY, now ? '1' : '0')
      } catch {
        /* ignored, same reason */
      }
      return now
    })
  return [pinned, toggle] as const
}

/** Fades with the rail's width, and leaves the tab order while hidden so
 *  a keyboard user cannot land on an invisible control. */
function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        'opacity-0 transition-opacity duration-150 group-hover:opacity-100',
        'group-hover:delay-75 group-data-[pinned=true]:opacity-100',
        'pointer-events-none group-hover:pointer-events-auto group-data-[pinned=true]:pointer-events-auto',
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Rail({ view, onNavigate }: { view: ViewId; onNavigate: (v: ViewId) => void }) {
  const [pinned, togglePin] = usePinned()
  return (
    <nav
      data-pinned={pinned}
      className={cn(
        'group fixed inset-y-0 left-0 z-40 flex w-21 flex-col overflow-hidden px-3 pt-5.5 pb-4.5',
        'border-r border-line bg-[rgb(6_6_8/0.52)] backdrop-blur-xl',
        'transition-[width,background-color] duration-200 ease-[var(--ease-zpf)]',
        // the shadow is what makes it read as a sheet OVER the page
        // rather than a column that grew: without it the header text it
        // covers looks broken instead of behind something
        'hover:w-59 hover:bg-[rgb(6_6_8/0.88)] hover:shadow-[8px_0_40px_-12px_rgb(0_0_0/0.9)]',
        'data-[pinned=true]:w-59 data-[pinned=true]:bg-[rgb(6_6_8/0.88)]',
        'motion-reduce:transition-none',
      )}
    >
      <div className="mb-6.5 flex items-center gap-2.5">
        <button
          type="button"
          title="Studio"
          className={cn(
            'grid size-9.5 flex-none place-items-center rounded-r1 border border-line-hi',
            'font-mono text-[11px] tracking-wider text-text transition-colors duration-200',
            'hover:border-accent',
          )}
        >
          ZP
        </button>
        <Reveal className="font-display text-[13px] tracking-[0.09em] whitespace-nowrap text-dim uppercase">
          Studio
        </Reveal>
        <Reveal className="ml-auto">
          <button
            type="button"
            onClick={togglePin}
            aria-pressed={pinned}
            title={pinned ? 'Let the rail collapse' : 'Keep the rail open'}
            className={cn(
              'grid size-7 cursor-pointer place-items-center rounded-[9px] border transition-colors duration-200',
              pinned
                ? 'border-line-hi text-text'
                : 'border-line text-dimmer hover:border-line-hi hover:text-text',
            )}
          >
            <PanelLeft className="size-3.5" strokeWidth={1.5} />
          </button>
        </Reveal>
      </div>

      <div className="flex flex-col gap-1.5">
        {NAV.map(({ id, label, icon: Icon }) => {
          const current = id === view
          return (
            <button
              key={id}
              type="button"
              onClick={() => onNavigate(id)}
              aria-current={current ? 'page' : undefined}
              title={label}
              className={cn(
                'relative flex h-11 cursor-pointer items-center gap-3.5 rounded-r1 px-3.5',
                'transition-colors duration-200',
                current
                  ? 'bg-white/8 text-text'
                  : 'text-dimmer hover:bg-white/4 hover:text-dim',
              )}
            >
              {current ? (
                <span className="absolute left-0 h-4.5 w-[3px] rounded-full bg-accent" />
              ) : null}
              <Icon className="size-4.5 flex-none" strokeWidth={1.35} />
              <Reveal className="text-[13.5px] whitespace-nowrap">{label}</Reveal>
            </button>
          )
        })}
      </div>

      <div className="mt-auto flex flex-col gap-2">
        <Reveal className="label-mono flex items-center gap-2.5 pl-2 text-[9px] text-dimmer">
          <kbd className="rounded-full border border-line px-2.5 py-1.5">⌘K</kbd>
        </Reveal>
        {/* The account block gets the rail's own reveal passed IN rather
            than importing it: one implementation of "fades with the
            width", so the name and the nav labels can never drift into
            appearing at different moments. */}
        <div className="border-t border-line pt-2">
          <AccountMenu reveal={(node) => <Reveal className="min-w-0 flex-1">{node}</Reveal>} />
        </div>
      </div>
    </nav>
  )
}
