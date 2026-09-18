"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Wordmark } from "@/components/wordmark";

// Fixed 60px bar: transparent while the page is at the top, glass (blur +
// hairline) once scrolled. The state is written to a data attribute the
// CSS reads (`.glass-nav[data-at-top]`) rather than React state, so the
// scroll listener never re-renders the tree.
const LINKS = [
  { href: "/#how", label: "How it works" },
  { href: "/#frames", label: "Frames" },
  { href: "/#work", label: "Who it's for" },
];

export function SiteHeader() {
  const bar = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    const update = () => {
      el.dataset.atTop = window.scrollY < 8 ? "true" : "false";
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  return (
    <header
      ref={bar}
      data-at-top="true"
      className="glass-nav fixed inset-x-0 top-0 z-50 border-b border-transparent"
    >
      <div className="mx-auto flex h-[60px] max-w-[1440px] items-center justify-between gap-10 px-6">
        <Wordmark />

        <nav className="hidden items-center gap-1 md:flex" aria-label="Site">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-md px-3 py-2 text-[13.5px] tracking-[-0.005em] text-[#c6c4c0] transition-colors hover:bg-secondary hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" className="text-foreground" render={<Link href="/studio" />}>
            Sign in
          </Button>
          <Button size="sm" render={<Link href="/studio" />}>
            Start creating
          </Button>
        </div>
      </div>
    </header>
  );
}
