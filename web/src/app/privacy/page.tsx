import type { Metadata } from "next";
import { LegalPage, LegalSection, Fact } from "@/components/legal-page";
import { SITE } from "@/lib/site";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "What ZeroPage collects, why, who it is shared with, and how to get it deleted.",
};

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" sibling={{ href: "/terms", label: "Terms of Use" }}>
      <LegalSection n={1} title="Who is responsible">
        <p>
          <Fact value={SITE.legalEntity} />, <Fact value={SITE.jurisdiction} />, is the data
          controller for {SITE.name}. Contact: <Fact value={SITE.contactEmail} />.
        </p>
      </LegalSection>

      <LegalSection n={2} title="What we collect">
        <ul>
          <li>
            <b className="font-medium text-foreground">Sign-in.</b> When you sign in with Google or
            Discord we receive your name, email address, and avatar. We do not get your password
            and we do not post on your behalf. With email sign-in we hold your email and a hashed
            password.
          </li>
          <li>
            <b className="font-medium text-foreground">What you make.</b> Concepts, references you
            upload, keyframes, renders, and your picks, archives, and reasons. This is the product;
            it is stored so it is there when you come back.
          </li>
          <li>
            <b className="font-medium text-foreground">Provider keys.</b> If you add your own render
            keys they are stored encrypted and used only to submit your renders.
          </li>
          <li>
            <b className="font-medium text-foreground">Usage and cost.</b> Which model was called,
            when, and what it cost, per account. We use this to run allowances and to see what the
            studio is spending.
          </li>
          <li>
            <b className="font-medium text-foreground">Technical.</b> Server logs with IP address,
            browser, and timestamps, kept briefly for security and debugging.
          </li>
        </ul>
        <p>We do not use advertising trackers, and we do not sell data.</p>
      </LegalSection>

      <LegalSection n={3} title="Why we use it">
        <p>
          To run the service you signed up for, to keep it secure, to enforce allowances, and to
          improve it. We use your picks and archive reasons to make the studio&apos;s ideas better
          for your account. We do not use your uploads or renders to train foundation models.
        </p>
      </LegalSection>

      <LegalSection n={4} title="Who we share it with">
        <ul>
          <li>
            <b className="font-medium text-foreground">Model providers</b> (Runway, fal.ai,
            Higgsfield, Google, Midjourney, and others we add): your prompts and references are sent
            to them to produce keyframes and renders. Each has its own privacy policy.
          </li>
          <li>
            <b className="font-medium text-foreground">Infrastructure:</b> Supabase (database and
            sign-in), Fly.io and Vercel (hosting), Cloudflare (storage).
          </li>
          <li>
            <b className="font-medium text-foreground">Legal:</b> if we are required to by law.
          </li>
        </ul>
        <p>No one else. We do not share your data with advertisers or data brokers.</p>
      </LegalSection>

      <LegalSection n={5} title="Google user data">
        <p>
          Our use of information received from Google APIs follows the{" "}
          <a href="https://developers.google.com/terms/api-services-user-data-policy" rel="noopener noreferrer" target="_blank">
            Google API Services User Data Policy
          </a>
          , including the Limited Use requirements. We request only basic profile and email
          scopes, to identify your account.
        </p>
      </LegalSection>

      <LegalSection n={6} title="How long we keep it">
        <p>
          For as long as your account exists. Archived concepts are kept, not deleted, so you can
          bring them back. Logs are kept for <Fact value={SITE.logRetentionDays} /> days. When you
          close your account we delete your data within 30 days, except where we must keep it by
          law.
        </p>
      </LegalSection>

      <LegalSection n={7} title="Your rights">
        <p>
          You can ask for a copy of your data, ask us to correct it, or ask us to delete it, by
          emailing <Fact value={SITE.contactEmail} />. If you are in the EU, UK, or California you
          have additional rights under local law, and you can use the same address to exercise
          them.
        </p>
      </LegalSection>

      <LegalSection n={8} title="Security">
        <p>
          Data is stored with access controls per account, provider keys are encrypted at rest,
          and the service is served over HTTPS. No system is perfect; if there is a breach
          affecting you we will tell you.
        </p>
      </LegalSection>

      <LegalSection n={9} title="Children">
        <p>
          {SITE.name} is not for anyone under 18. We do not knowingly collect data from minors; if
          we learn we have, we delete it.
        </p>
      </LegalSection>

      <LegalSection n={10} title="Changes">
        <p>
          If this policy changes materially we will tell you by email or in the app before it
          takes effect.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
