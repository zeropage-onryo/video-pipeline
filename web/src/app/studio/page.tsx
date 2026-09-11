"use client";

// This is the authenticated product surface -- what a signed-in user
// lands on. It's deliberately a thin placeholder: the real interface is
// the cinematic, WebGL-driven studio design already being iterated on
// separately (signal-red branding, synthesized footage frames -- see
// zpf-pipeline.md in project memory), not something to fake here.
//
// What this page actually proves: the cross-origin cookie session
// works end to end (Next.js on one origin, FastAPI on Fly on another),
// by pulling one real number from the API.
//
// Client component, not a server component, on purpose -- the session
// cookie is SameSite=None but still only sent by the browser; a Next.js
// server component's fetch wouldn't carry it without manually forwarding
// the incoming request's Cookie header, which buys nothing for a page
// that's authenticated-only anyway (no SEO, no SSR benefit to chase
// here). See frontend_cors.md in project memory.

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ApertureMark } from "@/components/aperture-mark";
import { apiFetch, checkSession, goToSignIn, signOut } from "@/lib/api";

type Status = "checking" | "signed-out" | "ready" | "error";

export default function StudioPage() {
  const [status, setStatus] = useState<Status>("checking");
  const [pipelineCount, setPipelineCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const authed = await checkSession().catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
        return false;
      });
      if (cancelled) return;
      if (!authed) {
        setStatus("signed-out");
        return;
      }
      try {
        const board = await apiFetch<{ items: unknown[] }>(
          "/pipeline/concepts",
        );
        if (cancelled) return;
        setPipelineCount(board.items.length);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <StudioShell status={status}>
      {status === "checking" && (
        <>
          <ApertureMark className="h-9 w-9 text-primary animate-aperture" />
          <p className="mt-6 text-muted-foreground">Checking your session…</p>
        </>
      )}

      {status === "signed-out" && (
        <>
          <StateHeading kicker="Studio access">Restricted set</StateHeading>
          <p className="mt-4 max-w-md text-sm font-light leading-relaxed text-muted-foreground">
            You need to sign in before you can step onto the studio floor.
          </p>
          <Link
            href="/studio/flows"
            className="mt-6 text-sm underline underline-offset-4"
          >
            Open Flow workspace
          </Link>
          <Button className="mt-8 h-12 px-8" onClick={goToSignIn}>
            Sign in
          </Button>
        </>
      )}

      {status === "error" && (
        <>
          <StateHeading kicker="Connection" tone="error">
            Signal lost
          </StateHeading>
          <p className="mt-4 max-w-md text-sm font-light leading-relaxed text-muted-foreground">
            {error ??
              "If this app was just deployed, check that FRONTEND_ORIGINS on the API includes this app's origin."}
          </p>
          <Button
            variant="outline"
            className="mt-8 h-12 px-8"
            onClick={() => window.location.reload()}
          >
            Retry
          </Button>
        </>
      )}

      {status === "ready" && (
        <>
          <StateHeading kicker="Live session">Session connected</StateHeading>
          <Link
            href="/studio/flows"
            className="mt-6 rounded-md bg-primary px-6 py-3 text-sm"
          >
            Open Flow workspace
          </Link>
          <div className="mt-8 flex items-baseline gap-3">
            <span className="font-mono text-6xl font-medium text-primary">
              {pipelineCount}
            </span>
            <span className="film-slate text-muted-foreground">
              concept{pipelineCount === 1 ? "" : "s"} on the board
            </span>
          </div>
          <p className="mt-8 max-w-md text-sm font-light leading-relaxed text-muted-foreground">
            This is a placeholder — the real studio interface (composer, board,
            queue) replaces this page once the cinematic design is ready to wire
            in.
          </p>
          <Button
            variant="outline"
            className="mt-8 h-12 px-8"
            onClick={signOut}
          >
            Sign out
          </Button>
        </>
      )}
    </StudioShell>
  );
}

function StateHeading({
  children,
  kicker,
  tone = "default",
}: {
  children: React.ReactNode;
  kicker?: string;
  tone?: "default" | "error";
}) {
  return (
    <div className="flex flex-col items-center gap-3">
      {kicker && (
        <span
          className={`kicker ${tone === "error" ? "text-destructive" : ""}`}
        >
          {kicker}
        </span>
      )}
      <h1
        className={`display text-4xl sm:text-5xl ${
          tone === "error" ? "text-destructive" : "text-foreground"
        }`}
      >
        {children}
      </h1>
    </div>
  );
}

const STATUS_LABEL: Record<Status, string> = {
  checking: "Standby",
  "signed-out": "Locked",
  ready: "Live",
  error: "Fault",
};

function StudioShell({
  status,
  children,
}: {
  status: Status;
  children: React.ReactNode;
}) {
  return (
    <main className="relative z-10 flex min-h-screen flex-col">
      {/* Studio bar -- keeps the brand present on the product surface. */}
      <header className="border-b border-border/60">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-6">
          <Link href="/" className="group flex items-center gap-2.5">
            <ApertureMark className="h-5 w-5 text-primary transition-transform duration-500 group-hover:rotate-45" />
            <span className="display text-lg tracking-normal">
              ZERO<span className="text-primary">PAGE</span>
              <span className="ml-2 text-muted-foreground">STUDIO</span>
            </span>
          </Link>
          <div className="flex items-center gap-2.5 border border-border/60 px-3 py-1.5">
            <span
              aria-hidden
              className={`h-1.5 w-1.5 rounded-full ${
                status === "ready"
                  ? "bg-primary animate-aperture"
                  : status === "error"
                    ? "bg-destructive"
                    : "bg-muted-foreground/50"
              }`}
            />
            <span
              className={`film-slate ${
                status === "ready"
                  ? "text-primary"
                  : status === "error"
                    ? "text-destructive"
                    : "text-muted-foreground"
              }`}
            >
              {STATUS_LABEL[status]}
            </span>
          </div>
        </div>
      </header>

      {/* Centered stage -- letterboxed, grain from the global overlay. */}
      <div className="relative flex flex-1 items-center justify-center overflow-hidden px-6 py-20">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-60"
          style={{
            background:
              "radial-gradient(50% 50% at 50% 45%, rgba(228,0,43,0.10), transparent 70%)",
          }}
        />
        <div className="relative flex max-w-lg flex-col items-center text-center">
          {children}
        </div>
      </div>
    </main>
  );
}
