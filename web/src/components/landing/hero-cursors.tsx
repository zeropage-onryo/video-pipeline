// Four cursors drifting over the hero, each tagged with who is at the
// canvas: you, and the three agents that actually work the board -- the
// scout that finds sparks, the director that writes and plans the scene,
// the queue that renders what you approve. Named for real pipeline
// stages (src/scout.py, src/scene_chain.py, the Queue), not invented
// teammates. Hidden below md, where they would sit on the headline.

type Cursor = {
  name: string;
  color: string;
  className: string;
  delay: string;
};

const CURSORS: Cursor[] = [
  { name: "You", color: "var(--signal)", className: "left-[6%] top-10", delay: "-0.2s" },
  { name: "Scout", color: "#1f9d64", className: "right-[6%] top-9", delay: "-1.4s" },
  { name: "Director", color: "#4f5be6", className: "left-[8%] top-[400px]", delay: "-2.8s" },
  { name: "Queue", color: "#8b5cf6", className: "right-[8%] top-[400px]", delay: "-4.1s" },
];

export function HeroCursors() {
  return (
    <>
      {CURSORS.map((cursor) => (
        <div
          key={cursor.name}
          aria-hidden
          className={`cursor-float pointer-events-none absolute z-40 hidden flex-col items-start md:flex ${cursor.className}`}
          style={{ animationDelay: cursor.delay }}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-[22px] w-[22px] drop-shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
            fill={cursor.color}
            stroke="#fff"
            strokeWidth="1.4"
            strokeLinejoin="round"
          >
            <path d="M5.2 3.4 19.4 12.3 12.9 13.5 16.3 20.4 13.6 21.6 10.1 14.7 5.2 19.1Z" />
          </svg>
          <span
            className="-mt-0.5 ml-3.5 inline-flex items-center whitespace-nowrap rounded-[5px] px-2 pb-1 pt-[3px] text-xs font-semibold leading-none tracking-[0.01em] text-white shadow-[0_1px_2px_rgba(0,0,0,0.25)]"
            style={{ backgroundColor: cursor.color }}
          >
            {cursor.name}
          </span>
        </div>
      ))}
    </>
  );
}
