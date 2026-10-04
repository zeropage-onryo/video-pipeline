import type { Metadata } from "next";
import Link from "next/link";
import { LEGAL_CONTACT, LegalPage, type LegalSection } from "@/components/legal-page";
import { CATALOG } from "@/lib/catalog";

// Plain-language terms. A first draft written 2026-09-17 alongside
// /privacy; not yet reviewed by a lawyer. Governing law names the United
// States and no state (2026-09-18, Mike's call). Rewritten 2026-10-03 for
// what is live: open sign-up with a trial grant (2026-09-24), plans,
// credits and Stripe (2026-09-18, docs/BILLING.md -- the numbers here are
// read off the catalog so the page cannot drift from /pricing), the
// optional ChatGPT / Claude sign-in, and nothing posting on anyone's
// behalf.

export const metadata: Metadata = {
  title: "Terms of Service",
  description:
    "The terms for using Zero Page: accounts, credits and payment, your content, AI-generated output, third-party providers and acceptable use.",
  alternates: { canonical: "/terms" },
};

const SECTIONS: LegalSection[] = [
  {
    title: "The agreement",
    body: (
      <p>
        These terms cover your use of Zero Page (&ldquo;the Studio&rdquo;), an AI content studio
        operated by Michael Massaad. By signing in or using the Studio you agree to them, and to
        the <Link href="/privacy">Privacy Policy</Link>. If you do not agree, do not use the
        Studio.
      </p>
    ),
  },
  {
    title: "Accounts & access",
    body: (
      <p>
        Anyone can sign up. Your first sign-in creates a workspace of your own; other people reach
        it only when a member invites them, and you are responsible for whom you invite and for
        activity under your sign-in. Keep it secure. You must be at least 13, and old enough to
        enter into these terms where you live. Access may be suspended or ended for a breach of
        these terms.
      </p>
    ),
  },
  {
    title: "Plans, credits & payment",
    body: (
      <>
        <p>
          The Studio is paid for in credits. A new workspace receives a one-time trial grant;
          after that, credit comes from a plan or a top-up on the{" "}
          <Link href="/pricing">pricing page</Link>. Writing scenes is included while you hold a
          plan or any credit balance. Stills and renders cost credits, at the price the Studio
          shows before you approve them; a render the provider fails to deliver is not charged, and
          anything held for it is released back to you. A render that completes is charged whether
          or not you like the result.
        </p>
        <p>
          Every grant expires {CATALOG.expiry_months} months after it lands. A yearly plan is billed
          once and released month by month, each month on its own clock. You can change or cancel a
          plan at any time from the billing portal; a cancelled plan stays active to the end of the
          period you paid for, and any allowance remaining from it ends with it. Credits have no
          cash value, cannot be transferred between accounts, and are not refundable except where
          the law requires. Payments are processed by Stripe under its own terms. Prices may change;
          a change is posted on the pricing page and applies from your next billing period.
        </p>
      </>
    ),
  },
  {
    title: "Your content",
    body: (
      <>
        <p>
          You keep ownership of everything you upload — photos, reference images, scripts, ideas —
          and you are responsible for having the rights to it, including the consent of any
          identifiable person whose likeness you upload as a reference.
        </p>
        <p>
          You give Zero Page permission to store, process and transmit that material only as
          needed to run the Studio for you: grounding the writing, drawing keyframes, and sending
          a scene&apos;s prompt and references to the rendering provider you choose.
        </p>
      </>
    ),
  },
  {
    title: "AI-generated output",
    body: (
      <>
        <p>
          As between you and Zero Page, the concepts, prompts, images and video the Studio
          generates for your account are yours to use, subject to the terms of the model provider
          that produced them.
        </p>
        <p>
          Output is produced by AI models. It can be inaccurate, can resemble existing work, and
          may not be eligible for copyright protection in every jurisdiction. Review it before you
          publish it; what you publish is your responsibility.
        </p>
      </>
    ),
  },
  {
    title: "Third-party providers & costs",
    body: (
      <p>
        The Studio runs on third-party services — model and rendering providers, storage,
        payments and hosting — listed in the <Link href="/privacy">Privacy Policy</Link>. Your use
        of them through the Studio is also subject to their own terms. If you connect your own
        ChatGPT or Claude account to write with, you do so under that provider&apos;s terms and
        your own agreement with it, and you can disconnect it at any time. Any dollar figures the
        Studio shows beside a credit price are estimates, not invoices. Rendering only happens when
        you approve it, and nothing is ever posted anywhere on your behalf.
      </p>
    ),
  },
  {
    title: "Acceptable use",
    body: (
      <>
        <p>Do not use the Studio to:</p>
        <ul>
          <li>break the law or infringe anyone&apos;s intellectual-property, privacy or publicity rights;</li>
          <li>
            depict a real person in a deceptive, defamatory or sexual way, or without the consent
            their likeness requires;
          </li>
          <li>generate content that sexualizes minors, or that promotes violence or harassment;</li>
          <li>get around a provider&apos;s safety systems, usage limits or terms;</li>
          <li>probe, overload or reverse-engineer the service, or access another account&apos;s data;</li>
          <li>
            share sign-ins or open repeat workspaces to collect the trial grant more than once.
          </li>
        </ul>
      </>
    ),
  },
  {
    title: "An experimental service",
    body: (
      <p>
        Zero Page is an early, evolving product. Features change, and the service may be
        interrupted or discontinued. It is provided &ldquo;as is&rdquo; and &ldquo;as
        available&rdquo;, without warranties of any kind to the extent the law allows. Keep your
        own copies of anything you cannot afford to lose.
      </p>
    ),
  },
  {
    title: "Liability",
    body: (
      <p>
        To the extent the law allows, Zero Page and its operator are not liable for indirect,
        incidental or consequential damages, or for lost profits, data or goodwill, arising from
        your use of the Studio; and total liability for any claim is limited to the amount you
        paid Zero Page for the Studio in the twelve months before it arose. Nothing in these terms
        limits rights you have by law that cannot be waived.
      </p>
    ),
  },
  {
    title: "Ending & changes",
    body: (
      <p>
        You can stop using the Studio at any time, cancel any plan from the billing portal, and
        ask for your account and its data to be deleted. If access is ended for a breach of these
        terms, unused credit is forfeited. If these terms change materially, the effective date
        above will be updated; continued use after a change means you accept the revised terms.
      </p>
    ),
  },
  {
    title: "Governing law",
    body: (
      <p>
        These terms are governed by the laws of the United States, and any dispute about them or
        about the Studio will be brought in the courts of the United States. If any part of these
        terms is found unenforceable, the rest still applies.
      </p>
    ),
  },
  {
    title: "Contact",
    body: (
      <p>
        Questions about these terms can be sent to{" "}
        <a href={`mailto:${LEGAL_CONTACT}`}>{LEGAL_CONTACT}</a>.
      </p>
    ),
  },
];

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      dek="The plain-language terms for using Zero Page — accounts, credits and payment, your content, what the AI makes, and what is not allowed."
      effective="3 Oct 2026"
      sections={SECTIONS}
    />
  );
}
