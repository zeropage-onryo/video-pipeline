import { cva, type VariantProps } from 'class-variance-authority'
import { ChevronDown } from 'lucide-react'
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * One control shape for the whole composer row: icon, optional label,
 * optional chevron. LTX's bar reads as one system because every control
 * in it is the same ghost pill — the moment one of them is a native
 * <select> and its neighbour is a button, the row looks assembled rather
 * than designed.
 */
const pill = cva(
  'inline-flex h-9 items-center gap-2 rounded-[10px] border border-transparent px-3 ' +
    'text-[12.5px] leading-none whitespace-nowrap cursor-pointer select-none ' +
    'transition-[color,background-color,border-color] duration-200 ' +
    'hover:bg-white/6 hover:text-text disabled:opacity-40 disabled:cursor-default ' +
    'disabled:hover:bg-transparent',
  {
    variants: {
      tone: {
        quiet: 'text-dim',
        /** the one control in the row that reads as chosen */
        chosen: 'text-text bg-white/5 border-line',
        /** a non-default setting, so the row shows it is not resting */
        accent: 'text-text bg-white/8 border-line-hi',
      },
      open: {
        true: 'text-text bg-white/9 border-line',
        false: '',
      },
    },
    defaultVariants: { tone: 'quiet', open: false },
  },
)

export interface PillProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof pill> {
  icon?: ReactNode
  chevron?: boolean
}

export const Pill = forwardRef<HTMLButtonElement, PillProps>(function Pill(
  { className, icon, chevron, tone, open, children, ...props },
  ref,
) {
  return (
    <button ref={ref} type="button" className={cn(pill({ tone, open }), className)} {...props}>
      {icon}
      {children ? <span className="hidden sm:inline">{children}</span> : null}
      {chevron ? <ChevronDown className="-ml-0.5 size-3 opacity-70" strokeWidth={1.6} /> : null}
    </button>
  )
})
