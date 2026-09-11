import * as Popover from '@radix-ui/react-popover'
import { Check } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * The LTX model menu, generalised: a grouped list where every row is an
 * icon, a name, an optional badge and a line of prose saying what the
 * choice actually costs you.
 *
 * Radix owns the hard parts — focus trapping, Escape, outside-click,
 * collision flipping when the composer sits near the bottom of the
 * viewport — which is the whole reason to reach for it rather than
 * hand-rolling a positioned div for the fourth time.
 */
export interface Option {
  id: string
  label: string
  note?: string
  badge?: string
  icon?: ReactNode
}

interface Props {
  trigger: ReactNode
  heading: string
  options: Option[]
  value: string
  onChange: (id: string) => void
  align?: 'start' | 'center' | 'end'
}

export function OptionPopover({ trigger, heading, options, value, onChange, align = 'start' }: Props) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>{trigger}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align={align}
          side="top"
          sideOffset={10}
          collisionPadding={12}
          className={cn(
            'z-90 w-[min(21rem,calc(100vw-1.5rem))] rounded-2xl border border-line p-1.5',
            'bg-panel/97 backdrop-blur-2xl shadow-[0_30px_90px_-30px_rgb(0_0_0/0.9)]',
            'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
            'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          )}
        >
          <div className="label-mono px-3 pt-2.5 pb-1.5 text-[8.5px] text-dimmer">{heading}</div>
          {options.map((o) => {
            const selected = o.id === value
            return (
              <Popover.Close asChild key={o.id}>
                <button
                  type="button"
                  aria-selected={selected}
                  onClick={() => onChange(o.id)}
                  className={cn(
                    'flex w-full cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 text-left',
                    'transition-colors duration-200 hover:bg-white/6',
                    selected && 'bg-white/8',
                  )}
                >
                  {o.icon ? (
                    <span className="grid size-6.5 flex-none place-items-center rounded-lg bg-white/6 text-dim">
                      {o.icon}
                    </span>
                  ) : null}
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 text-[13px]">
                      {o.label}
                      {o.badge ? (
                        <em className="label-mono rounded-[5px] border border-line-hi px-1.5 py-0.5 text-[7.5px] not-italic text-dim">
                          {o.badge}
                        </em>
                      ) : null}
                    </span>
                    {o.note ? (
                      <span className="mt-0.5 block text-[11.5px] leading-relaxed text-dim">
                        {o.note}
                      </span>
                    ) : null}
                  </span>
                  <Check
                    className={cn('ml-auto size-4 text-text', selected ? 'opacity-100' : 'opacity-0')}
                    strokeWidth={2}
                  />
                </button>
              </Popover.Close>
            )
          })}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
