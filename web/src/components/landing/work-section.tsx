// LTX-style first section: a full-bleed 3-up media grid directly under the
// hero. The frames lead; each tile carries only a plain bottom-left label.
// Placeholder frames -- deliberately NOT fabricated footage; each tile reads
// as a labelled slate awaiting a real still/clip from the footage bank.

const TILES = [
  { label: "Filmmakers", slate: "01 / FILM", copy: "Develop scenes, explore visual worlds, and direct the moments that make the story yours." },
  { label: "Brands", slate: "02 / BRAND", copy: "Turn a brief into campaign concepts shaped around your product and identity." },
  { label: "Creators", slate: "03 / CULTURE", copy: "Give your next short, series, or visual experiment a world of its own." },
];

export function WorkSection() {
  return (
    <section id="work" className="relative z-10 mx-auto max-w-6xl px-6 py-28">
      <div className="mb-14 max-w-3xl">
        <span className="kicker">Made for your kind of creative</span>
        <h2 className="display mt-5 text-5xl sm:text-7xl">Big vision.<br />Meet your studio.</h2>
      </div>
      <div className="grid grid-cols-1 gap-px overflow-hidden border border-border bg-border md:grid-cols-3">
        {TILES.map((tile) => (
          <div
            key={tile.slate}
            className="group relative flex min-h-[420px] flex-col justify-between overflow-hidden bg-gradient-to-br from-neutral-700 via-neutral-900 to-black p-7"
          >
            {/* Bottom scrim so the label stays legible over any frame. */}
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/80 to-transparent"
            />
            <span className="film-slate relative text-muted-foreground">{tile.slate}</span>
            <div className="relative"><h3 className="display text-4xl">{tile.label}</h3><p className="mt-4 text-sm leading-relaxed text-muted-foreground">{tile.copy}</p></div>
          </div>
        ))}
      </div>
    </section>
  );
}
