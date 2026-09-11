import { ArrowRight, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Runway's send: a circle, not a word.
 *
 * Disabled is quiet rather than absent — a button that disappears when
 * the box is empty is a button people ask about — and the enabled state
 * is the only place in the composer that carries the brand red, so the
 * eye lands on the one control that spends something.
 */
export function SendButton({
  disabled,
  busy,
  label,
  onClick,
}: {
  disabled?: boolean
  busy?: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled || busy}
      onClick={onClick}
      className={cn(
        'ml-1 grid size-10 flex-none cursor-pointer place-items-center rounded-full',
        'transition-[background-color,color,transform,box-shadow] duration-200',
        'active:translate-y-px disabled:cursor-default disabled:active:translate-y-0',
        disabled || busy
          ? 'bg-white/8 text-dimmer'
          : 'bg-accent text-on-accent shadow-[0_6px_22px_-12px_rgb(255_255_255/0.55)] hover:brightness-95',
      )}
    >
      {busy ? (
        <Loader2 className="size-4.5 animate-spin" strokeWidth={2} />
      ) : (
        <ArrowRight className="size-4.5" strokeWidth={1.9} />
      )}
    </button>
  )
}
