import type { Metadata } from "next";
import Link from "next/link";
import { LEGAL_CONTACT, LegalPage, type LegalSection } from "@/components/legal-page";

// Ported 2026-09-17 from the policy the API origin serves
// (app/templates/privacy.html -- the URL already on file with the OAuth app
// registrations). Rewritten 2026-10-03 against what the product actually
// does now: open sign-up with a trial grant (2026-09-24), Stripe billing
// (2026-09-18), the Serper image search behind the Guide, the optional
// ChatGPT / Claude sign-in, and BYOK gone (2026-09-26). The research
// accounts (Instagram, Pinterest, YouTube) are the operator's own, never a
// member's, and the policy says so now. A change to one copy should be
// made to the other.

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "What Zero Page collects, why, and how it is handled — across the studio itself and the third-party services it connects to.",
  alternates: { canonical: "/privacy" },
};

const SECTIONS: LegalSection[] = [
  {
    title: "What this is",
    body: (
      <p>
        Zero Page (&ldquo;the Studio&rdquo;) is an AI pre-production studio: it turns ideas, scripts and
        reference photography into scene prompts, keyframes and AI-generated video. It is operated by
        Michael Massaad, trading as Zero Page Films, from the United States. Anyone can sign up; a new
        workspace starts with a small one-time grant of trial credits, and everything beyond that is
        paid for through the plans on the <Link href="/pricing">pricing page</Link>.
      </p>
    ),
  },
  {
    title: "Signing in",
    body: (
      <>
        <p>
          Signing in uses Supabase Auth, either by email and password or through Google or Discord.
          Zero Page never sees or stores your password with those providers. When you sign in with
          Google or Discord, the Studio receives only your basic profile: your email address, display
          name and profile picture. They are used to create and identify your account and for nothing
          else. Zero Page&apos;s use of information received from Google APIs adheres to the{" "}
          <a
            href="https://developers.google.com/terms/api-services-user-data-policy"
            target="_blank"
            rel="noreferrer"
          >
            Google API Services User Data Policy
          </a>
          , including the Limited Use requirements.
        </p>
        <p>
          A session is kept in a single signed, HTTP-only cookie on your device, valid for 30 days;
          signing out clears it. One further cookie remembers which workspace you had open, and your
          browser&apos;s own storage keeps an unsent draft so it survives a reload. Zero Page sets no
          advertising or tracking cookies and loads no analytics scripts.
        </p>
      </>
    ),
  },
  {
    title: "What's collected",
    body: (
      <ul>
        <li>
          <strong>Account</strong> — email address, display name, profile picture, an account
          identifier, and which workspaces you belong to.
        </li>
        <li>
          <strong>Production material</strong> — the photos, reference images, audio and video you
          upload; the characters, props and places you add; and the ideas, scene prompts,
          keyframes, rendered clips and cuts produced from them. A web link you paste into the
          Guide is fetched once, by the Studio, to read that page&apos;s own preview image.
        </li>
        <li>
          <strong>Billing</strong> — your plan, your credit balance and a ledger of what each render
          and still cost. Card details are entered on Stripe&apos;s pages and held by Stripe; the
          Studio stores a Stripe customer identifier and the email on it, never a card number.
        </li>
        <li>
          <strong>Connected model accounts</strong> — optionally, your own ChatGPT or Claude sign-in,
          if you connect one to write with. The signed-in session those providers issue is kept on
          the Studio&apos;s server, scoped to your account, used only when you ask that model to
          work, and removed when you press Disconnect.
        </li>
        <li>
          <strong>Usage</strong> — basic operational data (timestamps, error logs, model-call counts
          and their cost) used to keep the pipeline running, meter spend and grade output quality.
        </li>
      </ul>
    ),
  },
  {
    title: "Third-party services",
    body: (
      <>
        <p>
          The Studio relies on a small set of providers to function, each under its own privacy
          policy:
        </p>
        <ul>
          <li>
            <strong>Supabase</strong> — authentication and database storage. The sign-in step may
            be served under a zeropage.studio address or a supabase.co one; both are this project.
          </li>
          <li>
            <strong>Google (Gemini API)</strong> — writing and judging scenes, describing the photos
            you upload, and drawing keyframes and reference sheets from them.
          </li>
          <li>
            <strong>fal.ai</strong> — video rendering. When you approve a render, the shot&apos;s
            prompt and its reference images are sent to fal.ai, which runs the model you picked
            (from Kling, ByteDance, Lightricks, Alibaba or Google). When you index footage in the
            editor, a clip&apos;s speech is transcribed there too.
          </li>
          <li>
            <strong>Serper</strong> — the web image search behind the Guide&apos;s reference
            suggestions. It receives the search text only, never your material.
          </li>
          <li>
            <strong>Stripe</strong> — payments and subscriptions.
          </li>
          <li>
            <strong>Cloudflare R2</strong> — storage for reference images and rendered media.
          </li>
          <li>
            <strong>OpenAI and Anthropic</strong> — only if you connect your own ChatGPT or Claude
            account, and only for the work you send to it.
          </li>
          <li>
            <strong>Vercel and Fly.io</strong> — application hosting.
          </li>
        </ul>
        <p className="text-muted-foreground">
          The Studio&apos;s research scout also reads public feeds and the operator&apos;s own
          connected Instagram, Pinterest and YouTube accounts for visual reference. It never reads
          a member&apos;s social accounts: the Studio asks for no access to them. None of the
          providers above receive more than what is needed to perform their function, and Zero
          Page does not authorize any of them to use Studio data for advertising.
        </p>
      </>
    ),
  },
  {
    title: "What doesn't happen",
    body: (
      <p className="border-l-2 border-primary bg-card/60 px-5 py-4 text-muted-foreground">
        Zero Page does not sell data, run ads, train models on your material, or share your media,
        images or account details with data brokers or marketers. Nothing is posted anywhere on
        your behalf: every render lands in your Queue, and publishing is an explicit action a person
        takes.
      </p>
    ),
  },
  {
    title: "Retention & control",
    body: (
      <p>
        Production material and account data are kept for as long as your account is active.
        Deleting a render in the Studio removes it from your library at once; the file itself is
        kept until your account is deleted, so a scene that used it keeps playing. You can
        disconnect a connected model account at any time from its settings, and you can ask for your
        account and all of its data to be deleted — see contact below.
      </p>
    ),
  },
  {
    title: "Children",
    body: (
      <p>
        Zero Page is a professional production tool and is not directed at or knowingly used by
        children under 13.
      </p>
    ),
  },
  {
    title: "Changes",
    body: (
      <p>
        If this policy changes materially, the effective date above will be updated. Continued use
        of the Studio after a change means you accept the revised policy.
      </p>
    ),
  },
  {
    title: "Contact",
    body: (
      <p>
        Questions about this policy or your data can be sent to{" "}
        <a href={`mailto:${LEGAL_CONTACT}`}>{LEGAL_CONTACT}</a>.
      </p>
    ),
  },
];

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      dek="What Zero Page collects, why, and how it is handled — across the studio itself and the third-party services it connects to."
      effective="3 Oct 2026"
      sections={SECTIONS}
    />
  );
}
