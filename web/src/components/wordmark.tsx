import Link from "next/link";
import { ZpLogo } from "@/components/zp-logo";

// The wordmark the header and footer share: the ZP mark, then the
// name set in the body face at 600 -- a logo-sized word, not a headline.
export function Wordmark({ className = "", intro = false }: { className?: string; intro?: boolean }) {
  return (
    <Link href="/" className={`group flex items-center gap-2.5 ${className}`} aria-label="Zero Page home">
      <ZpLogo size={34} intro={intro} />
      <span className="text-[17px] font-semibold tracking-[-0.02em] text-foreground">zeropage</span>
    </Link>
  );
}
