import type { ReactNode } from "react";

// The head of every inner page: the mono eyebrow, the serif title at the
// hero's scale, one paragraph of dek. Centered, like the home hero, so
// the site reads as one thing page to page.
export function PageIntro({
  eyebrow,
  title,
  dek,
  children,
}: {
  eyebrow: string;
  title: string;
  dek?: string;
  children?: ReactNode;
}) {
  return (
    <div className="relative overflow-hidden pt-[60px]">
      <div aria-hidden className="hero-grid pointer-events-none absolute inset-0 z-0" />
      <div className="relative z-10 mx-auto flex max-w-[1200px] flex-col items-center px-6 pb-14 pt-20 text-center md:pb-16 md:pt-28">
        <span className="eyebrow">{eyebrow}</span>
        <h1 className="serif mt-5 max-w-[18ch] text-[clamp(2.25rem,6vw,4.25rem)]">{title}</h1>
        {dek && (
          <p className="mt-6 max-w-[52ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal text-[#afafaf]">
            {dek}
          </p>
        )}
        {children}
      </div>
    </div>
  );
}
