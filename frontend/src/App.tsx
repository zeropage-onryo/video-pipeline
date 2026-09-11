import { motion } from 'motion/react'
import { useState } from 'react'
import { Composer } from '@/components/Composer'
import { Rail, type ViewId } from '@/components/Rail'

export default function App() {
  const [view, setView] = useState<ViewId>('studio')

  return (
    <>
      {/* the field sits behind everything and is masked away before the
          fold, so the composer lands on near-black */}
      <div className="zpf-field pointer-events-none fixed inset-0 z-0 h-screen" />

      <Rail view={view} onNavigate={setView} />

      {/* the shell keeps its margin whatever the rail is doing */}
      <div className="relative z-10 ml-21 min-h-screen">
        <header className="flex items-center gap-3.5 px-10 py-4.5">
          <span className="font-display text-[15px] font-bold tracking-[0.09em] text-text uppercase">
            ZPF
          </span>
          <span className="text-dimmer">/</span>
          <span className="font-display text-[15px] tracking-[0.09em] text-dim uppercase">
            {view}
          </span>
          <span className="flex-1" />
          <button
            type="button"
            className="label-mono cursor-pointer rounded-full border border-line bg-[rgb(8_8_10/0.4)] px-4 py-1.5 text-[9.5px] backdrop-blur-md transition-colors duration-200 hover:border-line-hi hover:text-text"
          >
            Zero Page
          </button>
        </header>

        {view === 'studio' ? (
          <section className="flex flex-col items-center px-10 pt-[15vh]">
            <motion.h1
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: [0.22, 0.61, 0.36, 1] }}
              className="mb-11 text-center font-display text-[clamp(2.2rem,5.6vw,5rem)] leading-[0.96] font-medium tracking-[-0.018em] uppercase"
            >
              What do you
              <br />
              want to create?
            </motion.h1>
            <Composer />
          </section>
        ) : (
          <section className="flex flex-col items-center px-10 pt-[18vh] text-dim">
            <p className="label-mono">{view} — not built in this app yet</p>
          </section>
        )}
      </div>
    </>
  )
}
