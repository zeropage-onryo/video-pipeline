import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

// The five ways in. Same canvas as every other section -- separation on
// this page is done by hairlines and spacing, never by inverting the
// background.
const STARTS = [
  ["A script", "Bring a scene or passage into your brief and develop its visual direction."],
  ["An idea", "Start with a sentence, a feeling, or a what-if. Give it somewhere to go."],
  ["A concept", "Explore how an existing creative direction could look on screen."],
  ["An image", "Use a reference to guide the character, subject, object, or world."],
  ["A video", "Start from a selected frame and describe the motion you want to create."],
];

export function StartingPointsSection() {
  return (
    <section id="starting-points" className="mx-auto max-w-[1200px] px-6 py-24 md:py-28">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div className="max-w-[640px]">
          <span className="eyebrow">Start where you are</span>
          <h2 className="serif mt-5 text-[clamp(2rem,4.2vw,3.25rem)]">
            A blank page is only one way in.
          </h2>
        </div>
        <Button size="lg" variant="outline" render={<Link href="/studio" />}>
          Bring your starting point
          <ArrowRight data-icon="inline-end" className="size-4" />
        </Button>
      </div>
      <div className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {STARTS.map(([title, body], i) => (
          <article
            key={title}
            className="rounded-[14px] border border-border bg-card p-6 transition-colors hover:border-[#343331]"
          >
            <span className="eyebrow">0{i + 1}</span>
            <h3 className="serif mt-8 text-2xl">{title}</h3>
            <p className="mt-3 text-sm leading-relaxed text-[#afafaf]">{body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
