"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

// The hero's front door. A landing page that only links to the product
// asks a visitor to commit before they have touched anything; a box they
// can type in IS the product's first step, and what they type is carried
// into the studio composer as ?spark= rather than thrown away.
const EXAMPLES = [
  "a commercial for the brand",
  "a horror short in a motel hallway",
  "a rain-soaked chase down a neon street",
  "a product film for a watch, shot on 35mm",
];

export function HeroPrompt() {
  const router = useRouter();
  const [idea, setIdea] = useState("");
  const [example, setExample] = useState(0);

  // The placeholder cycles so the box reads as an invitation rather than a
  // search field. It stops the moment anything is typed -- a placeholder
  // moving under live text is noise.
  useEffect(() => {
    if (idea) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setInterval(() => setExample((i) => (i + 1) % EXAMPLES.length), 3200);
    return () => clearInterval(id);
  }, [idea]);

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const spark = idea.trim();
        router.push(spark ? `/studio?spark=${encodeURIComponent(spark)}` : "/studio");
      }}
      className="relative mt-10 flex w-full max-w-[620px] flex-col gap-2 rounded-2xl border border-border bg-card p-2 text-left transition-colors focus-within:border-white/25 sm:block sm:pl-5 md:mt-14"
    >
      <label htmlFor="hero-spark" className="sr-only">
        What do you want to create?
      </label>
      <input
        id="hero-spark"
        value={idea}
        onChange={(event) => setIdea(event.target.value)}
        placeholder={`I'm creating ${EXAMPLES[example]}`}
        autoComplete="off"
        className="h-12 w-full bg-transparent px-3 text-[15px] outline-none placeholder:text-[#82807d] sm:px-0 sm:pr-[9.5rem]"
      />
      <Button type="submit" className="h-12 w-full sm:absolute sm:right-2 sm:top-2 sm:w-auto">
        Start creating
        <ArrowRight data-icon="inline-end" className="size-4" />
      </Button>
    </form>
  );
}
