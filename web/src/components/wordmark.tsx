import Link from "next/link";
import { ApertureMark } from "@/components/aperture-mark";

// The wordmark the header and footer share: the aperture mark, then the
// name set in the body face at 600 -- a logo-sized word, not a headline.
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <Link href="/" className={`group flex items-center gap-2.5 ${className}`} aria-label="Zero Page home">
      <ApertureMark className="h-[22px] w-[22px] text-foreground transition-transform duration-500 group-hover:rotate-45" />
      <span className="text-[17px] font-semibold tracking-[-0.02em] text-foreground">zeropage</span>
    </Link>
  );
}
