import type { Metadata } from "next";
import Link from "next/link";
import { LEGAL_CONTACT, LegalPage, type LegalSection } from "@/components/legal-page";

// Plain-language terms for an invite-based product. A first draft written
// 2026-09-17 alongside /privacy; not yet reviewed by a lawyer. Governing
// law names the United States and no state (2026-09-18, Mike's call).

export const metadata: Metadata = {
  title: "Terms of Service",
  description:
    "The terms for using Zero Page: accounts, your content, AI-generated output, third-party providers and acceptable use.",
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
        Access is by invitation. Signing in does not by itself grant access to any account;
        membership is granted by an existing member. You are responsible for activity under your
        sign-in and for keeping it secure. You must be at least 13, and old enough to enter into
        these terms where you live. Access may be suspended or ended for a breach of these terms.
      </p>
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
        The Studio runs on third-party services — model and rendering providers, storage and
        hosting — listed in the <Link href="/privacy">Privacy Policy</Link>. Your use of them
        through the Studio is also subject to their own terms. Renders are charged in credits at the
        price the Queue shows before you approve; any dollar figures the Studio shows beside them
        are estimates, not invoices. Rendering only happens when you approve it.
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
          <li>probe, overload or reverse-engineer the service, or access another account&apos;s data.</li>
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
        You can stop using the Studio at any time and ask for your account and its data to be
        deleted. If these terms change materially, the effective date above will be updated;
        continued use after a change means you accept the revised terms.
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
      dek="The plain-language terms for using Zero Page — accounts, your content, what the AI makes, and what is not allowed."
      effective="17 Sep 2026"
      sections={SECTIONS}
    />
  );
}
