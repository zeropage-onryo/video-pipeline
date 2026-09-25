import { Reveal } from "@/components/reveal";
// Who the studio is for: three cards in the same warm-black card system as
// the rest of the page. Copy carried over from the previous section.
const TILES = [
  {
    label: "Filmmakers",
    copy: "Develop scenes, explore visual worlds, and direct the moments that make the story yours.",
  },
  {
    label: "Brands",
    copy: "Turn a brief into campaign concepts shaped around your product and identity.",
  },
  {
    label: "Creators",
    copy: "Give your next short, series, or visual experiment a world of its own.",
  },
];

export function WorkSection() {
  return (
    <section id="work" className="mx-auto max-w-[1200px] px-6 py-24 md:py-28">
      <Reveal className="max-w-[640px]">
        <span className="eyebrow">Who it&apos;s for</span>
        <h2 className="serif mt-5 text-[clamp(2rem,4.2vw,3.25rem)]">
          Made for your kind of creative.
        </h2>
      </Reveal>
      <div className="mt-12 grid gap-3 md:grid-cols-3">
        {TILES.map((tile, i) => (
          <Reveal key={tile.label} delay={i * 0.08}>
          <article
            className="flex h-full min-h-[260px] flex-col justify-between rounded-[14px] border border-border bg-card p-7 transition-colors duration-300 hover:-translate-y-1 hover:border-[#343331] motion-safe:transition-transform"
          >
            <h3 className="serif text-[28px]">{tile.label}</h3>
            <p className="mt-10 text-[15px] leading-relaxed text-[#afafaf]">{tile.copy}</p>
          </article>
          </Reveal>
        ))}
      </div>
    </section>
  );
}
