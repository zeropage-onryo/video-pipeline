import type { Metadata } from "next";
import { LEGAL_CONTACT, LegalPage, type LegalSection } from "@/components/legal-page";

// Ported 2026-09-17 from the policy the API origin serves
// (app/templates/privacy.html -- the URL already on file with the OAuth app
// registrations). This copy names the providers added since: the rendering
// services, R2 and Vercel. A change to one should be made to the other.

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
        Zero Page (&ldquo;the Studio&rdquo;) is an AI content studio: it turns ideas, scripts and
        reference photography into concepts, scene prompts and AI-generated images and video. It is
        operated as a small, invite-based product by Michael Massaad, not a public consumer app
        with open sign-up.
      </p>
    ),
  },
  {
    title: "Accounts",
    body: (
      <p>
        Signing in uses Supabase Auth, either by email and password or by OAuth through a provider
        such as Google or Discord. Zero Page never sees or stores your password with those
        providers — they authenticate you and return a verified email address, which Supabase and
        Zero Page use to identify your account. A session is kept in a single signed, HTTP-only
        cookie on your device; signing out clears it. Zero Page sets no advertising or tracking
        cookies.
      </p>
    ),
  },
  {
    title: "What's collected",
    body: (
      <ul>
        <li>
          <strong>Account</strong> — email address and account identifier.
        </li>
        <li>
          <strong>Production material</strong> — photos, reference images and other media you
          upload, plus the concepts, prompts and AI-generated images and video produced from them.
        </li>
        <li>
          <strong>Reference sources</strong> — where you connect a service like Instagram or
          Pinterest, the Studio reads boards, pins or posts from an account you authorize, to
          gather visual reference for your own projects.
        </li>
        <li>
          <strong>Your own provider keys</strong> — if you add an API key for a rendering service,
          it is stored against your account and used only to run your own generations.
        </li>
        <li>
          <strong>Usage</strong> — basic operational data (timestamps, error logs, model-call
          counts) used to keep the pipeline running, meter cost and grade output quality.
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
            <strong>Supabase</strong> — authentication and database storage.
          </li>
          <li>
            <strong>Google (Gemini API)</strong> — AI writing, reasoning and image generation over
            your material.
          </li>
          <li>
            <strong>Video rendering providers</strong> (Runway, fal.ai, Higgsfield, Google Veo) —
            when you approve a render, the scene&apos;s prompt and its reference images are sent to
            the provider you chose.
          </li>
          <li>
            <strong>Cloudflare R2</strong> — storage for reference images and rendered media.
          </li>
          <li>
            <strong>Meta (Instagram Graph API) / Pinterest API</strong> — read-only reference
            gathering from accounts you explicitly authorize.
          </li>
          <li>
            <strong>Vercel and Fly.io</strong> — application hosting.
          </li>
        </ul>
        <p className="text-muted-foreground">
          None of these providers receive more than what is needed to perform their function, and
          Zero Page does not authorize any of them to use Studio data for advertising.
        </p>
      </>
    ),
  },
  {
    title: "What doesn't happen",
    body: (
      <p className="border-l-2 border-primary bg-card/60 px-5 py-4 text-muted-foreground">
        Zero Page does not sell data, run ads, or share your media, images or account details with
        data brokers or marketers. Reference-gathering integrations are read-only — the Studio
        never posts, edits or deletes anything on a connected account without an explicit action
        from you.
      </p>
    ),
  },
  {
    title: "Retention & control",
    body: (
      <p>
        Production material and account data are kept for as long as your account is active. You
        can ask for your account and its data to be deleted, or revoke any connected third-party
        account (under that service&apos;s own connected-apps settings), at any time — see contact
        below.
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
      effective="17 Sep 2026"
      sections={SECTIONS}
    />
  );
}
