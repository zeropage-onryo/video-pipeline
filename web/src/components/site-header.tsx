"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { ChevronDown } from "lucide-react";
import { NavigationMenu as Menu } from "@base-ui/react/navigation-menu";
import { Button } from "@/components/ui/button";
import { goToSignIn } from "@/lib/api";
import { Wordmark } from "@/components/wordmark";
import { skinClass, useTone } from "@/components/editorial-skin";
import { MAKE_PAGES, makePath } from "@/landing-pages/pages";

// Fixed 60px bar: transparent while the page is at the top, glass (blur +
// hairline) once scrolled. The state is written to a data attribute the
// CSS reads (`.glass-nav[data-at-top]`) rather than React state, so the
// scroll listener never re-renders the tree.
//
// "Solutions" (Mike, 2026-10-02) sits right of "How it works" and opens a
// panel listing every /make landing page by its short `menu` line, off the
// same list the footer and the sitemap read -- adding a page adds the row.
const BEFORE = [{ href: "/#how", label: "How it works" }];
const AFTER = [
  { href: "/models", label: "Models" },
  { href: "/pricing", label: "Pricing" },
  { href: "/faq", label: "FAQ" },
];

const ITEM =
  "inline-flex h-9 items-center rounded-md px-3 text-[13.5px] tracking-[-0.005em] text-[var(--nav-fg)] transition-colors outline-none hover:bg-secondary hover:text-foreground focus-visible:bg-secondary focus-visible:text-foreground";

export function SiteHeader() {
  const bar = useRef<HTMLElement>(null);
  // The Solutions panel portals to <body>, outside the skin wrapper, so it
  // carries the page's tone itself or it draws dark on a white page.
  const tone = useTone();

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
        <Wordmark intro />

        <Menu.Root className="hidden md:block" aria-label="Site">
          <Menu.List className="flex items-center gap-1">
            {BEFORE.map((link) => (
              <Menu.Item key={link.href}>
                <Menu.Link render={<Link href={link.href} />} className={ITEM}>
                  {link.label}
                </Menu.Link>
              </Menu.Item>
            ))}

            <Menu.Item>
              <Menu.Trigger className={`${ITEM} group/solutions gap-1 data-popup-open:bg-secondary data-popup-open:text-foreground`}>
                Solutions
                <ChevronDown
                  aria-hidden
                  strokeWidth={1.75}
                  className="size-3.5 transition-transform duration-200 group-data-popup-open/solutions:rotate-180"
                />
              </Menu.Trigger>
              <Menu.Content className="w-[300px] p-1.5 data-ending-style:opacity-0 data-starting-style:opacity-0 transition-opacity duration-200">
                <ul className="flex flex-col">
                  {MAKE_PAGES.map((page) => (
                    <li key={page.slug}>
                      <Menu.Link
                        render={<Link href={makePath(page.slug)} />}
                        closeOnClick
                        className="block rounded-md px-3 py-2.5 transition-colors outline-none hover:bg-secondary focus-visible:bg-secondary"
                      >
                        <span className="block text-[14px] font-medium tracking-[-0.005em] text-foreground">
                          {page.menu}
                        </span>
                        <span className="mt-0.5 block text-[12.5px] leading-snug text-[var(--ink-3)]">
                          {page.subhead}
                        </span>
                      </Menu.Link>
                    </li>
                  ))}
                </ul>
              </Menu.Content>
            </Menu.Item>

            {AFTER.map((link) => (
              <Menu.Item key={link.href}>
                <Menu.Link render={<Link href={link.href} />} className={ITEM}>
                  {link.label}
                </Menu.Link>
              </Menu.Item>
            ))}
          </Menu.List>

          <Menu.Portal>
            <Menu.Positioner
              side="bottom"
              sideOffset={6}
              align="start"
              className={`${skinClass(tone)} z-[60] h-(--positioner-height) w-(--positioner-width) max-w-(--available-width) text-foreground transition-[top,left] duration-200 data-instant:transition-none`}
            >
              <Menu.Popup className="h-(--popup-height) w-(--popup-width) origin-(--transform-origin) rounded-xl border border-border bg-popover text-popover-foreground shadow-[0_12px_40px_-12px_rgba(0,0,0,0.25)] transition-[opacity,transform,width,height] duration-200 outline-none data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0">
                <Menu.Viewport className="relative size-full overflow-hidden" />
              </Menu.Popup>
            </Menu.Positioner>
          </Menu.Portal>
        </Menu.Root>

        <div className="flex items-center gap-2">
          {/* Straight to the one sign-in door, the way InVideo and LTX
              Studio do it: both buttons open the same page, and the first
              pass through it creates the workspace. "Sign up" only
              asks for the sign-up heading. A visitor who is already signed
              in is handed on to /studio by the door itself. */}
          <Button variant="ghost" size="sm" className="text-foreground" onClick={() => goToSignIn()}>
            Log in
          </Button>
          <Button size="sm" onClick={() => goToSignIn("signup")}>
            Sign up
          </Button>
        </div>
      </div>
    </header>
  );
}
