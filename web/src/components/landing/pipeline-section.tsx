import Link from "next/link";
import { Button } from "@/components/ui/button";

// The pipeline is a genuine ordered sequence -- ground, then write, then
// approve, then render -- so numbering the steps is load-bearing, not
// decoration. First three are the "rules the studio won't let you skip";
// render is the payoff at the end.

const STEPS = [
  {
    n: "01",
    title: "Develop the direction",
    body: "Turn a spark, a brief, or a passage from your script into several scene concepts worth exploring.",
  },
  {
    n: "02",
    title: "Build the visual world",
    body: "Attach characters, objects, locations, and visual references so every scene begins from your material.",
  },
  {
    n: "03",
    title: "Direct every frame",
    body: "Shape prompts, connect references, and create keyframes in a canvas built for creative decisions.",
  },
  {
    n: "04",
    title: "Put it in motion",
    body: "Choose a model, frame, and duration, then generate the image or clip you decided was worth making.",
  },
];

export function PipelineSection() {
  return (
    <section id="pipeline" className="relative z-10 mx-auto max-w-6xl px-6 py-28">
      <div className="mb-16 flex flex-col gap-4">
        <span className="kicker">The creative toolkit</span>
        <h2 className="display max-w-3xl text-balance text-4xl sm:text-6xl">
          Everything starts with your direction.
        </h2>
        <p className="max-w-xl text-muted-foreground">Move between ideas, references, scenes, and generations while keeping every creative decision connected.</p>
      </div>

      <div className="grid gap-px overflow-hidden border border-border/60 bg-border/60 sm:grid-cols-2">
        {STEPS.map((step) => (
          <div
            key={step.n}
            className="group relative flex flex-col gap-4 bg-card p-8 transition-colors duration-300 hover:bg-secondary/40 sm:p-10"
          >
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-3xl font-medium text-primary/80">{step.n}</span>
              <span
                aria-hidden
                className="h-px w-10 bg-border transition-all duration-300 group-hover:w-16 group-hover:bg-primary/60"
              />
            </div>
            <h3 className="display text-2xl sm:text-3xl">{step.title}</h3>
            <p className="text-sm font-light leading-relaxed text-muted-foreground">{step.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

const STARTS = [
  ["A script", "Bring a scene or passage into your brief and develop its visual direction."],
  ["An idea", "Start with a sentence, a feeling, or a what-if. Give it somewhere to go."],
  ["A concept", "Explore how an existing creative direction could look on screen."],
  ["An image", "Use a reference to guide the character, subject, object, or world."],
  ["A video", "Start from a selected frame and describe the motion you want to create."],
];

export function StartingPointsSection() {
  return <section id="starting-points" className="bg-foreground text-background">
    <div className="mx-auto max-w-6xl px-6 py-28">
      <span className="film-slate opacity-60">Start where you are</span>
      <h2 className="display mt-5 max-w-3xl text-5xl sm:text-7xl">A blank page is only one way in.</h2>
      <div className="mt-16 grid border-y border-black/20 md:grid-cols-5">
        {STARTS.map(([title, body], i) => <article key={title} className="border-b border-black/20 p-6 md:border-b-0 md:border-r last:border-r-0">
          <span className="font-mono text-xs opacity-50">0{i+1}</span><h3 className="display mt-10 text-2xl">{title}</h3><p className="mt-4 text-sm leading-relaxed opacity-65">{body}</p>
        </article>)}
      </div>
      <Button className="mt-10 h-12 bg-background px-8 text-foreground hover:bg-background/90" render={<Link href="/studio" />}>Bring your starting point</Button>
    </div>
  </section>;
}
