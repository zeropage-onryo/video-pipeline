import type { ReactNode } from "react";

export type Faq = { q: string; a: ReactNode };

// Native <details>: no JS, keyboard-accessible, and the open state
// survives a client-side navigation. The hairline between rows is the
// page's only separator, as everywhere else.
export function FaqList({ items }: { items: Faq[] }) {
  return (
    <div className="divide-y divide-border border-y border-border">
      {items.map((item) => (
        <details key={item.q} className="group py-5">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-6 text-[17px] font-medium tracking-[-0.005em] text-foreground [&::-webkit-details-marker]:hidden">
            {item.q}
            <span
              aria-hidden
              className="relative block h-4 w-4 shrink-0 text-[#82807d] transition-transform group-open:rotate-45"
            >
              <span className="absolute left-1/2 top-0 h-4 w-px -translate-x-1/2 bg-current" />
              <span className="absolute left-0 top-1/2 h-px w-4 -translate-y-1/2 bg-current" />
            </span>
          </summary>
          <div className="mt-3 max-w-[64ch] text-[15px] leading-relaxed text-[#afafaf] [&_a]:text-foreground [&_a]:underline [&_a]:underline-offset-4">
            {item.a}
          </div>
        </details>
      ))}
    </div>
  );
}
