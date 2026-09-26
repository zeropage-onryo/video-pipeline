import type { Metadata } from "next";
import Link from "next/link";
import { EditorialSkin } from "@/components/editorial-skin";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { PageIntro } from "@/components/site/page-intro";
import { FaqList, type Faq } from "@/components/site/faq-list";
import { CATALOG } from "@/lib/catalog";

export const metadata: Metadata = {
  title: "FAQ",
  description: "What Zero Page is, how a scene gets from a spark to a clip, what references do, and what it costs.",
};

const GROUPS: { title: string; items: Faq[] }[] = [
  {
    title: "The studio",
    items: [
      {
        q: "What is Zero Page?",
        a: (
          <p>
            An AI pre-production studio. You bring a spark — a line, a script passage, an image — and the
            studio writes a short scene worth shooting, grounds it in the references you attached, draws its
            first frame, and renders the clip on the model you choose. Editing stays yours.
          </p>
        ),
      },
      {
        q: "What do I actually get out of it?",
        a: (
          <p>
            Rendered clips, one per shot, with the keyframe and the prompt that made each. A scene is written
            as timed shots and rendered one shot at a time; the parts are listed in order for you to cut
            together in your editor.
          </p>
        ),
      },
      {
        q: "Who is it for?",
        a: (
          <p>
            Filmmakers developing a look before a shoot, brands turning a brief into campaign concepts, and
            creators who post every week and need a world of their own to post from.
          </p>
        ),
      },
      {
        q: "Does it post for me?",
        a: (
          <p>
            No. Everything lands in your Queue and a person pushes it out. Publishing exists in the pipeline but
            is held off on purpose until you choose to turn it on.
          </p>
        ),
      },
    ],
  },
  {
    title: "How a scene is made",
    items: [
      {
        q: "What is a spark?",
        a: (
          <p>
            The direction a scene starts from: a sentence, a feeling, a what-if. You type one, or the research
            scout finds candidates from what&apos;s landing right now and banks the best. Each spark becomes one
            scene, one prompt.
          </p>
        ),
      },
      {
        q: "What do references do?",
        a: (
          <p>
            They are what grounds a scene. Characters, props, locations and the images you upload are attached
            to the shot, and the keyframe is drawn from them — a scene with no references never reaches the
            board, because a clip anchored on nothing is a clip anchored on the model&apos;s guess.
          </p>
        ),
      },
      {
        q: "What is the Director?",
        a: (
          <p>
            The canvas where one shot&apos;s chain is laid out: the prompt, its references, the enhance, the
            keyframe, the renderer. You edit the prompt, swap a reference, redraw the still, then send it to
            the Queue.
          </p>
        ),
      },
      {
        q: "Where is money spent?",
        a: (
          <p>
            In one place: approving a render in the Queue. Writing, picking and drawing keyframes are part of
            the plan. The card shows the price in credits before you press it, and that price is what is
            charged.
          </p>
        ),
      },
      {
        q: "Which models can I render on?",
        a: (
          <p>
            Kling, LTX, Wan, Seedance and Veo, all rendered through fal and chosen per approve. The{" "}
            <Link href="/models">models page</Link> lists each with its tier and what a clip costs.
          </p>
        ),
      },
    ],
  },
  {
    title: "Plans and credits",
    items: [
      {
        q: "How much does it cost?",
        a: (
          <p>
            Three monthly plans — see <Link href="/pricing">pricing</Link> — and a one-time top-up. One credit
            is one cent; a render costs the model&apos;s own rate for the length you picked, so the cheapest
            clip is a few dozen credits and the most expensive a few hundred.
          </p>
        ),
      },
      {
        q: "Do credits expire?",
        a: (
          <p>
            {CATALOG.expiry_months} months after they land. Your monthly allowance is spent before any credit
            you bought.
          </p>
        ),
      },
      {
        q: "Who owns what I make?",
        a: (
          <p>
            You do, within each model provider&apos;s own terms. The <Link href="/terms">terms</Link> and{" "}
            <Link href="/privacy">privacy</Link> pages spell out what the studio keeps and what it never does
            with your references.
          </p>
        ),
      },
    ],
  },
];

export default function FaqPage() {
  return (
    <EditorialSkin>
      <SiteHeader />
      <main className="flex-1">
        <PageIntro
          eyebrow="FAQ"
          title="Questions, answered plainly."
          dek="How the studio works, what a scene is made of, and what it costs. If it isn't here, the terms and privacy pages hold the rest."
        />
        <section className="mx-auto max-w-[760px] px-6 pb-24">
          {GROUPS.map((group, i) => (
            <div key={group.title} className={i === 0 ? "" : "mt-16"}>
              <h2 className="serif mb-6 text-[clamp(1.5rem,3vw,2rem)]">{group.title}</h2>
              <FaqList items={group.items} />
            </div>
          ))}
        </section>
      </main>
      <SiteFooter />
    </EditorialSkin>
  );
}
