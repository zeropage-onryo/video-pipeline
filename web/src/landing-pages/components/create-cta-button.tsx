"use client";

import { ArrowRight, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { goToSignIn } from "@/lib/api";

// The one door off a /make page: the sign-in form (sign-up heading), and
// after it the composer opened on this page's starting line. The studio
// reads `?spark=` and nothing else today -- a `?template=` the composer
// understands (prefill, Create mode, "add your product photos") is the
// follow-up that would make this a real template rather than a sentence.
//
// `variant="link"` is the small "Start now ›" at the foot of a card.
export function CreateCtaButton({
  label,
  spark,
  size = "lg",
  variant = "default",
  className,
}: {
  label: string;
  spark: string;
  size?: "lg" | "default";
  variant?: "default" | "link";
  className?: string;
}) {
  const go = () => goToSignIn("signup", `/studio?spark=${encodeURIComponent(spark)}`);
  if (variant === "link") {
    return (
      <button
        type="button"
        onClick={go}
        className={`inline-flex items-center gap-1 text-[13px] font-semibold text-foreground transition-opacity hover:opacity-70 ${className ?? ""}`}
      >
        {label}
        <ChevronRight className="size-3.5" />
      </button>
    );
  }
  return (
    <Button size={size} className={className} onClick={go}>
      {label}
      <ArrowRight data-icon="inline-end" className="size-4" />
    </Button>
  );
}
