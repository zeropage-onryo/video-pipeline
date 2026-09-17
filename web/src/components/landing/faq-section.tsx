// Straight answers, in the order a first-time visitor asks them. Pricing is
// answered here in one honest line instead of on a pricing page: nothing is
// priced yet, and a page that pretends otherwise would be the first lie on
// the site. Native <details> so it works with no JS.

const FAQS: Array<[string, string]> = [
  [
    "What is ZeroPage, in one line?",
    "An AI creative studio that takes an idea, grounds it in your references, and turns it into scenes, keyframes, and clips you decide are worth making.",
  ],
  [
    "Who is it for?",
    "Filmmakers, brands, and creators who think in scenes and worlds and want a pipeline, not a chat box.",
  ],
  [
    "What does it cost?",
    "Nothing during the pilot. The pilot is invite-only, and each account gets a daily render allowance on the studio's own keys. Pricing comes after the pilot and will be per-render credits rather than a flat seat, because that is how the costs actually fall.",
  ],
  [
    "Which models does it render on?",
    "Runway, Kling, LTX, Wan, Seedance, and Higgsfield today, chosen per shot. Keyframes are drawn on Nano Banana Pro. You can also plug in your own provider keys and render on your own account.",
  ],
  [
    "Does it use my references, or anyone's, without asking?",
    "No. A render is grounded only on the references attached to that scene. Nothing from your library is pulled in by default, and nothing from anyone else's library is ever pulled in.",
  ],
  [
    "Who owns what comes out?",
    "You do, subject to each model provider's own terms. We claim no rights in your uploads or your renders, and we do not use them to train anything.",
  ],
  [
    "Is there an API?",
    "Not yet. The studio runs on the web and on your phone. An API comes when someone needs one badly enough to ask.",
  ],
];

export function FaqSection() {
  return (
    <section id="faq" className="relative z-10 border-t border-border/60">
      <div className="mx-auto max-w-6xl px-6 py-28">
        <div className="mb-12 flex flex-col gap-4">
          <span className="kicker">Before you ask</span>
          <h2 className="display max-w-3xl text-balance text-4xl sm:text-6xl">Straight answers.</h2>
        </div>
        <div className="border-t border-border/60">
          {FAQS.map(([q, a]) => (
            <details key={q} className="group border-b border-border/60">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-6 py-6 [&::-webkit-details-marker]:hidden">
                <span className="display text-xl sm:text-2xl">{q}</span>
                <span
                  aria-hidden
                  className="font-mono text-2xl leading-none text-primary transition-transform duration-300 group-open:rotate-45"
                >
                  +
                </span>
              </summary>
              <p className="max-w-2xl pb-7 text-sm font-light leading-relaxed text-muted-foreground">{a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
